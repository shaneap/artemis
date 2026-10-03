"""Tests for the analytics layer (sql/007_analytics.sql). Run:  python3 -m unittest tests.test_analytics -v

Same scratch-database setup as the other tests (needs a running PostgreSQL).
"""
import datetime as dt
import unittest
from decimal import Decimal

import load_raw
from tests.test_raw_load import HEADER_C, HEADER_ITEM_B, REAL_EXPORTS, ScratchDB
from tests.test_staging import FileLoading, order_row

_next_id = iter(range(1300000000000100000, 1300000000000999999))


def sale(menu_item, sent, price, qty="1.0", void="false", order_id="1300000000000000001"):
    """One ItemSelectionDetails row (17-column layout) with a fresh Item Selection Id."""
    return (f"{order_id},5,{sent},{sent},1300000000000000002,O3,Lounge,{next(_next_id)},"
            f"{menu_item},Cocktails,Cocktails,Liquor,{price},0.00,{price},{qty},{void}")


class PriceVersions(FileLoading):
    def versions(self, menu_item):
        return self.conn.execute(
            "SELECT list_price, valid_from, valid_to FROM analytics.dim_menu_item "
            "WHERE menu_item = %s ORDER BY valid_from", (menu_item,)).fetchall()

    def test_a_dominant_monthly_price_change_starts_a_new_version(self):
        rows = ([sale("Gin", f"1/{d}/26 7:00 PM", "17.49") for d in (5, 6, 7, 8)]
                + [sale("Gin", f"2/{d}/26 7:00 PM", "19.00") for d in (10, 11, 12, 13)]
                + [sale("Gin", f"3/{d}/26 7:00 PM", "19.00") for d in (2, 3, 4)]
                + [sale("Gin", "3/5/26 7:00 PM", "38.00")])           # a double: not a new price
        self.load("items.csv", HEADER_ITEM_B, *rows)
        self.assertEqual(self.versions("Gin"), [
            (Decimal("17.49"), dt.date(2026, 1, 5), dt.date(2026, 2, 10)),
            (Decimal("19.00"), dt.date(2026, 2, 10), None)])

    def test_mixed_months_and_odd_rows_do_not_move_the_price(self):
        rows = ([sale("Rye", f"1/{d}/26 7:00 PM", "16.00") for d in (5, 6, 7)]
                # February: no price is more than half -> no change
                + [sale("Rye", f"2/{d}/26 7:00 PM", p) for d, p in ((2, "20.00"), (3, "20.00"),
                                                                    (4, "16.00"), (5, "16.00"))]
                # March: qty 2 and voids don't count
                + [sale("Rye", f"3/{d}/26 7:00 PM", "32.00", qty="2.0") for d in (2, 3, 4)]
                + [sale("Rye", f"3/{d}/26 7:00 PM", "25.00", void="true") for d in (5, 6, 7)])
        self.load("items.csv", HEADER_ITEM_B, *rows)
        self.assertEqual(self.versions("Rye"), [(Decimal("16.00"), dt.date(2026, 1, 5), None)])

    def test_low_sellers_use_their_overall_price_and_open_price_items_have_none(self):
        rows = ([sale("Rare Scotch", "1/5/26 7:00 PM", "40.00"),
                 sale("Rare Scotch", "4/5/26 7:00 PM", "40.00")]
                + [sale("Locker", f"1/{d}/26 7:00 PM", p) for d, p in ((5, "113.00"), (6, "236.00"),
                                                                      (7, "158.00"))])
        self.load("items.csv", HEADER_ITEM_B, *rows)
        self.assertEqual(self.versions("Rare Scotch"), [(Decimal("40.00"), dt.date(2026, 1, 5), None)])
        self.assertEqual(self.versions("Locker"), [(None, dt.date(2026, 1, 5), None)])

    def test_each_sale_points_at_the_version_in_force_that_day(self):
        rows = ([sale("Gin", f"1/{d}/26 7:00 PM", "17.49") for d in (5, 6, 7)]
                + [sale("Gin", f"2/{d}/26 7:00 PM", "19.00") for d in (10, 11, 12)])
        self.load("items.csv", HEADER_ITEM_B, *rows)
        got = self.conn.execute(
            "SELECT f.sent_at::date, m.list_price FROM analytics.fact_item_selection f "
            "JOIN analytics.dim_menu_item m USING (menu_item_key) ORDER BY 1").fetchall()
        self.assertEqual([p for _, p in got], [Decimal("17.49")] * 3 + [Decimal("19.00")] * 3)


