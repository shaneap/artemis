"""Print every figure quoted in the owner-facing report, so it can be refreshed safely.

The report itself (`owner_report.html`) is hand-written prose -- generating that from a
template would make it worse, not better. But hand-written prose goes stale silently, which
is how a report ends up quoting numbers that no longer hold.

So this script does the other half: it recomputes every number the report cites, labelled and
grouped in the order they appear. Drop a newer export in, run this, and update the figures
against the output.

    python report_figures.py [path-to-export.csv]
"""

import sys

import numpy as np
import pandas as pd

import artemis

CSV = sys.argv[1] if len(sys.argv) > 1 else 'OrderDetails_2026_01_15-2026_07_15.csv'
EVENT_PRICES = {'Black Duck': 1200, 'Evangeline': 900}
DOW_ORDER = ['Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def heading(text):
    print(f'\n{text}\n' + '-' * len(text))


# --------------------------------------------------------------------------------------
raw = artemis.load_orders(CSV, verbose=False)
seated, _ = artemis.apply_duration_floor(raw)
seated = artemis.add_turn_gaps(seated)
occ = artemis.build_occupancy(seated)
res = seated[seated['Section'].isin(artemis.RESERVATION_SECTIONS)].copy()
NT = artemis.RESERVATION_TABLE_COUNT

heading('MASTHEAD')
print(f'period          {raw["Service_Date"].min():%-d %B %Y} to {raw["Service_Date"].max():%-d %B %Y}')
print(f'orders          {len(raw):,}')
print(f'trading nights  {res["Service_Date"].nunique()}')
print(f'recorded sales  ${raw["Amount"].sum():,.0f}')

# How full the room gets -- the claim the whole report rests on.
room = (occ[occ['Section'].isin(artemis.RESERVATION_SECTIONS)]
        .groupby(['Service_Date', 'Slot'])['Table'].nunique().rename('Tables').reset_index())
room['Room %'] = 100 * room['Tables'] / NT

heading('THE SHORT VERSION')
print(f'median room fullness while open   {room["Room %"].median():.0f}%')
print(f'highest ever observed             {room["Room %"].max():.0f}%')
print(f'15-min slots at full capacity     {(room["Tables"] == NT).sum()}')

# Q1 -- turn gaps against room fullness.
gaps = res[res['Turn_Gap'].notna()].copy()
gaps['Slot'] = ((gaps['Paid_DT'] - gaps['Service_Date']).dt.total_seconds() // 900).astype(int)
gaps = gaps.merge(room[['Service_Date', 'Slot', 'Room %']], on=['Service_Date', 'Slot'], how='left')
gaps['Room %'] = gaps['Room %'].fillna(0)
band = pd.cut(gaps['Room %'], [-1, 25, 50, 75, 100], labels=['under 1/4', '1/4-1/2', '1/2-3/4', 'over 3/4'])

heading('Q1  SEATING BACK TO BACK')
print(gaps.groupby(band, observed=True)['Turn_Gap']
          .agg(**{'turns': 'count', 'median gap': 'median'}).round(1).to_string())

achievable = gaps.loc[gaps['Room %'] > 75, 'Turn_Gap'].median()
blended = res['Amount'].sum() / (res['Duration'].sum() / 15)
peak = gaps[gaps['Paid_DT'].dt.hour.between(17, 22)]
naive = (peak['Turn_Gap'] - 15).clip(lower=0).sum() / 15 * blended * 2
real = ((peak.loc[peak['Room %'] > 75, 'Turn_Gap'] - achievable).clip(lower=0).sum()
        / 15 * blended * 2)
print(f'\nreset achieved when busy   {achievable:.0f} min')
print(f'value, demand-constrained  ${real:,.0f}/yr   <- the honest figure')
print(f'value, naive assumption    ${naive:,.0f}/yr')

# Q2 -- utilization by night.
night = res.groupby(['Service_Date', 'Service_DOW']).agg(
    first=('Opened_DT', 'min'), last=('Paid_DT', 'max'), used=('Duration', 'sum'))
night['available'] = ((night['last'] - night['first']).dt.total_seconds() / 60) * NT
by_dow = night.groupby('Service_DOW').agg(
    nights=('available', 'count'), available=('available', 'sum'), used=('used', 'sum'))
by_dow['sold %'] = (100 * by_dow['used'] / by_dow['available']).round(0)
by_dow['unsold table-hr/night'] = ((by_dow['available'] - by_dow['used'])
                                   / by_dow['nights'] / 60).round(0)

heading('Q2  REVENUE BY TIME OF DAY')
print(by_dow[['nights', 'sold %', 'unsold table-hr/night']].reindex(DOW_ORDER).to_string())

# Q3 -- what a table earns, by party size.
single = res[~res['Likely_Combined_Booking']].copy()
single['TPCPM'] = single['Amount'] / (single['Duration'] / 15)
econ = single.groupby('# of Guests').agg(**{
    'seatings': ('Amount', 'count'),
    'typical stay': ('Duration', 'median'),
    'per table-hour': ('TPCPM', lambda s: 4 * np.exp(np.log(s).mean())),
})

heading('Q3  VALUE PER PERSON / PER TABLE')
print(econ.round(0).head(8).to_string())
big = res[res['# of Guests'] >= 5]
print(f'\nparties of 5+: {100 * len(big) / len(res):.0f}% of seatings, '
      f'{100 * big["Amount"].sum() / res["Amount"].sum():.0f}% of table revenue')

# Event pricing.
heading('EVENT PRICING')
for section, price in EVENT_PRICES.items():
    section_occ = artemis.build_occupancy(seated[seated['Section'] == section])
    slots = section_occ.groupby(['Service_Date', 'Service_DOW', 'Slot'])['Slot_Revenue'].sum().reset_index()
    best = []
    for (date, dow), grp in slots.groupby(['Service_Date', 'Service_DOW']):
        series = grp.set_index('Slot')['Slot_Revenue']
        filled = series.reindex(range(series.index.min(), series.index.max() + 1), fill_value=0.0)
        if len(filled) >= 12:
            best.append({'dow': dow, 'best3h': filled.rolling(12).sum().max()})
    best = pd.DataFrame(best)
    med = best.groupby('dow')['best3h'].median()
    print(f'{section}: rate ${price}, typical best 3h ${best["best3h"].median():,.0f}, '
          f'beats {100 * (best["best3h"] < price).mean():.0f}% of nights, '
          f'best ever ${best["best3h"].max():,.0f}')
    print(f'    premium on Tuesday ${price - med.get("Tuesday", np.nan):,.0f} '
          f'vs Saturday ${price - med.get("Saturday", np.nan):,.0f}')

# Seating-policy answers.
heading('SEATING QUESTIONS')
e3 = res[res['Table'] == 'E3']
held = set()
for r in e3[e3['# of Guests'] <= 4].itertuples():
    a = int((r.Opened_DT - r.Service_Date).total_seconds() // 900)
    b = int((r.Paid_DT - r.Service_Date).total_seconds() // 900)
    held.update((r.Service_Date, s) for s in range(a, b + 1))
five_six = res[res['# of Guests'].between(5, 6)].copy()
five_six['Slot'] = ((five_six['Opened_DT'] - five_six['Service_Date']).dt.total_seconds() // 900).astype(int)
clash = sum((d, s) in held for d, s in zip(five_six['Service_Date'], five_six['Slot']))
print(f'E3 held by a party of <=4 when a 5/6 arrived: {clash} times '
      f'= once every {res["Service_Date"].nunique() / max(clash, 1):.1f} nights')

bd6 = res[res['Seating_Unit'] == 'BD 6-top banquette']
fives = bd6[bd6['# of Guests'] == 5]
if len(fives):
    rate = 4 * np.exp(np.log(fives['Amount'] / (fives['Duration'] / 15)).mean())
    print(f'parties of 5 on the BD 6-top banquette: {len(fives)}, ${rate:.0f} per table-hour')

allowance = {2: 90, 3: 90, 4: 105, 5: 120, 6: 120, 7: 120, 8: 120}
over = res[res['# of Guests'].map(allowance).notna()].copy()
over['Allowed'] = over['# of Guests'].map(allowance)
over = over[over['Duration'] > over['Allowed']].copy()
over['Slot'] = ((over['Paid_DT'] - over['Service_Date']).dt.total_seconds() // 900).astype(int)
over = over.merge(room[['Service_Date', 'Slot', 'Room %']], on=['Service_Date', 'Slot'], how='left')
pct_over = {s: round(100 * (res[res['# of Guests'] == s]['Duration'] > a).mean())
            for s, a in allowance.items() if (res['# of Guests'] == s).sum() >= 10}
print(f'overstay rate by party size: {pct_over}')
print(f'overstays while room >75% full: {100 * (over["Room %"].fillna(0) > 75).mean():.0f}%')

# Floor-plan correction and trend.
heading('FLOOR PLAN CORRECTION')
flag = (raw[raw['Section'].isin(artemis.RESERVATION_SECTIONS)].groupby('Section')
        .agg(orders=('Amount', 'count'), solo=('Exceeds_Solo_Capacity', 'sum'),
             unit=('Likely_Combined_Booking', 'sum')))
flag['before %'] = (100 * flag['solo'] / flag['orders']).round(0)
flag['after %'] = (100 * flag['unit'] / flag['orders']).round(0)
print(flag[['orders', 'before %', 'after %']].to_string())
print('\nseat totals: ' + ', '.join(
    f'{s} {artemis.section_seats(s)}' for s in ['Open Lounge', 'Black Duck', 'Evangeline', 'Bar']))

heading('TREND')
monthly = res.copy()
monthly['Month'] = monthly['Service_Date'].dt.to_period('M')
trend = monthly.groupby('Month').agg(
    nights=('Service_Date', 'nunique'), parties=('Amount', 'count'),
    avg_party=('# of Guests', 'mean'), revenue=('Amount', 'sum'))
trend['parties/night'] = (trend['parties'] / trend['nights']).round(1)
trend['revenue/night'] = (trend['revenue'] / trend['nights']).round(0)
print(trend[['nights', 'parties/night', 'avg_party', 'revenue/night']].round(2).to_string())

heading('EXCLUDED FROM TABLE FIGURES')
excluded = raw[raw['Order_Type'] != 'Seated'].groupby('Order_Type')['Amount'].agg(['count', 'sum'])
print(excluded.round(0).to_string())
