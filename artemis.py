"""Shared data pipeline for the Artemis bar analysis.

The notebook (`analysis.ipynb`) and any report generator both import from here so there is
exactly one copy of the loading/cleaning rules.

Two layers live in this module:

* **Per-order layer** (`load_orders`, `apply_duration_floor`) -- lifted verbatim from the
  notebook cells that already worked. This is what VPCPM/TPCPM are built on.
* **Time layer** (`add_service_day`, `add_turn_gaps`, `build_occupancy`) -- new. The
  per-order layer looks at one order at a time and so cannot see a table sitting empty
  between two parties; the time layer reconstructs what the floor actually looked like.
"""

from pathlib import Path

import numpy as np
import pandas as pd

import merge_exports

# --------------------------------------------------------------------------------------
# Data location
# --------------------------------------------------------------------------------------
#
# Raw Toast pulls accumulate in `data/exports/`; `merge_exports` upserts them into one
# continuous dataset. `load_orders()` with no argument reads that merged file and rebuilds it
# first if the exports have changed -- so pulling a fresh export and re-running is all it takes
# for every number here to extend. Passing an explicit path still loads a single raw export.

EXPORTS_DIR = merge_exports.EXPORTS_DIR
MERGED_PATH = merge_exports.MERGED_PATH


# --------------------------------------------------------------------------------------
# Floor plan
# --------------------------------------------------------------------------------------

RESERVATION_SECTIONS = ['Black Duck', 'Evangeline', 'Open Lounge']

# --- Seating units -------------------------------------------------------------------
#
# The POS table code is not the physical unit. Black Duck and Evangeline are banquettes
# subdivided into two codes each, and most Open Lounge tables pair up. A party booking a
# whole unit gets recorded against one of its codes, which is why measuring guests against
# per-code capacity flagged ~60% of Black Duck rows as "overbooked".
#
# The pairings are confirmed two ways: against Tock, and against the order data -- when a
# code hosts a party too large for it alone, its partner is empty 92-100% of the time,
# versus 20-66% for small parties. Non-adjacent control pairs show no such effect.
#
# Summing unit seats reproduces the operator's own section totals exactly:
# Open Lounge 22, Black Duck 14, Evangeline 10, Bar 12.
SEATING_UNITS = {
    # Black Duck: an 8-seat and a 6-seat banquette. The 6 splits "3 and 2" per the
    # operator's floor notes; the 8 splits into a 3-4 and a 4-5.
    'BD 8-top banquette': {'tables': ('BD3', 'BD5'), 'seats': 8},
    'BD 6-top banquette': {'tables': ('BD1', 'BD2'), 'seats': 6},

    # Evangeline: two 2-tops that push together into a 4, plus the 5/6-seater.
    'E 2+2 pair': {'tables': ('E1', 'E2'), 'seats': 4},
    'E3 large': {'tables': ('E3',), 'seats': 6},

    # Open Lounge: four confirmed combo pairs. O3 and O6 never combine -- 99% and 98% of
    # their orders are two-guest.
    'O1+O2': {'tables': ('O1', 'O2'), 'seats': 5},
    'O4+O5': {'tables': ('O4', 'O5'), 'seats': 4},
    'O7+O8': {'tables': ('O7', 'O8'), 'seats': 5},
    'O9+O10': {'tables': ('O9', 'O10'), 'seats': 4},
    'O3': {'tables': ('O3',), 'seats': 2},
    'O6': {'tables': ('O6',), 'seats': 2},

    # Bar stools are independent single seats, walk-up only.
    **{f'B{i}': {'tables': (f'B{i}',), 'seats': 1} for i in range(1, 13)},
}

# Reverse index: table code -> the unit it belongs to.
TABLE_TO_UNIT = {t: unit for unit, spec in SEATING_UNITS.items() for t in spec['tables']}

# Solo seat ranges -- what a code seats when its partner is being used separately. These
# are a soft guide (the banquettes flex); the binding constraint is the unit's seat count.
# B13/B14 are deliberately absent: standing-wait placeholders used when a guest is served
# while waiting for a real stool, not physical seats.
CAPACITY_RANGES = {f'B{i}': (1, 1) for i in range(1, 13)}
CAPACITY_RANGES.update({
    'BD1': (3, 4),  # larger half of the 6-top banquette
    'BD2': (2, 3),  # confirmed against Tock
    'BD3': (3, 4),  # confirmed against Tock
    'BD5': (4, 5),  # larger half of the 8-top banquette
    'E1': (2, 2),
    'E2': (2, 2),
    'E3': (5, 6),
    'O1': (3, 3),
    'O8': (3, 3),
})
CAPACITY_RANGES.update({f'O{i}': (2, 2) for i in range(1, 11) if f'O{i}' not in CAPACITY_RANGES})