class OrderFacts(FileLoading):
    def fact(self, order_id):
        cur = self.conn.execute("SELECT * FROM analytics.fact_order WHERE order_id = %s", (order_id,))
        return dict(zip([d.name for d in cur.description], cur.fetchone()))

    def test_order_type_rule(self):
        self.load("orders.csv", HEADER_C,
                  order_row(order_id="1300000000000000501", table="O3", amount="900.00"),
                  order_row(order_id="1300000000000000502", table="", amount="400.00"),
                  order_row(order_id="1300000000000000503", table="", amount="399.99"))
        self.assertEqual([self.fact(1300000000000000500 + n)["order_type"] for n in (1, 2, 3)],
                         ["Seated", "Event-Catering", "To-Go"])

    def test_vpcpm_tpcpm_and_when_they_are_left_out(self):
        self.load("orders.csv", HEADER_C,
                  order_row(order_id="1300000000000000601", guests="2", amount="100.00", duration="1:00:00"),
                  order_row(order_id="1300000000000000602", duration="0:10:00"),        # under 15 min
                  order_row(order_id="1300000000000000603", duration="7:00:00"),        # over 6 h
                  order_row(order_id="1300000000000000604", guests="0"),
                  order_row(order_id="1300000000000000605", table=""))                  # not seated
        f = self.fact(1300000000000000601)
        self.assertEqual((f["vpcpm"], f["tpcpm"], f["in_time_metrics"]),
                         (Decimal("12.5000"), Decimal("25.0000"), True))   # $50 a head over 4 x 15 min
        for n in (2, 3, 4, 5):
            f = self.fact(1300000000000000600 + n)
            self.assertEqual((f["vpcpm"], f["tpcpm"], f["in_time_metrics"]), (None, None, False), n)


@unittest.skipUnless(REAL_EXPORTS, "no exports in data/exports/")
class AnalyticsOnRealExports(ScratchDB):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_raw.load_all(cls.conn)
        load_raw.refresh_models(cls.conn)

    def setUp(self):
        pass

    def scalar(self, query):
        return self.conn.execute(query).fetchone()[0]

    def test_facts_keep_every_staged_row_and_every_dollar(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM analytics.fact_order"),
                         self.scalar("SELECT count(*) FROM staging.orders"))
        self.assertEqual(self.scalar("SELECT count(*) FROM analytics.fact_item_selection"),
                         self.scalar("SELECT count(*) FROM staging.item_selections"))
        self.assertEqual(self.scalar("SELECT sum(amount) FROM analytics.fact_order"),
                         self.scalar("SELECT sum(amount) FROM staging.orders"))

    def test_price_versions_are_contiguous_and_cover_every_sale(self):
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM (SELECT valid_to, lead(valid_from) OVER "
            "(PARTITION BY menu_item ORDER BY valid_from) AS next_from FROM analytics.dim_menu_item) x "
            "WHERE valid_to IS DISTINCT FROM next_from"), 0)
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM analytics.fact_item_selection WHERE menu_item_key IS NULL"), 0)

    def test_every_service_day_is_in_the_date_dimension(self):
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM analytics.fact_order f LEFT JOIN analytics.dim_date d USING (date_key) "
            "WHERE d.date_key IS NULL"), 0)

    def test_tabled_reservation_orders_all_have_a_seating_unit(self):
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM analytics.fact_order WHERE table_code IS NOT NULL "
            "AND section <> 'Bar' AND seating_unit_key IS NULL"), 0)


if __name__ == "__main__":
    unittest.main()
