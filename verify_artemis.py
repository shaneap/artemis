"""Verification checks for the artemis pipeline. Run directly: `python verify_artemis.py`

These are the checks that were run by hand when the time layer was built. Keeping them as a
script means a future change to a cleaning rule or the service-day cutoff can't silently break
the occupancy/turn-gap reconstruction.

No test framework -- just prints PASS/FAIL and exits nonzero if anything fails.
"""

import json
import sys

import pandas as pd

import artemis
import merge_exports

results = []


def check(name, passed, detail=''):
    results.append((name, passed, detail))
    print(f'{"PASS" if passed else "FAIL"}  {name}' + (f'  --  {detail}' if detail else ''))


# --- Floor plan -----------------------------------------------------------------------
# Summing the seating units must reproduce the operator's own section totals. If a unit's
# seat count or membership is edited carelessly, this is what catches it.
EXPECTED_SECTION_SEATS = {'Open Lounge': 22, 'Black Duck': 14, 'Evangeline': 10, 'Bar': 12}
for section, expected in EXPECTED_SECTION_SEATS.items():
    got = artemis.section_seats(section)
    check(f'{section} seat total', got == expected, f'{got} seats (expected {expected})')

# Every capacity-bearing table code must belong to exactly one unit.
unmapped = [t for t in artemis.CAPACITY_RANGES if artemis.get_unit(t) is None]
check('every table code maps to a seating unit', not unmapped, f'unmapped: {unmapped}')

seen = [t for spec in artemis.SEATING_UNITS.values() for t in spec['tables']]
check('no table code appears in two units', len(seen) == len(set(seen)),
      f'{len(seen)} memberships across {len(set(seen))} codes')


# --- Export merge -----------------------------------------------------------------------
# The merged dataset grows every time a new Toast pull lands, so there is no fixed row count to
# assert against. What must hold instead is that merging is lossless and unambiguous: no order
# appears twice, none is dropped, and the file agrees with the manifest it was built from.

merged_path = merge_exports.ensure_merged(verbose=False)
merged = pd.read_csv(merged_path, parse_dates=merge_exports.DATETIME_COLUMNS,
                     date_format=merge_exports.TOAST_DATETIME_FORMAT)
meta = json.loads(merge_exports.META_PATH.read_text())
sources = {path.name: merge_exports.read_export(path, verbose=False)[0]
           for path in merge_exports.discover_exports()}

merged_keys = merge_exports.identity_keys(merged)
check('no order appears twice in the merged dataset',
      len(merged_keys) == len(merged), f'{len(merged)} rows, {len(merged_keys)} distinct orders')

check('merged file agrees with its manifest',
      len(merged) == meta['merged_rows'],
      f"{len(merged)} rows, manifest says {meta['merged_rows']}")

check('merged dataset is current with the exports on disk',
      not merge_exports.is_stale(), f'{len(sources)} export(s) in {merge_exports.EXPORTS_DIR}')

# Every pull's orders must survive the merge. A newer pull may revise an order's tip or close
# time, but it can never make one disappear.
dropped = {name: len(merge_exports.identity_keys(frame) - merged_keys)
           for name, frame in sources.items()}
check('every order from every export survives into the merged dataset',
      not any(dropped.values()),
      ', '.join(f'{name}: {n} missing' for name, n in dropped.items()))

# Revenue conservation: on a service date whose merged rows all come from one pull, the merged
# total must equal that pull's own total. This is what would catch a merge that silently
# double-counted an overlapping date or dropped half of one.
merged_dates = merge_exports.service_dates(merged)
worst_date, worst_delta = None, 0.0
for name, frame in sources.items():
    source_dates = merge_exports.service_dates(frame)
    for date, source_rows in frame.groupby(source_dates):
        on_date = merged[merged_dates == date]
        if on_date.empty or set(on_date['Source_File']) != {name}:
            continue
        delta = abs(on_date['Amount'].sum() - source_rows['Amount'].sum())
        if delta > worst_delta:
            worst_date, worst_delta = f'{date.date()} ({name})', delta

check('revenue on single-source dates is conserved through the merge',
      worst_delta < 0.01, f'worst drift ${worst_delta:.2f}' +
      (f' on {worst_date}' if worst_date else ' -- every date matches'))


df = artemis.load_orders(verbose=False)

