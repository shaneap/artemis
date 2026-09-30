"""Load Toast exports into the raw schema exactly as received (Phase 1, D003/D010/D011).

    python3 load_raw.py [--exports-dir data/exports]

Each file is fingerprinted (SHA256). A file whose fingerprint is already in
raw.load_log is skipped; any other file is stored in a single transaction -- the
log row and every data row commit together or not at all. Nothing is converted,
trimmed or de-duplicated; a blank cell is stored as the empty string.

Connection settings come from .env / the environment (see .env.example).
"""
import argparse
import csv
import hashlib
import os
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent
EXPORTS_DIR = ROOT / "data" / "exports"

# Export layouts: exact header -> (export_type, raw table). A header that matches
# none of these is refused rather than guessed at; a new layout needs a new table.
LAYOUTS = {
    ("Opened", "# of Guests", "Table", "Discount Amount", "Amount", "Tip", "Gratuity",
     "Total", "Closed", "Duration (Opened to Paid)"): ("A", "order_details_a"),
    ("Opened", "# of Guests", "Table", "Discount Amount", "Amount", "Tax", "Tip",
     "Gratuity", "Closed"): ("B", "order_details_b"),
}


def connect_kwargs():
    """Connection parameters from .env, with real environment variables winning."""
    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    env.update(os.environ)
    return dict(
        host=env.get("POSTGRES_HOST", "localhost"),
        port=int(env.get("POSTGRES_PORT", 5432)),
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
        dbname=env["POSTGRES_DB"],
    )


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_export(path):
    """Return (header, rows) with rows as (physical_line_number, fields).

    Line numbers count the header as line 1. A line identical to the header (the
    01_15 export repeats it mid-file where two report chunks were joined) is not
    data and is left out; its line number stays unused. Raises ValueError if any
    row's width differs from the header's.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = tuple(next(reader))
        rows = []
        for fields in reader:
            if not fields:
                continue
            if tuple(fields) == header:
                continue
            if len(fields) != len(header):
                raise ValueError(
                    f"{Path(path).name} line {reader.line_num}: "
                    f"{len(fields)} fields, header has {len(header)}")
            rows.append((reader.line_num, fields))
    return header, rows


def load_file(conn, path):
    """Store one export in a single transaction. Returns row count, or None if skipped."""
    path = Path(path)
    file_hash = file_sha256(path)
    header, rows = read_export(path)
    if header not in LAYOUTS:
        raise ValueError(f"{path.name}: unrecognised header {list(header)}; "
                         "no raw table exists for this layout")
    export_type, table = LAYOUTS[header]

    with conn.transaction():
        row = conn.execute(
            "INSERT INTO raw.load_log (source_file, file_hash, export_type, row_count) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (file_hash) DO NOTHING RETURNING load_id",
            (path.name, file_hash, export_type, len(rows))).fetchone()
        if row is None:
            return None
        load_id = row[0]
        columns = ["load_id", "source_file", "source_row_number", *header]
        copy = sql.SQL("COPY {} ({}) FROM STDIN").format(
            sql.Identifier("raw", table),
            sql.SQL(", ").join(sql.Identifier(c) for c in columns))
        with conn.cursor() as cur, cur.copy(copy) as writer:
            for line_number, fields in rows:
                writer.write_row([load_id, path.name, line_number, *fields])
    return len(rows)


def load_all(conn, exports_dir=EXPORTS_DIR):
    """Load every CSV in exports_dir. Returns (loaded, skipped, rows_inserted)."""
    loaded = skipped = inserted = 0
    for path in sorted(Path(exports_dir).glob("*.csv")):
        count = load_file(conn, path)
        if count is None:
            skipped += 1
            print(f"skipped  {path.name} (already loaded)")
        else:
            loaded += 1
            inserted += count
            print(f"loaded   {path.name}: {count:,} rows")
    print(f"\n{loaded} file(s) loaded, {skipped} skipped, {inserted:,} rows inserted")
    return loaded, skipped, inserted


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--exports-dir", default=EXPORTS_DIR, type=Path)
    args = parser.parse_args()
    # autocommit: each file's conn.transaction() is then a real commit boundary.
    with psycopg.connect(**connect_kwargs(), autocommit=True) as conn:
        load_all(conn, args.exports_dir)


if __name__ == "__main__":
    main()
