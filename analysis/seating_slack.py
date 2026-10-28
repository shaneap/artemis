"""On Friday and Saturday evenings, could one more party have been seated?

    python3 analysis/seating_slack.py   # prints the report and writes analysis/results/seating_slack.md

For every Fri/Sat 15-minute slot from 6pm to 10pm, and a party of 2, 4 or 6 arriving then and
staying the typical weekend-evening time for its size, three tests:

  as seated      some table or listed combination was free for the whole stay, on the floor
                 as it was actually used (analytics.fact_table_occupancy);
  re-seated      the same parties, at their actual times and stays, could have been given
                 different tables in their own section to make room (an integer program);
  any section    the same, but parties may also move between sections.

Nobody who actually came is turned away or moved in time. Where even "any section" fails, the
room was full: anyone else who wanted a table then was turned away or waited, and Toast can't
show it. A reset time can be required around the new party (the table must be clear that long
before and after it).

Re-seated parties keep a table or combination that seats them. Parties whose seating is uncertain
stay exactly where they were: whole-room and over-capacity placements, likely typo guest counts,
parties whose combination partner was in separate use, and checks overlapping on the same table
(usually one party split across checks). Bar and Monday excluded.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.db import RESULTS, query  # noqa: E402

SIZES = (2, 4, 6)
SLOTS = range(18 * 4, 22 * 4)            # 6:00pm .. 9:45pm arrivals (15-minute slots)
RESETS = (0, 15)                          # minutes clear before and after the new party
SECTIONS = ("Black Duck", "Evangeline", "Open Lounge")


def load():
    occ = query("""
        SELECT o.order_id, o.service_date, o.table_code, o.section, o.is_recorded_table,
               o.seating_fit, o.start_at, o.end_at, f.guests, f.amount, s.seating_unit,
               s.guests_implausible
        FROM analytics.fact_table_occupancy o
        JOIN analytics.fact_order f USING (order_id)
        JOIN staging.order_seating s USING (order_id)
        JOIN analytics.dim_date d ON d.date_key = o.date_key
        WHERE d.is_fri_or_sat""")
    for c in ("service_date", "start_at", "end_at"):
        occ[c] = pd.to_datetime(occ[c])
    occ["start"] = (occ.start_at - occ.service_date).dt.total_seconds() / 60
    occ["end"] = (occ.end_at - occ.service_date).dt.total_seconds() / 60

    tables = query("SELECT table_code, section, seats_max, valid_from, valid_to FROM staging.floor_plan_tables")
    combos = query("""SELECT combination, section, table_codes, seats, valid_from, valid_to
                      FROM staging.floor_plan_combinations WHERE NOT is_whole_room""")
    for d in (tables, combos):
        d["valid_from"] = pd.to_datetime(d.valid_from)
        d["valid_to"] = pd.to_datetime(d.valid_to)
    stays = query("""
        SELECT f.guests, percentile_cont(0.5) WITHIN GROUP (ORDER BY f.duration_minutes) AS minutes
        FROM analytics.fact_order f JOIN analytics.dim_date d USING (date_key)
        WHERE d.is_fri_or_sat AND f.section IN ('Black Duck', 'Evangeline', 'Open Lounge')
          AND f.in_time_metrics AND extract(hour FROM f.opened_at) BETWEEN 18 AND 21
        GROUP BY 1""").set_index("guests").minutes.astype(float)
    return occ, tables, combos, {s: stays[s] for s in SIZES}


def units_on(date, tables, combos):
    """Tables and listed combinations on the floor that night: (name, section, tables, seats)."""
    valid = lambda d: d[(d.valid_from <= date) & (d.valid_to.isna() | (d.valid_to > date))]
    t = valid(tables[tables.section.isin(SECTIONS)])
    c = valid(combos)
    units = [(r.table_code, r.section, (r.table_code,), r.seats_max) for r in t.itertuples()]
    units += [(r.combination, r.section, tuple(r.table_codes), r.seats) for r in c.itertuples()]
    return units


def overlaps(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


class Night:
    """One night's parties, split into those that may be re-seated and fixed blocks."""

    def __init__(self, g, units):
        self.units = units
        unit_tables = {u[0]: set(u[2]) for u in units}
        parties = (g.groupby("order_id")
                     .agg(tables=("table_code", lambda s: frozenset(s)), start=("start", "first"),
                          end=("end", "first"), guests=("guests", "first"), fit=("seating_fit", "first"),
                          unit=("seating_unit", "first"), typo=("guests_implausible", "first"),
                          section=("section", "first"))
                     .reset_index())
        rec = g[g.is_recorded_table].set_index("order_id").table_code
        parties["recorded"] = parties.order_id.map(rec)

        # checks overlapping on the same recorded table: usually one party, so keep them fixed
        split = set()
        for _, r in g[g.is_recorded_table].sort_values("start").groupby("table_code"):
            latest = None                      # the check that ends last so far
            for row in r.itertuples():
                if latest is not None and row.start < latest.end:
                    split.update((latest.order_id, row.order_id))
                if latest is None or row.end > latest.end:
                    latest = row
        movable = (parties.fit.isin(["table", "combination"]) & ~parties.typo
                   & ~parties.order_id.isin(split)
                   & np.array([set(t) == unit_tables.get(u, {rc}) for t, u, rc in
                               zip(parties.tables, parties.unit.fillna(""), parties.recorded)]))
        self.fixed = [(t, r.start, r.end) for r in parties[~movable].itertuples() for t in r.tables]
        self.parties = parties[movable].reset_index(drop=True)
        self.actual = parties

    def blocked(self, unit_tables, start, end):
        return any(t in unit_tables and overlaps(start, end, s, e) for t, s, e in self.fixed)

    def as_seated_fits(self, start, end, size):
        """Is some unit seating `size` free for [start, end) on the floor as actually used?"""
        busy = [(t, r.start, r.end) for r in self.actual.itertuples() for t in r.tables]
        return any(seats >= size and not any(t in tabs and overlaps(start, end, s, e) for t, s, e in busy)
                   for _, _, tabs, seats in self.units)

    def reseat_fits(self, start, end, size, same_section):
        """Integer program: re-assign movable parties so that a new party fits [start, end)."""
        options = []          # (party index or -1 for the new party, unit tables, start, end)
        for i, p in enumerate(self.parties.itertuples()):
            for name, sec, tabs, seats in self.units:
                own = set(tabs) == set(p.tables)
                if not own and (seats < p.guests or (same_section and sec != p.section)):
                    continue
                if own or not self.blocked(tabs, p.start, p.end):
                    options.append((i, tabs, p.start, p.end))
        new = [(-1, tabs, start, end) for _, _, tabs, seats in self.units
               if seats >= size and not self.blocked(tabs, start, end)]
        if not new:
            return False
        options += new
        n_parties = len(self.parties)

        # one option per party (and for the new one); each table holds one party at a time,
        # checked at every interval start (enough for intervals)
        events = sorted({o[2] for o in options})
        tables = sorted({t for o in options for t in o[1]})
        A = lil_matrix((n_parties + 1 + len(events) * len(tables), len(options)))
        for j, (i, tabs, s, e) in enumerate(options):
            A[i if i >= 0 else n_parties, j] = 1
        r0 = n_parties + 1
        for k, t in enumerate(tables):
            for m, ev in enumerate(events):
                row = r0 + k * len(events) + m
                for j, (i, tabs, s, e) in enumerate(options):
                    if t in tabs and s <= ev < e:
                        A[row, j] = 1
        lo = np.r_[np.ones(n_parties + 1), np.zeros(len(events) * len(tables))]
        hi = np.ones(n_parties + 1 + len(events) * len(tables))
        res = milp(c=np.zeros(len(options)), constraints=LinearConstraint(A.tocsr(), lo, hi),
                   integrality=np.ones(len(options)), bounds=Bounds(0, 1),
                   options={"time_limit": 20})
        self.last_solution = ([o for o, x in zip(options, res.x) if x > 0.5]
                              if res.status == 0 else None)
        return res.status == 0


