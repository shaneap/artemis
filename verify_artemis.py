"""Verification checks for the artemis pipeline. Run directly: `python verify_artemis.py`

These are the checks that were run by hand when the time layer was built. Keeping them as a
script means a future change to a cleaning rule or the service-day cutoff can't silently break
the occupancy/turn-gap reconstruction.

No test framework -- just prints PASS/FAIL and exits nonzero if anything fails.
"""

import sys

import pandas as pd

import artemis

CSV = 'OrderDetails_2026_01_15-2026_07_15.csv'
EXPECTED_ROWS = 6233  # matches the notebook's own post-clean count

results = []


def check(name, passed, detail=''):
    results.append((name, passed, detail))
    print(f'{"PASS" if passed else "FAIL"}  {name}' + (f'  --  {detail}' if detail else ''))


df = artemis.load_orders(CSV, verbose=False)

check('row count matches notebook post-clean count',
      len(df) == EXPECTED_ROWS, f'{len(df)} rows (expected {EXPECTED_ROWS})')

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

print()
failed = [n for n, ok, _ in results if not ok]
if failed:
    print(f'{len(failed)} check(s) FAILED: {", ".join(failed)}')
    sys.exit(1)
print(f'All {len(results)} checks passed.')