def get_section(table):
    """Map a Toast table code to its seating section."""
    if pd.isna(table):
        return 'Unknown/To-Go'
    if table.startswith('BD'):
        return 'Black Duck'
    if table.startswith('B'):
        return 'Bar'
    if table.startswith('E'):
        return 'Evangeline'
    if table.startswith('O'):
        return 'Open Lounge'
    return 'Unknown'


def get_unit(table):
    """The physical seating unit a table code belongs to."""
    if pd.isna(table):
        return None
    return TABLE_TO_UNIT.get(table)


def unit_capacity(table):
    """Seats in the physical unit this table code belongs to (NaN if unmapped)."""
    unit = get_unit(table)
    return SEATING_UNITS[unit]['seats'] if unit else np.nan


def section_seats(section):
    """Total seats in a section, summed over physical units rather than POS codes."""
    return sum(spec['seats'] for spec in SEATING_UNITS.values()
               if get_section(spec['tables'][0]) == section)


def section_units(section):
    """Physical seating units in a section -- the real count of seatable spaces."""
    return [unit for unit, spec in SEATING_UNITS.items()
            if get_section(spec['tables'][0]) == section]


def table_count(section):
    """How many real (capacity-bearing) table codes a section has."""
    return sum(1 for t in CAPACITY_RANGES if get_section(t) == section)


RESERVATION_TABLE_COUNT = sum(table_count(s) for s in RESERVATION_SECTIONS)
RESERVATION_UNIT_COUNT = sum(len(section_units(s)) for s in RESERVATION_SECTIONS)
SECTION_SEATS = {s: section_seats(s) for s in RESERVATION_SECTIONS + ['Bar']}


# --------------------------------------------------------------------------------------
# Tuning constants
# --------------------------------------------------------------------------------------

GUEST_COUNT_SANITY_MAX = 20
DURATION_FLOOR_MINUTES = 15
SERVICE_DAY_CUTOFF_HOUR = 4

# Untabled orders split cleanly by check size, not by time of day. Above this threshold
# they are private events / catering / large pickups; below it they are ordinary to-go.
# Both are real revenue but neither is a seated table, so neither belongs in per-seat
# metrics. Tune here rather than in the notebook.
EVENT_AMOUNT_THRESHOLD = 400

# Seated durations above this are POS artifacts (checks left open overnight), not parties.
# They're kept in the per-order data but excluded from the occupancy timeline, where a
# single runaway row would otherwise mark a table occupied for days.
MAX_PLAUSIBLE_SEATING_MINUTES = 6 * 60


# --------------------------------------------------------------------------------------
# Per-order layer
# --------------------------------------------------------------------------------------