def main():
    occ, tables, combos, stay = load()
    results, infeasible_nights = [], []
    for date, g in occ.groupby("service_date"):
        night = Night(g, units_on(date, tables, combos))
        # the actual seating must be a solution: a new party at 5am fits only if it is
        if not night.reseat_fits(29 * 60, 29 * 60 + 1, 1, same_section=True):
            infeasible_nights.append(date)
            continue
        for reset in RESETS:
            for size in SIZES:
                for slot in SLOTS:
                    t0 = slot * 15
                    s, e = t0 - reset, t0 + stay[size] + reset
                    seated = night.as_seated_fits(s, e, size)
                    anywhere = seated or night.reseat_fits(s, e, size, same_section=False)
                    section = seated or (anywhere and night.reseat_fits(s, e, size, same_section=True))
                    results.append((date, date.day_name(), reset, size, slot, seated, section, anywhere))
    if infeasible_nights:
        print(f"skipped {len(infeasible_nights)} night(s) whose actual seating the model rejects: "
              f"{[f'{d:%Y-%m-%d}' for d in infeasible_nights]}")
    r = pd.DataFrame(results, columns=["date", "day", "reset", "size", "slot", "seated", "section", "anywhere"])
    report(r, stay, occ)


def clock(slot):
    h, m = divmod(slot * 15, 60)
    return f"{(h - 1) % 12 + 1}:{m:02d}pm"


