"""Is trade declining, or was the Jan-Jul 2026 drop just the season?

    python3 analysis/trend.py          # prints the report and writes analysis/results/trend.md

The old analysis couldn't tell: over Jan-Jul, elapsed time and temperature moved together
(r = 0.90). With Apr 2025 - Sep 2026 loaded, May-Sep appear in both years, so the same months
can be compared directly and a trend can be separated from the time of year.

Nights: regular trading nights only (Tuesday-Sunday with at least one order). Mondays are
closed to the public; the odd Monday order is a private booking, reported separately.
Event/catering revenue is lumpy (a single $2K booking moves a night), so the trend is shown
for regular revenue (seated + to-go) as well as in total.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.db import RESULTS, nightly  # noqa: E402

# Until about Jun 5, 2025 drinks were rung tax-inclusive ($17.49 for a $19 drink), so the
# same sale counted ~8% less net revenue. Nights before this are re-run as a sensitivity check.
TAX_INCLUSIVE_UNTIL = pd.Timestamp("2025-06-05")


def money(x):
    return f"${x:,.0f}"


def pct(x):
    return f"{x:+.1%}"


def main():
    n = nightly()
    mondays = n[(n.iso_day_of_week == 1) & (n.orders > 0)]
    n = n[(n.iso_day_of_week != 1) & (n.orders > 0)].copy()
    n["regular_revenue"] = n["seated_revenue"] + n["togo_revenue"]
    n["years"] = (n["service_date"] - n["service_date"].min()).dt.days / 365.25
    n["month_of_year"] = n["service_date"].dt.month
    n["dow"] = n["day_name"]
    n["spend_per_guest"] = n["seated_revenue"] / n["guests"].where(n["guests"] > 0)

    out = []
    p = out.append
    p("# Trend vs. season\n")
    p(f"Regular trading nights (Tue-Sun): **{len(n)}**, "
      f"{n.service_date.min():%b %-d, %Y} to {n.service_date.max():%b %-d, %Y}. "
      f"Monday private bookings: {len(mondays)} nights, {money(mondays.revenue.sum())} "
      f"(left out below).\n")

    # 1. Month by month -------------------------------------------------------------------
    m = (n.groupby("month_start")
           .agg(nights=("service_date", "size"), revenue=("revenue", "sum"),
                regular=("regular_revenue", "sum"), parties=("parties", "sum"),
                guests=("guests", "sum"), seated=("seated_revenue", "sum"),
                temp=("Temp_High_F", "mean")))
    m["rev_per_night"] = m.revenue / m.nights
    m["regular_per_night"] = m.regular / m.nights
    m["parties_per_night"] = m.parties / m.nights
    m["spend_per_guest"] = m.seated / m.guests
    p("## Month by month (per regular night)\n")
    p("| Month | Nights | Revenue | Regular revenue | Parties | Spend/guest | Avg high °F |")
    p("|---|---|---|---|---|---|---|")
    for ms, r in m.iterrows():
        p(f"| {ms:%b %Y} | {int(r.nights)} | {money(r.rev_per_night)} | {money(r.regular_per_night)} | "
          f"{r.parties_per_night:.1f} | ${r.spend_per_guest:.2f} | {r.temp:.0f} |")
    p("")

    # 2. Same months, year over year ------------------------------------------------------
    # months traded in both years, with at least 15 nights in each (Apr 2025 is opening week)
    nights_by = n.groupby(["month_of_year", "year"]).size()
    both = [mo for mo in range(1, 13)
            if nights_by.get((mo, 2025), 0) >= 15 and nights_by.get((mo, 2026), 0) >= 15]
    yoy_rows = []
    for mo in both:
        a = n[(n.month_of_year == mo) & (n.year == 2025)]
        b = n[(n.month_of_year == mo) & (n.year == 2026)]
        yoy_rows.append(dict(
            month=pd.Timestamp(2026, mo, 1).strftime("%b"), nights=(len(a), len(b)),
            regular=(a.regular_revenue.mean(), b.regular_revenue.mean()),
            parties=(a.parties.mean(), b.parties.mean()),
            spg=(a.seated_revenue.sum() / a.guests.sum(), b.seated_revenue.sum() / b.guests.sum()),
            frisat=(a[a.is_fri_or_sat].regular_revenue.mean(), b[b.is_fri_or_sat].regular_revenue.mean()),
            midweek=(a[~a.is_fri_or_sat].regular_revenue.mean(), b[~b.is_fri_or_sat].regular_revenue.mean())))
    p("## Same month, 2025 vs 2026 (regular revenue per night)\n")
    p("| Month | Nights | Regular revenue | Change | Fri/Sat | Tue-Thu & Sun | Parties/night | Spend/guest |")
    p("|---|---|---|---|---|---|---|---|")
    for r in yoy_rows:
        p(f"| {r['month']} | {r['nights'][0]} → {r['nights'][1]} | "
          f"{money(r['regular'][0])} → {money(r['regular'][1])} | {pct(r['regular'][1] / r['regular'][0] - 1)} | "
          f"{pct(r['frisat'][1] / r['frisat'][0] - 1)} | {pct(r['midweek'][1] / r['midweek'][0] - 1)} | "
          f"{r['parties'][0]:.1f} → {r['parties'][1]:.1f} | ${r['spg'][0]:.2f} → ${r['spg'][1]:.2f} |")
    pooled_a = n[n.month_of_year.isin(both) & (n.year == 2025)]
    pooled_b = n[n.month_of_year.isin(both) & (n.year == 2026)]
    p("")
    p(f"Across those months together: regular revenue per night "
      f"{money(pooled_a.regular_revenue.mean())} → {money(pooled_b.regular_revenue.mean())} "
      f"({pct(pooled_b.regular_revenue.mean() / pooled_a.regular_revenue.mean() - 1)}); parties per night "
      f"{pooled_a.parties.mean():.1f} → {pooled_b.parties.mean():.1f} "
      f"({pct(pooled_b.parties.mean() / pooled_a.parties.mean() - 1)}); spend per guest "
      f"${pooled_a.seated_revenue.sum() / pooled_a.guests.sum():.2f} → "
      f"${pooled_b.seated_revenue.sum() / pooled_b.guests.sum():.2f}.\n")

    # 3. Models: trend net of day of week and time of year --------------------------------
    p("## Trend after allowing for day of week and season\n")
    p("Log of nightly revenue, so the trend reads as % per year. Season is either the calendar "
      "month or the day's high temperature (with a curve). 95% intervals use errors robust to "
      "uneven variance.\n")
    p("| Revenue | Season as | Nights | Trend per year | 95% interval |")
    p("|---|---|---|---|---|")
    fits = {}
    for label, data in (("all nights", n),
                        (f"from {TAX_INCLUSIVE_UNTIL:%b %-d, %Y}", n[n.service_date >= TAX_INCLUSIVE_UNTIL])):
        for col, col_label in (("regular_revenue", "regular"), ("revenue", "total")):
            for season, formula in (("month", "C(month_of_year)"),
                                    ("temperature", "Temp_High_F + I(Temp_High_F**2)")):
                d = data[data[col] > 0]
                fit = smf.ols(f"np.log({col}) ~ C(dow) + {formula} + years", data=d).fit(cov_type="HC1")
                lo, hi = fit.conf_int().loc["years"]
                b = fit.params["years"]
                fits[(label, col_label, season)] = (b, lo, hi)
                p(f"| {col_label}, {label} | {season} | {len(d)} | {pct(np.exp(b) - 1)} | "
                  f"{pct(np.exp(lo) - 1)} to {pct(np.exp(hi) - 1)} |")
    r_tt = np.corrcoef(n.years, n.Temp_High_F)[0, 1]
    p("")
    p(f"Elapsed time vs. daily high temperature over this window: r = {r_tt:.2f} "
      f"(was 0.90 over Jan-Jul 2026), so the two can now be told apart.\n")

    # 4. Footfall vs spend ------------------------------------------------------------------
    p("## Fewer people, or less spend per person?\n")
    for col, label in (("parties", "parties per night"), ("spend_per_guest", "seated spend per guest")):
        d = n[n[col] > 0]
        fit = smf.ols(f"np.log({col}) ~ C(dow) + C(month_of_year) + years", data=d).fit(cov_type="HC1")
        lo, hi = fit.conf_int().loc["years"]
        p(f"- **{label.capitalize()}:** {pct(np.exp(fit.params['years']) - 1)} per year "
          f"(95%: {pct(np.exp(lo) - 1)} to {pct(np.exp(hi) - 1)}).")
    p("")

    text = "\n".join(out)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "trend.md").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