def load_orders(path=None, verbose=True):
    """Load and clean Toast order data.

    With no `path`, reads the merged dataset built from every export in `data/exports/`,
    rebuilding it first if a new pull has appeared -- see `merge_exports`. A path still loads a
    single raw export directly, which is what `report_figures.py`'s CLI argument does.

    Cleaning rules are lifted unchanged from the notebook; see the inline comments for the
    reasoning behind each one. Returns a dataframe with `Section`, parsed datetimes, a
    numeric `Duration` in minutes, capacity columns, and an `Order_Type` label.

    The `Duration >= 15min` floor is deliberately NOT applied here -- call
    `apply_duration_floor` for that, so the censoring it causes stays visible.
    """
    if path is None:
        path = merge_exports.ensure_merged(verbose=verbose)

    df = pd.read_csv(path)

    # A raw export is often two report chunks concatenated together: the header row repeats
    # mid-file and the two chunks' date ranges overlap by part of a day, producing
    # exact-duplicate order rows. That stray header row (a literal 'Opened' value in the Opened
    # column) is also why every column loads as string instead of numeric -- clean both before
    # anything else. Both are no-ops on the merged file, which `merge_exports` has already
    # resolved; they matter when a raw export is passed directly.
    df = df[df['Opened'] != 'Opened'].copy()
    duplicate_rows = df.duplicated().sum()
    df = df.drop_duplicates()

    # Which columns a pull carries varies -- older exports have `Tax` where newer ones have
    # `Total`, and `merge_exports` derives whichever is missing. Coerce what's actually here so
    # a raw export of either vintage still loads.
    numeric_cols = [c for c in ['# of Guests', 'Discount Amount', 'Amount', 'Tip', 'Gratuity',
                                'Tax', 'Total'] if c in df.columns]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric)

    # Amount is already net of any Discount Amount (confirmed: rows with a nonzero discount
    # still have Total > 0 even when Discount == Amount, which is only consistent with Amount
    # being the post-discount charge) -- so VPCPM/TPCPM are built on realized revenue, not list
    # price. Tip/Gratuity/Total/Discount Amount don't feed any metric; they're kept numeric for
    # reference (e.g. spot-checking a specific order).
    df = df[df['Amount'] > 0]

    # Guest counts up to 18 form a smooth, decreasing tail (consistent with legitimate large
    # combined-table bookings); a single row at 101 guests on a 1-seat bar stool has no such
    # support and is almost certainly a data-entry error, not a real party.
    implausible = df[df['# of Guests'] > GUEST_COUNT_SANITY_MAX]
    df = df[df['# of Guests'] <= GUEST_COUNT_SANITY_MAX]

    # BD4 is no longer an active table, but this export spans 7 months so its historical orders
    # are still present. Excluded entirely (not just from capacity checks) since it's not
    # actionable for any current seating decision.
    bd4_rows = (df['Table'] == 'BD4').sum()
    df = df[df['Table'] != 'BD4']

    df['Section'] = df['Table'].map(get_section)

    # Full datetimes are kept as their own columns. The notebook later overwrites the display
    # `Opened`/`Closed` columns with time-only strings, which destroys the date -- every
    # time-based analysis reads these instead.
    df['Opened_DT'] = pd.to_datetime(df['Opened'], format='%m/%d/%y %I:%M %p')
    df['Closed_DT'] = pd.to_datetime(df['Closed'], format='%m/%d/%y %I:%M %p')

    # Use Toast's own Duration (Opened to Paid) rather than Closed - Opened: Closed frequently
    # reflects a late/batch POS close-out, not actual guest departure, which inflates the
    # timestamp-diff version. Duration (Opened to Paid) is a 'H:MM:SS' string.
    #
    # Some Toast report configurations omit the column entirely, and it cannot be reconstructed
    # from Closed. Those rows get a null duration and drop out of every duration-dependent
    # layer on their own -- the >= floor, `build_occupancy`'s plausibility window, and
    # `add_turn_gaps` via a null Paid_DT. The verbose summary below says how many.
    if 'Duration (Opened to Paid)' in df.columns:
        df['Duration'] = pd.to_timedelta(df['Duration (Opened to Paid)']).dt.total_seconds() / 60
    else:
        df['Duration'] = np.nan

    # When the party actually settled up -- the other half of every turn-gap calculation.
    # Nine event/catering rows have no duration at all (nobody sat anywhere), so they get a
    # null paid time rather than a bogus one. Filling before the timedelta cast and masking
    # after avoids pandas' noisy NaT-cast warning.
    df['Paid_DT'] = df['Opened_DT'] + pd.to_timedelta(df['Duration'].fillna(0), unit='m')
    df.loc[df['Duration'].isna(), 'Paid_DT'] = pd.NaT

    df['Capacity_Min'] = df['Table'].map(lambda t: CAPACITY_RANGES.get(t, (np.nan, np.nan))[0])
    df['Capacity_Max'] = df['Table'].map(lambda t: CAPACITY_RANGES.get(t, (np.nan, np.nan))[1])

    # The physical unit the code belongs to, and how many seats that unit really has.
    df['Seating_Unit'] = df['Table'].map(get_unit)
    df['Unit_Capacity'] = df['Table'].map(unit_capacity)

    # Toast records one table code per order. When a party takes a whole banquette or pushes a
    # confirmed pair together, the check lands on one anchor code -- so guests exceeding that
    # *code's* solo capacity is normal, not a data problem.
    #
    # Exceeding the whole *unit's* capacity is the real signal of a multi-table booking that
    # spans units, which Toast genuinely cannot reconstruct. Flagging against unit capacity is
    # what makes Likely_Combined_Booking mean what its name says.
    df['Likely_Combined_Booking'] = df['# of Guests'] > df['Unit_Capacity']

    # The old per-code definition, kept so the difference stays measurable rather than silent.
    # This is the one that flagged ~60% of Black Duck rows, because it measured parties against
    # half a banquette.
    df['Exceeds_Solo_Capacity'] = df['# of Guests'] > df['Capacity_Max']

    df = classify_order_type(df)
    df = add_service_day(df)

    if verbose:
        print(f'Exact duplicate rows from overlapping export chunks: {duplicate_rows}')
        print(f'Excluded {len(implausible)} row(s) with implausible guest counts '
              f'(> {GUEST_COUNT_SANITY_MAX}).')
        print(f'Excluded {bd4_rows} row(s) from BD4 (retired table, no longer in service).')
        no_duration = int(df['Duration'].isna().sum())
        if no_duration:
            print(f'{no_duration} order(s) have no duration and are excluded from the '
                  f'turn-gap and occupancy layers.')
        print(f'Loaded {len(df)} orders, {df["Service_Date"].nunique()} service days '
              f'({df["Service_Date"].min().date()} to {df["Service_Date"].max().date()}).')

    return df.reset_index(drop=True)