def report(r, stay, occ):
    nights = r.date.nunique()
    lines = []
    p = lines.append
    p("# Friday and Saturday evenings: could one more party have been seated?\n")
    p(f"{nights} Friday and Saturday nights, {r.date.min():%b %-d, %Y} to {r.date.max():%b %-d, %Y}; "
      f"arrivals every 15 minutes from 6pm to 9:45pm. The new party stays the typical weekend-evening "
      f"time for its size ({', '.join(f'{s}: {stay[s]:.0f} min' for s in SIZES)}). Nobody who actually "
      "came is moved in time or turned away.\n")
    p("- **As seated**: a table or listed combination was free for the whole stay, as the floor was actually used.")
    p("- **Re-seated**: the same parties given different tables in their own section could have made room.")
    p("- **Any section**: the same, letting parties move between sections.")
    p("- **Full**: not even that. Anyone else wanting a table then was turned away or waited; Toast can't see them.\n")

    for reset in RESETS:
        d = r[r.reset == reset]
        p(f"## {'No reset time' if reset == 0 else f'{reset}-minute reset before and after'}\n")
        p("Share of 6-10pm arrival slots:\n")
        p("| Party | As seated | Re-seated (section) | Any section | Full |")
        p("|---|---|---|---|---|")
        for size in SIZES:
            x = d[d["size"] == size]
            p(f"| {size} | {100 * x.seated.mean():.0f}% | {100 * x.section.mean():.0f}% | "
              f"{100 * x.anywhere.mean():.0f}% | {100 * (~x.anywhere).mean():.0f}% |")
        p("")
        p("Nights with at least one 6-10pm slot where the party could not be seated as the floor was used, "
          "and where it could not be seated at all:\n")
        p("| Party | Blocked as seated | Re-seating would have made room | Full (no seating works) | Full for an hour or more |")
        p("|---|---|---|---|---|")
        for size in SIZES:
            x = d[d["size"] == size]
            blocked = x[~x.seated].date.nunique()
            freed = x[~x.seated & x.section].date.nunique()
            full = x[~x.anywhere]
            hour_plus = (full.groupby("date").size() >= 4).sum()
            p(f"| {size} | {blocked} of {nights} | {freed} | {full.date.nunique()} | {hour_plus} |")
        p("")
        p("When the room was full for a party of 4, by arrival time (share of nights):\n")
        x = d[d["size"] == 4]
        by = x.groupby("slot").anywhere.apply(lambda s: 100 * (~s).mean())
        p("| " + " | ".join(clock(s) for s in by.index[::2]) + " |")
        p("|" + "---|" * len(by.index[::2]))
        p("| " + " | ".join(f"{v:.0f}%" for v in by.values[::2]) + " |")
        p("")

    d = r[r.reset == 0]
    six = d[d["size"] == 6]
    p("## Reading it\n")
    p(f"- Re-seating recovers a slot that the floor as used had blocked in "
      f"{100 * (six.section & ~six.seated).sum() / max((~six.seated).sum(), 1):.0f}% of blocked party-of-6 "
      f"cases (2: {100 * (d[d['size'] == 2].section & ~d[d['size'] == 2].seated).sum() / max((~d[d['size'] == 2].seated).sum(), 1):.0f}%, "
      f"4: {100 * (d[d['size'] == 4].section & ~d[d['size'] == 4].seated).sum() / max((~d[d['size'] == 4].seated).sum(), 1):.0f}%). "
      "That is capacity lost to which table each party got, not to having too few tables.")
    p("- The **Full** column is where seating policy can't help: more tables were wanted than existed. "
      "How many parties were turned away in those slots, and whether people booked elsewhere, needs "
      "reservation data (Tock): requests, denials, waitlists and no-shows.")
    text = "\n".join(lines) + "\n"
    print(text)
    (RESULTS / "seating_slack.md").write_text(text)


if __name__ == "__main__":
    main()