# The service-day cutoff has to fall in genuinely dead time, or it splits a real night in half.
spanning = artemis.verify_service_day_cutoff(df)
check('no orders open within an hour of the 4am service-day cutoff',
      len(spanning) == 0, f'{len(spanning)} orders in the 3am-5am window')

# Monday should be effectively empty once Sunday-night spillover is reattributed. What survives
# is catering/pickup rung in on a closed day, not seated business.
monday = df[df['Service_DOW'] == 'Monday']
monday_seated = (monday['Order_Type'] == 'Seated').sum()
check('Monday has no meaningful seated business (bar is closed Mondays)',
      monday_seated <= 2, f'{monday_seated} seated orders across {len(monday)} Monday rows')

# Every order gets exactly one type, and untabled revenue is no longer invisible.
check('every order is classified',
      df['Order_Type'].notna().all() and set(df['Order_Type']) <= {'Seated', 'Event-Catering', 'To-Go'},
      f'{dict(df["Order_Type"].value_counts())}')

seated, drop_summary = artemis.apply_duration_floor(df)
seated = artemis.add_turn_gaps(seated)
occ = artemis.build_occupancy(seated)

# Occupancy can never exceed the physical floor.
res_occ = occ[occ['Section'].isin(artemis.RESERVATION_SECTIONS)]
max_concurrent = res_occ.groupby(['Service_Date', 'Slot'])['Table'].nunique().max()
check('concurrent reservation-section tables never exceeds the real table count',
      max_concurrent <= artemis.RESERVATION_TABLE_COUNT,
      f'peak {max_concurrent} of {artemis.RESERVATION_TABLE_COUNT}')

# The hard one: for a table-night with no overlapping checks, occupied time plus gap time must
# exactly equal the span from first seating to last payment. If this drifts, the turn-gap
# reconstruction is wrong somewhere.
res = seated[seated['Section'].isin(artemis.RESERVATION_SECTIONS)]
residuals = []
overlap_nights = 0
for _, g in res.groupby(['Service_Date', 'Table']):
    if len(g) < 2:
        continue
    if g['Turn_Overlap'].any():
        overlap_nights += 1
        continue
    span = (g['Paid_DT'].max() - g['Opened_DT'].min()).total_seconds() / 60
    residuals.append(abs(span - (g['Duration'].sum() + g['Turn_Gap'].sum())))
worst = max(residuals) if residuals else 0.0
check('occupied time + gap time reconciles to the table-night span',
      worst < 0.01,
      f'worst residual {worst:.6f} min over {len(residuals)} clean table-nights '
      f'({overlap_nights} skipped for overlapping checks)')

# Gaps must never be negative or span two different nights.
gaps = seated['Turn_Gap'].dropna()
check('no negative turn gaps survive into Turn_Gap', (gaps >= 0).all(),
      f'{len(gaps)} measured turns, min {gaps.min():.1f} min')

# The seating units are a claim about physical furniture, and the order data can falsify it:
# if two codes really share one banquette, then whenever one hosts a party too big to fit its
# own half, the other must be empty. A pairing that drops below ~85% here is probably wrong.
occupied_slots = set(zip(occ['Service_Date'], occ['Table'], occ['Slot']))
worst_unit, worst_rate = None, 100.0
for unit, spec in artemis.SEATING_UNITS.items():
    if len(spec['tables']) != 2:
        continue
    for anchor, partner in (spec['tables'], spec['tables'][::-1]):
        solo_max = artemis.CAPACITY_RANGES.get(anchor, (0, 0))[1]
        big = seated[(seated['Table'] == anchor) & (seated['# of Guests'] > solo_max)]
        if len(big) < 20:
            continue
        slots = ((big['Opened_DT'] - big['Service_Date']).dt.total_seconds() // 900).astype(int)
        free = sum((d, partner, s) not in occupied_slots
                   for d, s in zip(big['Service_Date'], slots))
        rate = 100 * free / len(big)
        if rate < worst_rate:
            worst_unit, worst_rate = f'{anchor} (partner {partner}, n={len(big)})', rate

check('seating-unit partners are free when the unit is booked whole',
      worst_rate >= 85, f'weakest pairing: {worst_unit} at {worst_rate:.0f}% free')

print()
failed = [n for n, ok, _ in results if not ok]
if failed:
    print(f'{len(failed)} check(s) FAILED: {", ".join(failed)}')
    sys.exit(1)
print(f'All {len(results)} checks passed.')