def classify_order_type(df):
    """Label each order Seated / Event-Catering / To-Go.

    Previously everything without a table fell through the `Duration >= 15` floor and vanished
    from the analysis -- about $104K of real revenue, silently. These aren't seated tables so
    they don't belong in per-seat metrics, but they shouldn't disappear either.

    The split is by check size rather than time of day: untabled orders occur across the whole
    operating day, but a $2,200 untabled check is a catering/event booking whatever hour it was
    rung in, and a $40 one is a pickup. Durations on untabled rows are meaningless (they range
    up to 18 days) because nobody was sitting anywhere.
    """
    df = df.copy()
    untabled = df['Table'].isna()
    df['Order_Type'] = np.where(
        ~untabled, 'Seated',
        np.where(df['Amount'] >= EVENT_AMOUNT_THRESHOLD, 'Event-Catering', 'To-Go'),
    )
    return df


def apply_duration_floor(df, min_minutes=DURATION_FLOOR_MINUTES):
    """Drop implausibly short seated visits, and report what that censoring cost per section.

    The Bar is walk-up/quick-turnover so this filter is expected to remove a disproportionate
    share of Bar rows -- worth knowing before trusting any Bar statistic.

    Returns `(filtered_df, drop_summary)`.
    """
    pre_counts = df['Section'].value_counts()
    filtered = df[df['Duration'] >= min_minutes]
    post_counts = filtered['Section'].value_counts()

    drop_summary = pd.DataFrame({
        'Before': pre_counts,
        'After': post_counts.reindex(pre_counts.index).fillna(0).astype(int),
    })
    drop_summary['Dropped'] = drop_summary['Before'] - drop_summary['After']
    drop_summary['Drop %'] = (100 * drop_summary['Dropped'] / drop_summary['Before']).round(1)

    return filtered, drop_summary.sort_values('Drop %', ascending=False)


# --------------------------------------------------------------------------------------
# Time layer
# --------------------------------------------------------------------------------------

def add_service_day(df, cutoff_hour=SERVICE_DAY_CUTOFF_HOUR):
    """Attribute each order to the night it belongs to rather than the calendar date.

    A Friday that runs to 1:30am is all Friday. Dating orders by calendar date files that
    late-night revenue under Saturday, and is why a bar closed on Mondays shows Monday orders
    (Sunday-night spillover). Shifting back `cutoff_hour` fixes both.
    """
    df = df.copy()
    df['Service_Date'] = (df['Opened_DT'] - pd.Timedelta(hours=cutoff_hour)).dt.normalize()
    df['Service_DOW'] = df['Service_Date'].dt.day_name()
    # Minutes since midnight of the service date -- the x-axis for every time-of-night chart.
    # Past-midnight orders keep counting up (1:19am on a Friday night = 1519) so late slots
    # sort after evening ones instead of wrapping around to the start of the chart.
    df['Clock_Minutes'] = (df['Opened_DT'] - df['Service_Date']).dt.total_seconds() / 60
    return df


def verify_service_day_cutoff(df, cutoff_hour=SERVICE_DAY_CUTOFF_HOUR):
    """Check the cutoff falls in genuinely dead time -- i.e. no night's business spans it.

    If any order opens within the quiet window around the cutoff, the boundary is splitting a
    real service night in half and the cutoff needs moving. Returns the offending rows.
    """
    hour = df['Opened_DT'].dt.hour
    window = (hour >= cutoff_hour - 1) & (hour < cutoff_hour + 1)
    return df[window]


