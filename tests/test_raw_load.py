"""Tests for load_raw.py. Run:  python3 -m unittest tests.test_raw_load -v

Each test class gets a scratch database (created from sql/*.sql, dropped afterwards),
so the real warehouse is never touched. Needs a running PostgreSQL and the same
connection settings as load_raw.py; the role must be allowed to CREATE DATABASE.
The exports in data/exports/ are gitignored, so the tests that use them skip if absent.
"""
import csv
import random
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import load_raw  # noqa: E402

REAL_EXPORTS = sorted(load_raw.EXPORTS_DIR.glob("*.csv"))
HEADER_A = ",".join(next(iter(load_raw.LAYOUTS)))
TABLES = ("order_details_a", "order_details_b")


class ScratchDB(unittest.TestCase):
    """Fresh database per class, schema built by running sql/*.sql in order."""

    @classmethod
    def setUpClass(cls):
        cls.params = load_raw.connect_kwargs()
        cls.dbname = f"artemis_test_{uuid.uuid4().hex[:8]}"
        with psycopg.connect(**{**cls.params, "dbname": "postgres"}, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.dbname)))
        cls.conn = psycopg.connect(**{**cls.params, "dbname": cls.dbname}, autocommit=True)
        for path in sorted((ROOT / "sql").glob("*.sql")):
            cls.conn.execute(path.read_text())

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        with psycopg.connect(**{**cls.params, "dbname": "postgres"}, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                sql.Identifier(cls.dbname)))

    def setUp(self):
        self.conn.execute("TRUNCATE raw.load_log, raw.order_details_a, raw.order_details_b")

    def counts(self):
        return {t: self.conn.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("raw", t))).fetchone()[0]
            for t in (*TABLES, "load_log")}


def source_data_lines(path):
    """Independent of load_raw: physical lines of the file, split on the raw bytes."""
    text = Path(path).read_bytes().decode("utf-8")
    return text.replace("\r\n", "\n").split("\n")


@unittest.skipUnless(REAL_EXPORTS, "no exports in data/exports/")
class RealExports(ScratchDB):
    def test_second_run_changes_nothing(self):
        first = load_raw.load_all(self.conn)
        after_first = self.counts()
        second = load_raw.load_all(self.conn)
        self.assertEqual(first[0], len(REAL_EXPORTS))
        self.assertEqual(second, (0, len(REAL_EXPORTS), 0))
        self.assertEqual(self.counts(), after_first)

    def test_row_counts_match_source_files(self):
        load_raw.load_all(self.conn)
        for path in REAL_EXPORTS:
            lines = [ln for ln in source_data_lines(path) if ln]
            header = lines[0]
            expected = sum(1 for ln in lines if ln != header)   # data lines only
            table, = self.conn.execute(
                "SELECT CASE export_type WHEN 'A' THEN 'order_details_a' "
                "ELSE 'order_details_b' END FROM raw.load_log WHERE source_file = %s",
                (path.name,)).fetchone()
            stored = self.conn.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE source_file = %s").format(
                    sql.Identifier("raw", table)), (path.name,)).fetchone()[0]
            logged = self.conn.execute(
                "SELECT row_count FROM raw.load_log WHERE source_file = %s",
                (path.name,)).fetchone()[0]
            self.assertEqual(stored, expected, path.name)
            self.assertEqual(logged, expected, path.name)

    def test_rows_trace_back_to_their_source_line(self):
        load_raw.load_all(self.conn)
        seed = random.randrange(1 << 30)
        rng = random.Random(seed)
        for path in REAL_EXPORTS:
            lines = source_data_lines(path)
            table, = self.conn.execute(
                "SELECT CASE export_type WHEN 'A' THEN 'order_details_a' "
                "ELSE 'order_details_b' END FROM raw.load_log WHERE source_file = %s",
                (path.name,)).fetchone()
            query = sql.SQL("SELECT * FROM {} WHERE source_file = %s").format(
                sql.Identifier("raw", table))
            with self.conn.cursor() as cur:
                cur.execute(query, (path.name,))
                names = [d.name for d in cur.description]
                rows = cur.fetchall()
            # random rows, plus the first and last stored row of every file
            picks = rng.sample(rows, 25) + [min(rows, key=lambda r: r[2]),
                                            max(rows, key=lambda r: r[2])]
            for row in picks:
                record = dict(zip(names, row))
                line = lines[record["source_row_number"] - 1]
                fields = next(csv.reader([line]))
                stored = [record[c] for c in names[3:]]
                self.assertEqual(stored, fields,
                                 f"{path.name} line {record['source_row_number']} (seed {seed})")

    def test_repeated_header_line_is_not_stored(self):
        load_raw.load_all(self.conn)
        for table in TABLES:
            n = self.conn.execute(
                sql.SQL('SELECT count(*) FROM {} WHERE "Opened" = %s').format(
                    sql.Identifier("raw", table)), ("Opened",)).fetchone()[0]
            self.assertEqual(n, 0, table)


