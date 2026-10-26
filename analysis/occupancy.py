"""How full do the reservation sections get, and what is faster turning worth?

    python3 analysis/occupancy.py      # prints the report and writes analysis/results/occupancy.md

Built on analytics.fact_table_occupancy, where a party seated across a banquette or a pushed-
together pair occupies every table it used, not just the one Toast rang it on. The old count
(recorded table only) is shown alongside, because it is what the "room never fills" finding
rested on.

Reservation sections only (Black Duck, Evangeline, Open Lounge); the table count each night is
the floor plan in force that day (17 tables now, 18-20 under the old layouts). A night is open
from its first seating to its last payment. Mondays are left out (closed; private bookings only).
A stay is Toast's opened-to-paid time, so real occupancy is a little higher than shown here.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.db import RESULTS, query  # noqa: E402

DAYS = ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
GAP_ALLOWANCES = (0, 15, 30)   # minutes between two parties on a table that still count as taken


def fill_short_gaps(row, allowance):
    """Mark idle runs of <= allowance minutes between two occupied minutes as occupied."""
    out = row.copy()
    if allowance == 0:
        return out
    busy = np.flatnonzero(row)
    for a, b in zip(busy, busy[1:]):
        if 1 < b - a <= allowance + 1:
            out[a + 1:b] = True
    return out


def nights(occ, floor):
    """Per night: a tables x minutes boolean grid for both counting rules."""
    for date, g in occ.groupby("service_date"):
        tables = floor[(floor.valid_from <= date) & (floor.valid_to.isna() | (floor.valid_to > date))]
        index = {t: i for i, t in enumerate(sorted(tables.table_code))}
        lo, hi = int(g.start.min()), int(np.ceil(g.end.max()))
        grids = {}
        for rule, rows in (("new", g), ("old", g[g.is_recorded_table])):
            grid = np.zeros((len(index), hi - lo), bool)
            for r in rows.itertuples():
                if r.table_code in index:
                    grid[index[r.table_code], int(r.start) - lo:int(np.ceil(r.end)) - lo] = True
            grids[rule] = grid
        yield date, lo, grids


def turn_gaps(occ, rule):
    """Idle time on a table between one stay ending and the next starting, same night."""
    rows = occ if rule == "new" else occ[occ.is_recorded_table]
    out = []
    for (date, table), g in rows.sort_values("start").groupby(["service_date", "table_code"]):
        end_so_far = -np.inf
        for r in g.itertuples():
            if np.isfinite(end_so_far) and r.start > end_so_far:
                out.append((date, table, end_so_far, r.start - end_so_far))
            end_so_far = max(end_so_far, r.end)
    return pd.DataFrame(out, columns=["service_date", "table_code", "gap_start", "gap"])


def main():
    occ = query("""
        SELECT o.order_id, o.service_date, o.table_code, o.is_recorded_table, o.start_at, o.end_at,
               f.amount
        FROM analytics.fact_table_occupancy o JOIN analytics.fact_order f USING (order_id)""")
    floor = query("""SELECT table_code, valid_from, valid_to FROM staging.floor_plan_tables
                     WHERE section IN ('Black Duck', 'Evangeline', 'Open Lounge')""")
    for c in ("service_date", "start_at", "end_at"):
        occ[c] = pd.to_datetime(occ[c])
    floor["valid_from"] = pd.to_datetime(floor.valid_from)
    floor["valid_to"] = pd.to_datetime(floor.valid_to)
    occ = occ[occ.service_date.dt.day_name() != "Monday"].copy()
    occ["amount"] = occ.amount.astype(float)
    occ["start"] = (occ.start_at - occ.service_date).dt.total_seconds() / 60
    occ["end"] = (occ.end_at - occ.service_date).dt.total_seconds() / 60

    night_rows, slot_rows = [], []
    for date, lo, grids in nights(occ, floor):
        n_tables = grids["new"].shape[0]
        rec = {"service_date": date, "tables": n_tables, "open_minutes": grids["new"].shape[1]}
        for rule, grid in grids.items():
            rec[f"{rule}_table_minutes"] = grid.sum()
            for allowance in GAP_ALLOWANCES:
                filled = np.array([fill_short_gaps(r, allowance) for r in grid])
                rec[f"{rule}_full_min_{allowance}"] = filled.all(0).sum()
            # 15-minute slots on the clock, a table counted if in use at any point in the slot
            first = lo // 15
            for s in range(first, (lo + grid.shape[1] - 1) // 15 + 1):
                a, b = max(s * 15 - lo, 0), min((s + 1) * 15 - lo, grid.shape[1])
                slot_rows.append((date, rule, s, grid[:, a:b].any(1).sum(), n_tables))
        night_rows.append(rec)
    nt = pd.DataFrame(night_rows)
    nt["day"] = nt.service_date.dt.day_name()
    slots = pd.DataFrame(slot_rows, columns=["service_date", "rule", "slot", "in_use", "tables"])
    slots["pct"] = 100 * slots.in_use / slots.tables
    slots["day"] = slots.service_date.dt.day_name()

    lines = []
    p = lines.append
    p("# How full the room gets\n")
    p(f"Reservation sections (Black Duck, Evangeline, Open Lounge), {len(nt)} trading nights "
      f"(Tue-Sun), {nt.service_date.min():%b %-d, %Y} to {nt.service_date.max():%b %-d, %Y}. "
      "**New** = a party occupies every table of the banquette or pair it sat at; **old** = only "
      "the table Toast rang it on (what earlier reports used).\n")

    p("## Tables in use, by 15-minute slot\n")
    p("A table counts if it was in use at any point in the slot. Slots from each night's first "
      "seating to its last payment.\n")
    p("| | Median slot | Fri/Sat median | Fri/Sat 8-10pm median | Slots with every table in use | Nights with such a slot |")
    p("|---|---|---|---|---|---|")
    for rule in ("old", "new"):
        s = slots[slots.rule == rule]
        fs = s[s.day.isin(["Friday", "Saturday"])]
        peak = fs[fs.slot.between(20 * 4, 22 * 4 - 1)]
        full = s[s.in_use == s.tables]
        p(f"| {rule} | {s.pct.median():.0f}% | {fs.pct.median():.0f}% | {peak.pct.median():.0f}% | "
          f"{len(full)} | {full.service_date.nunique()} |")

    p("\n## Utilization: share of table-time used while open\n")
    p("| Night | Nights | Old | New | Unused table-hours per night (new) |")
    p("|---|---|---|---|---|")
    for day in DAYS + ["All"]:
        d = nt if day == "All" else nt[nt.day == day]
        cap = (d.tables * d.open_minutes).sum()
        p(f"| {day} | {len(d)} | {100 * d.old_table_minutes.sum() / cap:.0f}% | "
          f"{100 * d.new_table_minutes.sum() / cap:.0f}% | "
          f"{(cap - d.new_table_minutes.sum()) / len(d) / 60:.0f} |")

    p("\n## Nights when every table was taken at the same moment\n")
    p("Counted by the minute. Toast can't say how long a table takes to clear and reset, so a "
      "short idle gap between two parties on a table can also be counted as taken (the table "
      "was not really sellable).\n")
    p("| Gap counted as taken | Nights fully booked | of Fri/Sat nights | Median minutes full (those nights) | Nights full 30+ min |")
    p("|---|---|---|---|---|")
    fs_nights = nt.day.isin(["Friday", "Saturday"])
    for allowance in GAP_ALLOWANCES:
        col = f"new_full_min_{allowance}"
        f = nt[nt[col] > 0]
        p(f"| {'none' if allowance == 0 else f'up to {allowance} min'} | {len(f)} | "
          f"{(fs_nights & (nt[col] > 0)).sum()} of {fs_nights.sum()} | "
          f"{f[col].median():.0f} | {(nt[col] >= 30).sum()} |")
    old_full = (nt.old_full_min_30 > 0).sum()
    p(f"\nUnder the old count no night is ever fully booked, even allowing 30-minute gaps "
      f"({old_full} nights).")
    byday = nt[nt.new_full_min_15 > 0].day.value_counts().reindex(DAYS).fillna(0).astype(int)
    p("\nFully booked nights (gaps up to 15 min), by night: "
      + ", ".join(f"{d} {n}" for d, n in byday.items()) + ".")

    # Turn gaps against how full the room was, and what faster turning is worth.
    slot_pct = slots.set_index(["rule", "service_date", "slot"]).pct
    years = ((nt.service_date.max() - nt.service_date.min()).days + 1) / 365.25
    p("\n## Turn gaps and what faster turning is worth\n")
    p("A turn gap is the idle time on a table between one stay ending (payment) and the next "
      "starting, within a night. Under the old count a table borrowed by a combined party looked "
      "idle, so its gaps ran straight through people sitting at it. Room fullness is the slot "
      "the gap began in.\n")
    p("| Room full when gap began | Old: gaps | Old: median min | New: gaps | New: median min |")
    p("|---|---|---|---|---|")
    bands = [-1, 25, 50, 75, 100]
    labels = ["under 1/4", "1/4-1/2", "1/2-3/4", "over 3/4"]
    gaps, value = {}, {}
    for rule in ("old", "new"):
        g = turn_gaps(occ, rule)
        g["slot"] = (g.gap_start // 15).astype(int)
        g["room"] = [slot_pct.get((rule, d, s), 0) for d, s in zip(g.service_date, g.slot)]
        g["band"] = pd.cut(g.room, bands, labels=labels)
        gaps[rule] = g
        rows = occ if rule == "new" else occ[occ.is_recorded_table]
        # revenue per table per 15 min: a combined party's spend is spread over all its tables
        rate = occ.drop_duplicates("order_id").amount.sum() / ((rows.end - rows.start).sum() / 15)
        achievable = g.loc[g.room > 75, "gap"].median()
        evening = g[g.gap_start.between(17 * 60, 23 * 60)]
        excess = (evening.loc[evening.room > 75, "gap"] - achievable).clip(lower=0)
        real = excess.sum() / 15 * rate
        days = evening.loc[excess.index, "service_date"].dt.day_name()
        fri_sat = 100 * excess[days.isin(["Friday", "Saturday"])].sum() / excess.sum()
        naive = (evening.gap - 15).clip(lower=0).sum() / 15 * rate
        idle = (nt.tables * nt.open_minutes).sum() - nt[f"{rule}_table_minutes"].sum()
        value[rule] = (achievable, real / years, naive / years, rate, 100 * g.gap.sum() / idle, fri_sat)
    for band in labels:
        o, n = (gaps[r][gaps[r].band == band].gap for r in ("old", "new"))
        p(f"| {band} | {len(o)} | {o.median():.0f} | {len(n)} | {n.median():.0f} |")
    p("\n| | Old | New |")
    p("|---|---|---|")
    p(f"| Gap achieved when the room is over 3/4 full (median) | {value['old'][0]:.0f} min | {value['new'][0]:.0f} min |")
    p(f"| Revenue per table per 15 min | ${value['old'][3]:.2f} | ${value['new'][3]:.2f} |")
    p(f"| **Value of turning busy-room tables (5-11pm) as fast as that, per year** | "
      f"${value['old'][1]:,.0f} | **${value['new'][1]:,.0f}** |")
    p(f"| Naive: every evening gap over 15 min sells, per year | ${value['old'][2]:,.0f} | ${value['new'][2]:,.0f} |")
    p(f"| Turn gaps as a share of unused table-time while open | {value['old'][4]:.0f}% | {value['new'][4]:.0f}% |")
    p(f"| Share of that value on Fri/Sat | {value['old'][5]:.0f}% | {value['new'][5]:.0f}% |")
    p(f"\nPer-year figures divide the {years:.2f} years in the data.")

    text = "\n".join(lines) + "\n"
    print(text)
    (RESULTS / "occupancy.md").write_text(text)


if __name__ == "__main__":
    main()
