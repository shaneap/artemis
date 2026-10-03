"""Tests for the staging views (sql/005_staging.sql). Run:  python3 -m unittest tests.test_staging -v

Uses the same scratch-database setup as test_raw_load (needs a running PostgreSQL).
"""
import datetime as dt
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import load_raw
from tests.test_raw_load import HEADER_C, HEADER_ITEM, HEADER_ITEM_B, REAL_EXPORTS, ScratchDB


def order_row(order_id="1300000000000000001", opened="1/2/26 7:00 PM", table="O3", guests="2",
              amount="100.00", duration="1:00:00", closed="1/3/26 4:18 AM", checks="1"):
    return (f'{order_id},5,"{checks}",{opened},{guests},{table},0.00,{amount},8.00,20.00,0.00,'
            f'{Decimal(amount) + 28:.2f},{closed},{duration}')


def item_row(item_id, order_id="1300000000000000001", net="50.00", void="false", qty="1.0",
             with_service=False):
    service = "," if with_service else ""
    return (f"{order_id},5,1/2/26 7:05 PM,1/2/26 7:00 PM,1300000000000000002,O3,Lounge,"
            f"{service}{item_id},Burger,Plates,Food Menu,Food,{net},0.00,{net},{qty},{void}")


class FileLoading(ScratchDB):
    """Writes small synthetic exports into a temp dir and loads them."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def load(self, name, header, *rows):
        path = self.tmp / name
        path.write_text(header + "\r\n" + "\r\n".join(rows) + "\r\n")
        load_raw.load_file(self.conn, path)
        load_raw.refresh_models(self.conn)

    def order(self, order_id="1300000000000000001"):
        cur = self.conn.execute("SELECT * FROM staging.orders WHERE order_id = %s", (order_id,))
        names = [d.name for d in cur.description]
        row = cur.fetchone()
        return dict(zip(names, row)) if row else None


class StagingRules(FileLoading):

    def test_without_dated_file_names_the_newest_load_wins(self):
        self.load("old.csv", HEADER_C, order_row(amount="100.00"))
        self.load("new.csv", HEADER_C, order_row(amount="120.00"))
        o = self.order()
        self.assertEqual((o["amount"], o["source_file"], o["copies_in_raw"]),
                         (Decimal("120.00"), "new.csv", 2))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM staging.orders").fetchone()[0], 1)

    def test_export_with_the_later_date_range_wins_even_if_loaded_first(self):
        self.load("OrderDetails_2026_01_01-2026_03_01.csv", HEADER_C, order_row(amount="120.00"))
        self.load("OrderDetails_2025_10_24-2026_01_01.csv", HEADER_C, order_row(amount="100.00"))
        self.load("renamed.csv", HEADER_C, order_row(amount="90.00"))   # no date in name: ranks last
        o = self.order()
        self.assertEqual((o["amount"], o["copies_in_raw"]), (Decimal("120.00"), 3))

    def test_timestamps_and_the_4am_service_day(self):
        cases = {  # Opened -> (opened_at, service_date)
            "1/2/26 12:05 AM": (dt.datetime(2026, 1, 2, 0, 5), dt.date(2026, 1, 1)),
            "1/2/26 3:59 AM": (dt.datetime(2026, 1, 2, 3, 59), dt.date(2026, 1, 1)),
            "1/2/26 4:00 AM": (dt.datetime(2026, 1, 2, 4, 0), dt.date(2026, 1, 2)),
            "1/2/26 12:30 PM": (dt.datetime(2026, 1, 2, 12, 30), dt.date(2026, 1, 2)),
            "12/31/25 11:59 PM": (dt.datetime(2025, 12, 31, 23, 59), dt.date(2025, 12, 31)),
        }
        rows = [order_row(order_id=str(1300000000000000100 + n), opened=opened)
                for n, opened in enumerate(cases)]
        self.load("times.csv", HEADER_C, *rows)
        for n, (opened_at, service_date) in enumerate(cases.values()):
            o = self.order(1300000000000000100 + n)
            self.assertEqual((o["opened_at"], o["service_date"]), (opened_at, service_date))

    def test_duration_parsing_and_d009_flags(self):
        cases = {  # Duration text -> (minutes, long, negative, usable)
            "1:14:12": (Decimal("74.20"), False, False, True),
            "6:00:00": (Decimal("360.00"), False, False, True),     # "over 6 hours" is strict
            "6:00:01": (Decimal("360.02"), True, False, False),
            "147:09:50": (Decimal("8829.83"), True, False, False),
            "-378:-17:-58": (Decimal("-22697.97"), False, True, False),
            "": (None, None, None, False),
        }
        rows = [order_row(order_id=str(1300000000000000200 + n), duration=d)
                for n, d in enumerate(cases)]
        self.load("durations.csv", HEADER_C, *rows)
        for n, (text, expected) in enumerate(cases.items()):
            o = self.order(1300000000000000200 + n)
            got = (o["duration_minutes"], o["is_long_session"], o["is_negative_duration"],
                   o["duration_usable"])
            self.assertEqual(got, expected, repr(text))

    def test_blanks_become_null_and_check_lists_become_arrays(self):
        self.load("blanks.csv", HEADER_C, order_row(table="", closed="", checks="9, 16, 17"))
        o = self.order()
        self.assertEqual((o["table_code"], o["closed_at"], o["check_numbers"]),
                         (None, None, [9, 16, 17]))

    def test_items_from_both_layouts_newest_wins_and_void_is_boolean(self):
        self.load("items_a.csv", HEADER_ITEM, item_row("1300000000000000301", with_service=True),
                  item_row("1300000000000000302", net="10.00", with_service=True))
        self.load("items_b.csv", HEADER_ITEM_B, item_row("1300000000000000302", net="12.00"),
                  item_row("1300000000000000303", void="true", qty="0.5"))
        rows = self.conn.execute(
            "SELECT item_selection_id, net_price, is_void, qty, copies_in_raw "
            "FROM staging.item_selections ORDER BY 1").fetchall()
        self.assertEqual(rows, [
            (1300000000000000301, Decimal("50.00"), False, Decimal("1.00"), 1),
            (1300000000000000302, Decimal("12.00"), False, Decimal("1.00"), 2),
            (1300000000000000303, Decimal("50.00"), True, Decimal("0.50"), 1),
        ])


class SeatingRules(FileLoading):
    """Floor plan by date + the combined-table fix (sql/006_floor_plan.sql)."""

    def seat(self, opened, table, guests):
        order_id = 1300000000000000400 + len(self.placed)
        self.placed.append((order_id, opened, table, guests))
        return order_id

    def setUp(self):
        super().setUp()
        self.placed = []

    def run_cases(self, cases):
        ids = [self.seat(*case[:3]) for case in cases]
        rows = [order_row(order_id=str(i), opened=o, table=t, guests=str(g))
                for i, o, t, g in self.placed]
        self.load("seating.csv", HEADER_C, *rows)
        for order_id, case in zip(ids, cases):
            got = self.conn.execute(
                "SELECT seating_fit, seating_unit, unit_seats, guests_implausible "
                "FROM staging.order_seating WHERE order_id = %s", (order_id,)).fetchone()
            self.assertEqual(got, case[3], case[:3])

    def test_party_placement_follows_the_floor_plan_in_force_that_day(self):
        self.run_cases([
            # opened,           table, guests, (fit, unit, seats, implausible)
            ("1/10/26 7:00 PM", "E3", 5, ("table", "E3", 6, False)),              # E3 is the large table now
            ("10/1/25 7:00 PM", "E3", 5, ("combination", "E1+E2+E3", 6, False)),  # it seated 2 before 11/24/25
            ("10/1/25 7:00 PM", "E4", 2, ("table", "E4", 2, False)),
            ("10/1/25 7:00 PM", "E4", 4, ("combination", "E4+E5", 4, False)),
            ("10/1/25 7:00 PM", "BD2", 6, ("combination", "BD1+BD2", 6, False)),
            ("10/1/25 7:00 PM", "BD4", 7, ("combination", "BD3+BD4+BD5", 7, False)),
            ("10/1/25 7:00 PM", "BD4", 8, ("whole_room", "Black Duck (whole room)", 13, False)),
            ("1/10/26 7:00 PM", "E4", 2, ("unknown_table", None, None, False)),   # E4 gone after 11/23/25
            ("3/1/26 7:00 PM", "BD2", 6, ("combination", "BD1+BD2", 6, False)),
            ("3/1/26 7:00 PM", "BD2", 10, ("whole_room", "Black Duck (whole room)", 14, False)),
            ("3/1/26 7:00 PM", "BD2", 16, ("over_capacity", "Black Duck (whole room)", 14, False)),
            ("3/1/26 7:00 PM", "O6", 2, ("table", "O6", 2, False)),
            ("3/1/26 7:00 PM", "O6", 3, ("over_capacity", "O6", 2, False)),    # O6 never combines
            ("3/1/26 7:00 PM", "O6", 40, ("over_capacity", "O6", 2, True)),
            ("3/1/26 7:00 PM", "B1", 2, ("bar", None, None, False)),
            ("3/1/26 7:00 PM", "B1", 13, ("bar", None, None, True)),
            ("3/1/26 7:00 PM", "", 4, ("no_table", None, None, False)),
        ])


@unittest.skipUnless(REAL_EXPORTS, "no exports in data/exports/")
class StagingOnRealExports(ScratchDB):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        load_raw.load_all(cls.conn)
        load_raw.refresh_models(cls.conn)

    def setUp(self):
        pass    # keep the loaded data across tests in this class

    def scalar(self, query):
        return self.conn.execute(query).fetchone()[0]

    def test_one_row_per_id_covering_every_id_in_raw(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM staging.orders"),
                         self.scalar('SELECT count(DISTINCT "Order Id") FROM raw.order_details_c'))
        self.assertEqual(self.scalar("SELECT count(*) - count(DISTINCT order_id) FROM staging.orders"), 0)
        self.assertEqual(
            self.scalar("SELECT count(*) - count(DISTINCT item_selection_id) FROM staging.item_selections"), 0)

    def test_every_timestamp_parses(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM staging.orders WHERE opened_at IS NULL"), 0)
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM staging.orders o JOIN raw.order_details_c r USING (load_id, source_row_number) "
            "WHERE r.\"Closed\" <> '' AND o.closed_at IS NULL"), 0)
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM staging.item_selections WHERE sent_at IS NULL OR ordered_at IS NULL"), 0)

    def test_item_net_prices_reconcile_to_order_amount(self):
        mismatches = self.scalar(
            "SELECT count(*) FROM staging.orders o JOIN (SELECT order_id, sum(net_price) AS s "
            "FROM staging.item_selections WHERE NOT is_void GROUP BY 1) i USING (order_id) "
            "WHERE o.amount <> i.s")
        self.assertEqual(mismatches, 0)

    def test_every_order_is_placed_once_on_a_known_table(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM staging.order_seating"),
                         self.scalar("SELECT count(*) FROM staging.orders"))
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM staging.order_seating WHERE seating_fit = 'unknown_table'"), 0)

    def test_total_is_amount_plus_tax_tip_gratuity(self):
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM staging.orders WHERE amount + tax + tip + gratuity <> total"), 0)


if __name__ == "__main__":
    unittest.main()
