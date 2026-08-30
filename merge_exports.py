"""Merge successive Toast order exports into one continuous dataset.

Run directly after dropping a new pull into `data/exports/`:

    python merge_exports.py [--dry-run] [--exports-dir DIR] [--out PATH]

`artemis.load_orders()` also calls `build()` on its own when the merged file is out of date,
so in normal use the notebook just picks up a new export without anyone running this by hand.

This module deliberately imports nothing from `artemis`. It works at the raw-export schema
level, *below* every cleaning rule -- its job is to decide which rows exist, not which rows
count. Keeping the dependency one-way (artemis -> merge_exports) means a change to a cleaning
rule can never change the contents of the merged file.

Three properties of real Toast exports drive the design:

* **Schema drift.** Exports pulled at different times carry different columns. The 2026-01-15
  pull has `Total` and `Duration (Opened to Paid)`; the two earlier pulls have `Tax` and no
  duration at all. The schemas reconcile -- `Total == Amount + Tax + Tip + Gratuity` holds
  exactly on every overlapping row -- so each is derived from the other where it's missing.
  Duration cannot be reconstructed, so it stays null and the affected dates are reported.

* **Orders are amended after the fact.** The 6/5 6:37pm O1 check reads Tip 23.70 / Closed
  9:02pm in the 5/30 pull, and Tip 47.38 / Closed 6/6 6:01pm in the later one -- a tip
  finalized and a batch close-out. Deduplicating on row content would keep both and count the
  order twice. Rows are matched on *identity* instead, and the newest pull wins.

* **Distinct orders can share an identity.** About 0.7% of rows share
  (Opened, Table, # of Guests) -- split checks rung in the same minute, up to three deep.
  Collapsing them would lose real revenue, so each is given an occurrence index and matched
  across pulls positionally by check size.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent
EXPORTS_DIR = PROJECT_ROOT / 'data' / 'exports'
MERGED_PATH = PROJECT_ROOT / 'data' / 'orders_merged.csv'
META_PATH = PROJECT_ROOT / 'data' / 'orders_merged.meta.json'
EXPORT_GLOB = 'OrderDetails_*.csv'

# Columns every export must have. Anything missing here is a broken or wrongly-configured
# export and is worth failing loudly over rather than silently analysing a partial file.
CORE_COLUMNS = ['Opened', '# of Guests', 'Table', 'Discount Amount', 'Amount', 'Tip',
                'Gratuity', 'Closed']

# Present in some pulls, derived in others. See the module docstring.
DERIVED_COLUMNS = ['Tax', 'Total']
DURATION_COLUMN = 'Duration (Opened to Paid)'

MONEY_COLUMNS = ['Discount Amount', 'Amount', 'Tax', 'Tip', 'Gratuity', 'Total']
DATETIME_COLUMNS = ['Opened', 'Closed']

# What makes two rows the same order across two pulls. Deliberately excludes every field Toast
# can revise after service -- Amount, Tip, Gratuity, Closed -- since revision is exactly the
# case this has to survive.
IDENTITY_COLUMNS = ['Opened', 'Table', '# of Guests']

# Toast's own rendering, and what artemis.load_orders() parses. Output is written back in this
# format so the merged file is a drop-in for a raw export.
TOAST_DATETIME_FORMAT = '%m/%d/%y %I:%M %p'

# Only for the human-readable coverage report at the end of a merge -- no stored column depends
# on it. artemis.SERVICE_DAY_CUTOFF_HOUR is the canonical version; this copy exists so the
# dependency stays one-way (see the module docstring).
REPORT_SERVICE_DAY_CUTOFF_HOUR = 4

_FILENAME_RANGE = re.compile(r'_(\d{4})_(\d{2})_(\d{2})-(\d{4})_(\d{2})_(\d{2})')


# ------------------------------------------------------------------------------------------
# Source discovery and ordering
# ------------------------------------------------------------------------------------------

def _pull_order(path):
    """Sort key approximating when a file was pulled from Toast: (range end date, mtime).

    The end of an export's date range is the better signal -- a pull covering through 7/15 is
    necessarily later than one covering through 6/15, however the files were later copied
    around. mtime only breaks ties.
    """
    match = _FILENAME_RANGE.search(path.name)
    if match:
        end = datetime(int(match.group(4)), int(match.group(5)), int(match.group(6)))
    else:
        end = datetime.min
    return (end, path.stat().st_mtime)


def discover_exports(exports_dir=EXPORTS_DIR):
    """Every export in `exports_dir`, oldest pull first."""
    exports_dir = Path(exports_dir)
    if not exports_dir.is_dir():
        raise FileNotFoundError(
            f'No export directory at {exports_dir}. Create it and drop your '
            f'{EXPORT_GLOB} pulls in.')

    paths = sorted(exports_dir.glob(EXPORT_GLOB), key=_pull_order)
    if not paths:
        raise FileNotFoundError(f'No files matching {EXPORT_GLOB} in {exports_dir}.')

    undated = [p.name for p in paths if not _FILENAME_RANGE.search(p.name)]
    if undated:
        print(f'  ! {len(undated)} export(s) have no date range in the filename and are ordered '
              f'by modification time alone: {", ".join(undated)}')
    return paths


# ------------------------------------------------------------------------------------------
# Reading one export
# ------------------------------------------------------------------------------------------

def _parse_datetime(series, column, name):
    """Parse a Toast timestamp column, tolerating a future export using another format."""
    parsed = pd.to_datetime(series, format=TOAST_DATETIME_FORMAT, errors='coerce')
    unparsed = parsed.isna() & series.notna()
    if unparsed.any():
        print(f'  ! {name}: {unparsed.sum()} {column!r} value(s) are not in Toast\'s usual '
              f'{TOAST_DATETIME_FORMAT!r} format (e.g. {series[unparsed].iloc[0]!r}); '
              f'falling back to flexible parsing')
        parsed = pd.to_datetime(series, format='mixed', errors='coerce')
    return parsed


def read_export(path, verbose=True):
    """Read one export into the canonical schema.

    Returns `(df, stats)`. The frame carries the core columns, `Tax`/`Total` (derived where the
    export omits one), the duration string (null where the export has no such column), any
    extra columns the export happened to include, and provenance.
    """
    path = Path(path)
    name = path.name

    # Everything as string: a report-chunk header repeated mid-file puts the literal 'Opened'
    # in the Opened column, which would otherwise make pandas type the whole file as object
    # anyway -- and coercing after the header rows are gone is the only correct order.
    raw = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[''])

    missing = [c for c in CORE_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(
            f'{name} is missing required column(s): {", ".join(missing)}. '
            f'Re-export from Toast with at least: {", ".join(CORE_COLUMNS)}.')

    # Toast concatenates report chunks into one file, repeating the header at each boundary and
    # overlapping the chunks' date ranges by part of a day. Track which chunk each row came from
    # before dropping the header rows.
    is_header = raw['Opened'] == 'Opened'
    chunk = is_header.cumsum()
    df = raw[~is_header].copy()
    df['Source_Chunk'] = chunk[~is_header]

    for column in MONEY_COLUMNS:
        if column in df.columns:
            # Rounded because the same value is written '0' by one export and '0.00' by another,
            # and these columns are compared across pulls.
            df[column] = pd.to_numeric(df[column], errors='coerce').round(2)
    df['# of Guests'] = pd.to_numeric(df['# of Guests'], errors='coerce').astype('Int64')

    for column in DATETIME_COLUMNS:
        df[column] = _parse_datetime(df[column], column, name)

    # Tax and Total are the same information twice: Total = Amount + Tax + Tip + Gratuity.
    # Whichever the export omits is reconstructed so both are always available downstream.
    components = df['Amount'] + df['Tip'] + df['Gratuity']
    if 'Total' not in df.columns and 'Tax' in df.columns:
        df['Total'] = (components + df['Tax']).round(2)
    elif 'Tax' not in df.columns and 'Total' in df.columns:
        df['Tax'] = (df['Total'] - components).round(2)
    for column in DERIVED_COLUMNS:
        if column not in df.columns:
            df[column] = np.nan

    # Duration is the one field that genuinely cannot be reconstructed -- Closed reflects a
    # late/batch POS close-out, not guest departure. Dates covered only by an export without it
    # are invisible to the turn-gap and occupancy layers, and get reported as such.
    has_duration = DURATION_COLUMN in df.columns
    if not has_duration:
        df[DURATION_COLUMN] = pd.NA

    known = set(CORE_COLUMNS) | set(DERIVED_COLUMNS) | {DURATION_COLUMN, 'Source_Chunk'}
    extras = [c for c in df.columns if c not in known]
    if extras and verbose:
        print(f'  ! {name}: carrying through {len(extras)} column(s) this pipeline does not '
              f'model: {", ".join(extras)}')

    df['Source_File'] = name

    # Exact duplicates within one pull are always artifacts, never two real checks: no report
    # chunk contains an internal full-row duplicate, so every one of these comes from two
    # chunks of the same pull overlapping by part of a day.
    rows_read = len(df)
    content = _content_columns(df)
    df = df.drop_duplicates(subset=content).copy()

    stats = {
        'name': name,
        'rows_read': rows_read,
        'chunks': int(chunk.max()) + 1,
        'duplicates_dropped': rows_read - len(df),
        'rows': len(df),
        'has_duration': has_duration,
        'extras': extras,
    }
    return _add_occurrence(df), stats


def _content_columns(df):
    """Every column that carries data, i.e. all but provenance."""
    return [c for c in df.columns if c not in ('Source_File', 'Source_Chunk', 'Occurrence')]


def _add_occurrence(df):
    """Number rows that share an identity, so split checks survive and still match across pulls.

    Ordering within a group is by check size rather than file order: when one of three checks
    rung at the same minute has its tip finalized in a later pull, sorting by the fields that
    don't move is what keeps it matched to its own earlier version rather than a sibling's.
    """
    order = df.sort_values(IDENTITY_COLUMNS + ['Amount', 'Discount Amount'],
                           kind='stable', na_position='first')
    df['Occurrence'] = order.groupby(
        [order['Opened'], order['Table'].fillna(''), order['# of Guests'].fillna(-1)],
        sort=False, dropna=False,
    ).cumcount().reindex(df.index)
    return df


# ------------------------------------------------------------------------------------------
# Merging
# ------------------------------------------------------------------------------------------

def _merge_key(df):
    """The columns that identify one order across pulls."""
    return [df['Opened'], df['Table'].fillna(''), df['# of Guests'].fillna(-1), df['Occurrence']]


def identity_keys(df):
    """The set of orders a frame contains, as the merge identifies them.

    Works on a raw export or on the merged file. This is the merge's contract in one function:
    two rows with the same key are the same order seen in two pulls, and two rows with
    different keys are two different orders.
    """
    if 'Occurrence' not in df.columns:
        df = _add_occurrence(df.copy())
    return set(zip(*_merge_key(df)))


def merge_sources(frames):
    """Upsert a list of (df, stats) oldest-pull-first into one continuous frame.

    Newest pull wins, field by field: `GroupBy.last()` takes the last *non-null* value in each
    column, so a later pull's revised tip replaces the earlier one while a column that later
    pull doesn't carry at all -- Duration, when the report is reconfigured -- keeps the value
    the earlier pull supplied.
    """
    stacked = pd.concat(
        [df.assign(Pull_Rank=rank) for rank, (df, _) in enumerate(frames)],
        ignore_index=True, sort=False,
    )
    stacked = stacked.sort_values('Pull_Rank', kind='stable')

    content = _content_columns(stacked.drop(columns='Pull_Rank'))
    key = pd.MultiIndex.from_arrays(_merge_key(stacked))

    final = stacked.groupby(key, sort=False, dropna=False)[content + ['Source_File']].last()

    stats = _source_stats(stacked, key, final, content, [s for _, s in frames])
    return final.reset_index(drop=True), stats


def _render(df):
    """Render values for comparison, elementwise rather than via a vectorised `astype(str)`.

    These columns mix nullable integers, floats and object dtypes, whose missing values
    stringify inconsistently -- and a null that renders differently in two pulls would read as
    a revision that never happened.
    """
    return df.map(lambda value: '' if pd.isna(value) else str(value))


def _source_stats(stacked, key, final, content, source_stats):
    """Per-source accounting: what each pull contributed that no earlier one had, and what a
    later pull went on to revise.

    A row counts as *superseded* only when a value it actually supplied was overwritten. The
    distinction matters: every row in an export with no duration column differs from the merged
    result in that column, but that is the coalesce doing its job, not a revision -- comparing
    on supplied (non-null) fields only is what keeps the number meaningful.
    """
    ranks = stacked['Pull_Rank']
    first_rank = ranks.groupby(key, sort=False).transform('min')
    last_rank = ranks.groupby(key, sort=False).transform('max')

    supplied = stacked[content].notna()
    merged_values = final[content].reindex(key).set_axis(stacked.index)
    overwritten = (_render(stacked[content]) != _render(merged_values)) & supplied

    is_new = ranks == first_rank
    is_earlier = ranks < last_rank
    is_revised = is_earlier & overwritten.any(axis=1)

    for rank, stats in enumerate(source_stats):
        rows = ranks == rank
        stats['new'] = int(is_new[rows].sum())
        stats['superseded'] = int(is_revised[rows].sum())
        stats['identical'] = int((is_earlier & ~is_revised)[rows].sum())
    return source_stats


# ------------------------------------------------------------------------------------------
# Reporting
# ------------------------------------------------------------------------------------------

def service_dates(df):
    """Service date per row, for the coverage report only -- a night running to 1:30am belongs
    to the night it started. See REPORT_SERVICE_DAY_CUTOFF_HOUR."""
    return (df['Opened'] - pd.Timedelta(hours=REPORT_SERVICE_DAY_CUTOFF_HOUR)).dt.normalize()


def _contiguous_runs(days):
    """Group days into (first, last) runs of consecutive dates."""
    days = pd.DatetimeIndex(sorted(set(days)))
    if days.empty:
        return []

    runs, start, previous = [], days[0], days[0]
    for day in days[1:]:
        if (day - previous).days > 1:
            runs.append((start, previous))
            start = day
        previous = day
    runs.append((start, previous))
    return runs


def _missing_runs(dates, min_run=2):
    """Runs of consecutive days with no orders at all, within the span the data covers.

    A single missing day is routine -- the bar is closed Mondays -- so only runs of `min_run`
    or more are worth surfacing as a possible hole in the exports.
    """
    present = pd.DatetimeIndex(sorted(set(dates)))
    if len(present) < 2:
        return []
    missing = pd.date_range(present.min(), present.max(), freq='D').difference(present)
    return [run for run in _contiguous_runs(missing) if (run[1] - run[0]).days + 1 >= min_run]


def _format_range(start, end):
    return f'{start.date()}' if start == end else f'{start.date()} to {end.date()}'


def report(merged, stats, sources):
    """Print what the merge did. This is the whole point of --dry-run."""
    print(f'\nSources ({len(sources)}), oldest pull first:')
    for stats_row, path in zip(stats, sources):
        duration = 'with duration' if stats_row['has_duration'] else 'NO duration column'
        print(f"  {stats_row['name']}")
        print(f"    {stats_row['rows_read']:>6} rows in {stats_row['chunks']} report chunk(s), "
              f"{stats_row['duplicates_dropped']} exact duplicate(s) dropped  ({duration})")
        print(f"    {stats_row['new']:>6} first seen in this pull   "
              f"{stats_row['superseded']:>6} later revised   "
              f"{stats_row['identical']:>6} confirmed unchanged by a later pull")

    dates = service_dates(merged)
    print(f'\nMerged: {len(merged)} orders across {dates.nunique()} service days '
          f'({dates.min().date()} to {dates.max().date()}).')

    gaps = _missing_runs(dates)
    if gaps:
        print('  ! Possible export gaps (2+ consecutive days with no orders):')
        for start, end in gaps:
            print(f'      {_format_range(start, end)}  ({(end - start).days + 1} days)')

    # Dates with no duration data at all are absent from the turn-gap and occupancy layers,
    # which is a silent hole in every time-of-night chart unless it's stated here.
    has_duration = merged[DURATION_COLUMN].notna()
    print(f'  Duration present on {has_duration.sum()} of {len(merged)} orders.')

    by_date = has_duration.groupby(dates).mean()
    blind = by_date[by_date == 0].index
    if len(blind):
        print(f'  ! {len(blind)} service day(s) have no duration data at all, and are excluded '
              f'from turn-gap and occupancy analysis:')
        for start, end in _contiguous_runs(blind):
            print(f'      {_format_range(start, end)}')


# ------------------------------------------------------------------------------------------
# Building and staleness
# ------------------------------------------------------------------------------------------

def _source_fingerprint(path):
    stat = path.stat()
    return {'name': path.name, 'mtime': round(stat.st_mtime, 3), 'size': stat.st_size}


def _output_columns(merged):
    known = CORE_COLUMNS + DERIVED_COLUMNS + [DURATION_COLUMN]
    extras = [c for c in merged.columns if c not in known and c != 'Source_File']
    return known + extras + ['Source_File']


def build(exports_dir=EXPORTS_DIR, out_path=MERGED_PATH, meta_path=META_PATH,
          dry_run=False, verbose=True):
    """Merge every export in `exports_dir` and write the canonical dataset.

    Returns the merged frame. With `dry_run`, reports but writes nothing.
    """
    sources = discover_exports(exports_dir)
    if verbose:
        print(f'Merging {len(sources)} export(s) from {Path(exports_dir)}')

    frames = [read_export(path, verbose=verbose) for path in sources]
    merged, stats = merge_sources(frames)
    merged = merged.sort_values(['Opened', 'Table'], kind='stable').reset_index(drop=True)

    if verbose:
        report(merged, stats, sources)

    if dry_run:
        if verbose:
            print('\n(dry run -- nothing written)')
        return merged

    out_path, meta_path = Path(out_path), Path(meta_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = merged[_output_columns(merged)].copy()
    for column in DATETIME_COLUMNS:
        written[column] = written[column].dt.strftime(TOAST_DATETIME_FORMAT)
    written.to_csv(out_path, index=False)

    meta_path.write_text(json.dumps({
        'generated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'merged_rows': len(merged),
        'sources': [_source_fingerprint(p) for p in sources],
    }, indent=2) + '\n')

    if verbose:
        print(f'\nWrote {out_path} ({len(merged)} rows) and {meta_path.name}.')
    return merged


def is_stale(exports_dir=EXPORTS_DIR, out_path=MERGED_PATH, meta_path=META_PATH):
    """Whether the merged file needs rebuilding: missing, or built from a different set of
    exports than what's on disk now."""
    out_path, meta_path = Path(out_path), Path(meta_path)
    if not out_path.exists() or not meta_path.exists():
        return True
    try:
        recorded = json.loads(meta_path.read_text())['sources']
    except (ValueError, KeyError):
        return True
    current = [_source_fingerprint(p) for p in discover_exports(exports_dir)]
    return recorded != current


def ensure_merged(exports_dir=EXPORTS_DIR, out_path=MERGED_PATH, meta_path=META_PATH,
                  verbose=True):
    """Path to an up-to-date merged file, rebuilding it first if the exports have changed."""
    if is_stale(exports_dir, out_path, meta_path):
        if verbose:
            print(f'{Path(out_path).name} is out of date with {Path(exports_dir)} -- rebuilding.')
        build(exports_dir, out_path, meta_path, verbose=verbose)
    return Path(out_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--dry-run', action='store_true',
                        help='report what would be merged without writing anything')
    parser.add_argument('--exports-dir', default=EXPORTS_DIR, type=Path,
                        help=f'directory of raw Toast exports (default: {EXPORTS_DIR})')
    parser.add_argument('--out', default=MERGED_PATH, type=Path,
                        help=f'merged output path (default: {MERGED_PATH})')
    args = parser.parse_args(argv)

    meta = args.out.with_name(args.out.stem + '.meta.json')
    build(args.exports_dir, args.out, meta, dry_run=args.dry_run)
    return 0


if __name__ == '__main__':
    sys.exit(main())