class SyntheticFiles(ScratchDB):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def write(self, name, body):
        path = self.tmp / name
        path.write_bytes(body.encode("utf-8"))
        return path

    def test_failure_partway_leaves_no_rows_behind(self):
        good = "\r\n".join(f"1/1/26 {h}:00 PM,2,O3,0,50,5,0,55,1/1/26 {h}:59 PM,0:59:00"
                           for h in range(1, 11))
        # a NUL byte is rejected by PostgreSQL text columns, at COPY time, after the
        # ten good rows above have already been sent
        bad = "1/1/26 11:00 PM,2,O3,0,50,5,0,55,1/1/26 11:59 PM,0:5\x009:00"
        path = self.write("broken.csv", f"{HEADER_A}\r\n{good}\r\n{bad}")
        with self.assertRaises(psycopg.Error):
            load_raw.load_file(self.conn, path)
        self.assertEqual(self.counts(), {"order_details_a": 0, "order_details_b": 0,
                                         "load_log": 0})

    def test_failed_file_does_not_block_a_later_good_load(self):
        row = "1/1/26 1:00 PM,2,O3,0,50,5,0,55,1/1/26 1:59 PM,0:59:00"
        bad = self.write("bad.csv", f"{HEADER_A}\r\n{row}\r\n{row}\x00")
        with self.assertRaises(psycopg.Error):
            load_raw.load_file(self.conn, bad)
        good = self.write("good.csv", f"{HEADER_A}\r\n{row}\r\n")
        self.assertEqual(load_raw.load_file(self.conn, good), 1)
        self.assertEqual(self.counts()["load_log"], 1)

    def test_ragged_row_is_refused_before_anything_is_written(self):
        path = self.write("ragged.csv", f"{HEADER_A}\r\n1/1/26 1:00 PM,2,O3\r\n")
        with self.assertRaises(ValueError):
            load_raw.load_file(self.conn, path)
        self.assertEqual(self.counts()["load_log"], 0)

    def test_unknown_header_is_refused(self):
        path = self.write("new_layout.csv", "Opened,Something New\r\n1/1/26,x\r\n")
        with self.assertRaises(ValueError):
            load_raw.load_file(self.conn, path)
        self.assertEqual(self.counts()["load_log"], 0)

    def test_same_bytes_under_a_new_name_is_skipped(self):
        row = "1/1/26 1:00 PM,2,O3,0,50,5,0,55,1/1/26 1:59 PM,0:59:00"
        a = self.write("a.csv", f"{HEADER_A}\r\n{row}\r\n")
        b = self.write("b.csv", f"{HEADER_A}\r\n{row}\r\n")
        self.assertEqual(load_raw.load_file(self.conn, a), 1)
        self.assertIsNone(load_raw.load_file(self.conn, b))

    def test_blank_cells_and_exact_duplicates_are_kept_as_received(self):
        row = "1/1/26 1:00 PM,2,,0,50,5,0,55,,"
        path = self.write("dups.csv", f"{HEADER_A}\r\n{row}\r\n{row}")   # no trailing newline
        self.assertEqual(load_raw.load_file(self.conn, path), 2)
        rows = self.conn.execute(
            'SELECT source_row_number, "Table", "Closed" FROM raw.order_details_a '
            "ORDER BY 1").fetchall()
        self.assertEqual(rows, [(2, "", ""), (3, "", "")])


if __name__ == "__main__":
    unittest.main()