def add_turn_gaps(df):
    """Measure the dead time between one party paying and the next sitting at that table.

    This is the number the per-order layer structurally cannot see. For each table, within one
    service night, `Turn_Gap = next party's Opened - this party's Paid`.

    Two data artifacts are guarded:

    * **Cross-night pairs** -- the last party of Tuesday and the first of Wednesday are not a
      turn. Gaps are only computed within a single `Service_Date`.
    * **Overlapping orders** (~4% of consecutive same-table pairs) -- the next party appears to
      sit before the previous one paid. That's the combined-check artifact: one physical party's
      items split across two checks on the same table. These get `Turn_Gap = NaN` rather than a
      negative number, and are counted in `Turn_Overlap` so the rate stays visible.

    Adds `Turn_Gap` (minutes to the next party, NaN if none/invalid), `Turn_Overlap` (bool),
    and `Turn_Index` (1 = first party of the night at that table).
    """
    df = df.sort_values(['Table', 'Service_Date', 'Opened_DT']).copy()
    grp = df.groupby(['Table', 'Service_Date'], sort=False)

    next_opened = grp['Opened_DT'].shift(-1)
    gap = (next_opened - df['Paid_DT']).dt.total_seconds() / 60

    df['Turn_Overlap'] = gap < 0
    df['Turn_Gap'] = gap.where(gap >= 0)
    df['Turn_Index'] = grp.cumcount() + 1

    return df.sort_index()


def build_occupancy(df, slot_minutes=15, cutoff_hour=SERVICE_DAY_CUTOFF_HOUR):
    """Reconstruct which tables were occupied during each time slot of each night.

    Turns one-row-per-order into one-row-per-(night, table, slot): "at 8:15pm on Feb 13th,
    these 11 tables were full." Every time-of-day question -- when to open, when to staff up,
    when the room is actually busy -- is a query against this frame.

    Only seated orders with a plausible duration are included; a check left open overnight
    would otherwise mark its table occupied for days. Each order's revenue is spread evenly
    across the slots it occupies (`Slot_Revenue`) so revenue can be read off a clock.

    Returns a long dataframe with `Service_Date`, `Service_DOW`, `Table`, `Section`, `Slot`
    (slot index since the service night began), `Clock_Minutes` (minutes since midnight of the
    service date, so 1:30am reads as 1530), and `Slot_Revenue`.
    """
    seated = df[
        (df['Order_Type'] == 'Seated')
        & df['Duration'].between(0, MAX_PLAUSIBLE_SEATING_MINUTES)
    ]

    records = []
    for row in seated.itertuples():
        start_min = (row.Opened_DT - row.Service_Date).total_seconds() / 60
        end_min = (row.Paid_DT - row.Service_Date).total_seconds() / 60
        first = int(start_min // slot_minutes)
        last = int(end_min // slot_minutes)
        n_slots = last - first + 1
        revenue_per_slot = row.Amount / n_slots
        for slot in range(first, last + 1):
            records.append((
                row.Service_Date, row.Service_DOW, row.Table, row.Section,
                slot, slot * slot_minutes, revenue_per_slot,
            ))

    occ = pd.DataFrame(records, columns=[
        'Service_Date', 'Service_DOW', 'Table', 'Section',
        'Slot', 'Clock_Minutes', 'Slot_Revenue',
    ])
    # Clock_Minutes counts from midnight of the service date, so a 1:30am slot reads as 1530
    # rather than wrapping to 90 -- that keeps late-night slots sorting after evening ones.
    occ['Clock_Label'] = occ['Clock_Minutes'].map(_format_clock)
    return occ


def _format_clock(minutes):
    """Render minutes-since-service-midnight as a label, with past-midnight hours continuing
    past 24 (so 1:30am on a Friday night reads as 25:30 and sorts after 23:00)."""
    return f'{int(minutes // 60):02d}:{int(minutes % 60):02d}'


def utilization_by_slot(occ, sections=None, n_tables=None):
    """Average share of tables occupied in each slot, by day of week.

    `n_tables` defaults to the real table count of the sections requested, so the result is a
    true percentage of the floor rather than a raw count.
    """
    if sections is not None:
        occ = occ[occ['Section'].isin(sections)]
        if n_tables is None:
            n_tables = sum(table_count(s) for s in sections)
    if n_tables is None:
        n_tables = occ['Table'].nunique()

    nights = occ.groupby('Service_DOW')['Service_Date'].nunique()
    occupied = occ.groupby(['Service_DOW', 'Clock_Label', 'Clock_Minutes'])['Table'].nunique()
    revenue = occ.groupby(['Service_DOW', 'Clock_Label', 'Clock_Minutes'])['Slot_Revenue'].sum()

    out = pd.DataFrame({'Tables_Occupied': occupied, 'Revenue': revenue}).reset_index()
    out['Nights'] = out['Service_DOW'].map(nights)
    out['Utilization %'] = 100 * out['Tables_Occupied'] / (out['Nights'] * n_tables)
    out['Revenue Per Night'] = out['Revenue'] / out['Nights']
    return out.sort_values(['Service_DOW', 'Clock_Minutes'])
