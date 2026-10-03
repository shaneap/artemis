"""What does each hour of the night earn? (opening-hours question)

    python3 analysis/hours.py          # prints the report and writes analysis/results/hours.md

Seated trade only (tables and bar). A party's spend is spread evenly over the minutes it sat
(opened -> paid), so a $300 table from 9:30 to 11:30 puts $75 in 9-10pm, $150 in 10-11pm and
$75 in 11pm-midnight; a seated order without a usable duration (over 6 hours) counts in the
hour it opened. Untabled orders are left out: event/catering and to-go checks are mostly rung
in the morning (deposits, pickups), so the hour they're rung says nothing about opening hours;
their totals are reported separately. Hours are clock hours on the service night (12-1am belongs to the night
before). Mondays are left out (closed; private bookings only).

Main window: the latest full year, Oct 1, 2025 - Sep 29, 2026 (one of each season, current
prices). The first summer is shown for comparison in the marginal-hours table.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.db import RESULTS, query  # noqa: E402

YEAR_START, YEAR_END = pd.Timestamp("2025-10-01"), pd.Timestamp("2026-09-29")
HOURS = range(11, 28)          # 11am .. 3am (hour 24 = midnight-1am)
DAYS = ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def label(h):
    h12 = h % 12 or 12
    return f"{h12}{'am' if h % 24 < 12 else 'pm'}"


def hour_span(h):
    return f"{label(h)}-{label(h + 1)}"


def revenue_by_hour(orders):
    """Rows: orders. Returns an orders x hours matrix of revenue."""
    start = ((orders.opened_at - orders.service_date).dt.total_seconds() / 60).to_numpy()
    spread = orders.duration_usable.to_numpy() & (orders.duration_minutes > 0).to_numpy()
    dur = np.where(spread, orders.duration_minutes.astype(float).to_numpy(), 0.0)
    end = start + dur
    amount = orders.amount.astype(float).to_numpy()
    cols = {}
    for h in HOURS:
        lo, hi = h * 60, (h + 1) * 60
        overlap = np.clip(np.minimum(end, hi) - np.maximum(start, lo), 0, None)
        share = np.where(spread, overlap / np.where(dur > 0, dur, 1),
                         ((start >= lo) & (start < hi)).astype(float))
        cols[h] = amount * share
    return pd.DataFrame(cols, index=orders.index)


def main():
    o = query("""
        SELECT f.order_id, d.service_date, d.day_name, f.opened_at, f.amount, f.order_type,
               f.duration_minutes, f.duration_usable
        FROM analytics.fact_order f JOIN analytics.dim_date d USING (date_key)
        WHERE d.iso_day_of_week <> 1""")
    o["service_date"] = pd.to_datetime(o.service_date)
    o["opened_at"] = pd.to_datetime(o.opened_at)
    o["duration_minutes"] = o.duration_minutes.astype(float)
    o["duration_usable"] = o.duration_usable.fillna(False).astype(bool)
    untabled = o[o.order_type != "Seated"]
    o = o[o.order_type == "Seated"].copy()
    by_hour = revenue_by_hour(o)
    unplaced = o.amount.astype(float).sum() - by_hour.to_numpy().sum()

    nights = o.groupby("service_date").day_name.first()

    def per_night(window):
        mask = o.service_date.between(*window)
        totals = by_hour[mask].groupby(o.loc[mask, "service_date"]).sum()
        totals = totals.reindex(nights[nights.index.to_series().between(*window)].index, fill_value=0)
        return totals.groupby(nights.reindex(totals.index)).mean().reindex(DAYS)

    year = per_night((YEAR_START, YEAR_END))
    first_summer = per_night((pd.Timestamp("2025-06-05"), pd.Timestamp("2025-09-30")))
    last_summer = per_night((pd.Timestamp("2026-06-05"), pd.Timestamp("2026-09-29")))

    out = []
    p = out.append
    p("# Revenue by hour of the night\n")
    in_year = untabled.service_date.between(YEAR_START, YEAR_END)
    p(f"Average seated revenue per night in each hour, {YEAR_START:%b %-d, %Y} - {YEAR_END:%b %-d, %Y} "
      f"(Tue-Sun). Seated revenue outside 11am-4am: ${unplaced:,.0f}. Not included: "
      f"event/catering ${untabled[in_year & (untabled.order_type == 'Event-Catering')].amount.astype(float).sum():,.0f} "
      f"and to-go ${untabled[in_year & (untabled.order_type == 'To-Go')].amount.astype(float).sum():,.0f} "
      f"over the same 12 months.\n")
    shown = [h for h in HOURS if year[h].max() >= 25]
    p("| Night | " + " | ".join(hour_span(h) for h in shown) + " | Whole night |")
    p("|---|" + "---|" * (len(shown) + 1))
    for day, r in year.iterrows():
        p(f"| {day} | " + " | ".join(f"${r[h]:,.0f}" for h in shown) + f" | ${r.sum():,.0f} |")
    p("")

    p("## The hours at the edges\n")
    p("What the first and last hours earn on an average night. The old report (Jan-Jul 2026) "
      "suggested opening at 5pm Tue-Thu and closing at midnight Tue/Wed/Sun. Summers compared "
      "Jun 5 - Sep 30 each year.\n")
    edges = [16, 17, 23, 24]
    p("| Night | " + " | ".join(f"{hour_span(h)} (last 12 mo / summer 25 / summer 26)" for h in edges) + " |")
    p("|---|" + "---|" * len(edges))
    for day in DAYS:
        p(f"| {day} | " + " | ".join(
            f"${year.loc[day, h]:,.0f} / ${first_summer.loc[day, h]:,.0f} / ${last_summer.loc[day, h]:,.0f}"
            for h in edges) + " |")
    p("")

    # share of the night's revenue in the edge hours, last 12 months
    p("Share of the night's seated revenue earned before 5pm and after midnight (last 12 months):\n")
    for day in DAYS:
        tot = year.loc[day].sum()
        early = year.loc[day, [h for h in HOURS if h < 17]].sum()
        late = year.loc[day, [h for h in HOURS if h >= 24]].sum()
        p(f"- **{day}:** before 5pm {early / tot:.0%} (${early:,.0f}), after midnight "
          f"{late / tot:.0%} (${late:,.0f}) of ${tot:,.0f}")
    p("")

    text = "\n".join(out)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "hours.md").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
