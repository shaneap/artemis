"""Menu mix: what sells, how it's changed, and why spend per guest went up.

    python3 analysis/menu.py           # prints the report and writes analysis/results/menu.md

Item net sales (Net Price, which sums to the order's Amount) on non-void selections. Units
are Qty. "Per guest" uses seated orders with a believable guest count. The latest full year
is Oct 1, 2025 - Sep 29, 2026; year-over-year compares the months traded in both years
(May-Sep), as in trend.py.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.db import RESULTS, query  # noqa: E402

YEAR_START, YEAR_END = pd.Timestamp("2025-10-01"), pd.Timestamp("2026-09-29")
YOY_MONTHS = [5, 6, 7, 8, 9]


def main():
    items = query("""
        SELECT f.item_selection_id, f.order_id, d.service_date, f.qty, f.net_price, f.gross_price,
               m.menu_item, m.menu_group, m.menu, COALESCE(m.sales_category, '(none)') AS sales_category,
               m.list_price, m.menu_item_key, o.order_type, o.guests, o.guests_implausible
        FROM analytics.fact_item_selection f
        JOIN analytics.dim_menu_item m USING (menu_item_key)
        JOIN analytics.dim_date d USING (date_key)
        LEFT JOIN analytics.fact_order o USING (order_id)
        WHERE NOT f.is_void""")
    items["service_date"] = pd.to_datetime(items.service_date)
    for c in ("qty", "net_price", "gross_price"):
        items[c] = items[c].astype(float)
    items["year_of_sale"] = items.service_date.dt.year
    items["month"] = items.service_date.dt.month

    seated = query("""
        SELECT f.order_id, d.service_date, f.guests, f.amount
        FROM analytics.fact_order f JOIN analytics.dim_date d USING (date_key)
        WHERE f.order_type = 'Seated' AND f.amount > 0 AND NOT f.guests_implausible AND f.guests > 0""")
    seated["service_date"] = pd.to_datetime(seated.service_date)
    seated["amount"] = seated.amount.astype(float)

    out = []
    p = out.append
    year = items[items.service_date.between(YEAR_START, YEAR_END)]
    total = year.net_price.sum()
    p("# Menu mix\n")
    p(f"Latest full year ({YEAR_START:%b %-d, %Y} - {YEAR_END:%b %-d, %Y}): "
      f"${total:,.0f} item net sales, {year.qty.sum():,.0f} units, "
      f"{year.menu_item.nunique():,} distinct items sold.\n")

    # 1. Categories -------------------------------------------------------------------------
    p("## Sales category\n")
    cat = year.groupby("sales_category").agg(net=("net_price", "sum"), units=("qty", "sum"))
    cat = cat.sort_values("net", ascending=False)
    p("| Category | Net sales | Share | Units | Avg per unit |")
    p("|---|---|---|---|---|")
    for c, r in cat.iterrows():
        p(f"| {c} | ${r.net:,.0f} | {r.net / total:.1%} | {r.units:,.0f} | ${r.net / r.units:,.2f} |")
    p("")
    none = year[year.sales_category == "(none)"]
    if len(none):
        top_none = none.groupby("menu_item").net_price.sum().sort_values(ascending=False).head(6)
        p("Items with no sales category, biggest first: " +
          ", ".join(f"{k} (${v:,.0f})" for k, v in top_none.items()) + ".\n")

    # 2. Top items ----------------------------------------------------------------------------
    p("## Top 20 items by net sales\n")
    top = (year.groupby(["menu_item", "sales_category"])
               .agg(net=("net_price", "sum"), units=("qty", "sum"))
               .sort_values("net", ascending=False).head(20))
    p("| Item | Category | Net sales | Share | Units | Avg per unit |")
    p("|---|---|---|---|---|---|")
    for (item, c), r in top.iterrows():
        p(f"| {item} | {c} | ${r.net:,.0f} | {r.net / total:.1%} | {r.units:,.0f} | ${r.net / r.units:,.2f} |")
    share20 = top.net.sum() / total
    p(f"\nThe top 20 items are {share20:.0%} of item sales.\n")

    # 3. Why did spend per guest rise? ---------------------------------------------------------
    p("## Why spend per guest went up (same months, 2025 vs 2026)\n")
    s_items = items[items.order_type.eq("Seated") & ~items.guests_implausible.fillna(True)
                    & items.guests.gt(0) & items.month.isin(YOY_MONTHS)]
    s_orders = seated[seated.service_date.dt.month.isin(YOY_MONTHS)]
    rows = []
    for y in (2025, 2026):
        it = s_items[s_items.year_of_sale == y]
        od = s_orders[s_orders.service_date.dt.year == y]
        guests = od.guests.sum()
        rows.append(dict(year=y, guests=guests, spend=od.amount.sum() / guests,
                         units=it.qty.sum() / guests, per_unit=it.net_price.sum() / it.qty.sum(),
                         drinks=it[it.sales_category.isin(["Liquor", "Glass Wine", "Draft Beer",
                                                           "Bottle Wine", "NA Beverage"])].qty.sum() / guests,
                         food=it[it.sales_category == "Food"].qty.sum() / guests))
    a, b = rows
    p("| | May-Sep 2025 | May-Sep 2026 | Change |")
    p("|---|---|---|---|")
    p(f"| Seated guests | {a['guests']:,} | {b['guests']:,} | {b['guests'] / a['guests'] - 1:+.1%} |")
    p(f"| Spend per guest | ${a['spend']:.2f} | ${b['spend']:.2f} | {b['spend'] / a['spend'] - 1:+.1%} |")
    p(f"| Items per guest | {a['units']:.2f} | {b['units']:.2f} | {b['units'] / a['units'] - 1:+.1%} |")
    p(f"| — drinks per guest | {a['drinks']:.2f} | {b['drinks']:.2f} | {b['drinks'] / a['drinks'] - 1:+.1%} |")
    p(f"| — food items per guest | {a['food']:.2f} | {b['food']:.2f} | {b['food'] / a['food'] - 1:+.1%} |")
    p(f"| Net price per item | ${a['per_unit']:.2f} | ${b['per_unit']:.2f} | {b['per_unit'] / a['per_unit'] - 1:+.1%} |")
    p("")

    # like-for-like price change: same items sold in both periods, weighted by 2025 units
    base = s_items[s_items.year_of_sale == 2025].groupby("menu_item").agg(u=("qty", "sum"), n=("net_price", "sum"))
    new = s_items[s_items.year_of_sale == 2026].groupby("menu_item").agg(u=("qty", "sum"), n=("net_price", "sum"))
    common = base.join(new, lsuffix="_25", rsuffix="_26", how="inner")
    common = common[(common.u_25 >= 20) & (common.u_26 >= 20)]
    p25 = common.n_25 / common.u_25
    p26 = common.n_26 / common.u_26
    like_for_like = (p26 * common.u_25).sum() / (p25 * common.u_25).sum() - 1
    p(f"Like-for-like, the {len(common)} items that sold at least 20 units in both summers "
      f"({common.n_25.sum() / s_items[s_items.year_of_sale == 2025].net_price.sum():.0%} of 2025 sales) "
      f"cost **{like_for_like:+.1%}** more per unit in 2026 (weighted by what sold in 2025). "
      f"Part of the 2025 figure is the tax-inclusive pricing before Jun 5, 2025.\n")

    # 4. Price changes -----------------------------------------------------------------------
    p("## Menu price changes\n")
    versions = query("""
        SELECT menu_item, list_price, valid_from, valid_to,
               lag(list_price) OVER (PARTITION BY menu_item ORDER BY valid_from) AS prev_price
        FROM analytics.dim_menu_item""")
    ch = versions.dropna(subset=["prev_price", "list_price"]).copy()
    ch["list_price"] = ch.list_price.astype(float)
    ch["prev_price"] = ch.prev_price.astype(float)
    ch["change"] = ch.list_price / ch.prev_price - 1
    ch["valid_from"] = pd.to_datetime(ch.valid_from)
    units = items.groupby("menu_item").qty.sum()
    ch["units_all_time"] = ch.menu_item.map(units)
    big = ch[ch.units_all_time >= 200].sort_values("units_all_time", ascending=False)
    p(f"{len(ch)} price changes across {ch.menu_item.nunique()} items "
      f"({(ch.change > 0).sum()} up, {(ch.change < 0).sum()} down). "
      f"Changes on items that sold at least 200 units, biggest sellers first:\n")
    p("| Item | From | To | Change | Date | Units sold (all time) |")
    p("|---|---|---|---|---|---|")
    for _, r in big.head(25).iterrows():
        p(f"| {r.menu_item} | ${r.prev_price:.2f} | ${r.list_price:.2f} | {r.change:+.0%} | "
          f"{r.valid_from:%b %-d, %Y} | {r.units_all_time:,.0f} |")
    on_tax = ch[(ch.valid_from <= pd.Timestamp("2025-06-15")) &
                (np.isclose(ch.prev_price * 1.08625, ch.list_price, atol=0.02))]
    p(f"\n{len(on_tax)} of the changes are exactly the move from tax-inclusive to tax-added pricing "
      f"in early June 2025 (old price × 1.08625 = new price).\n")

    text = "\n".join(out)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "menu.md").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
