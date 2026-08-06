# Artemis

Exploratory analysis of restaurant order data — looking at how table value scales with party size, and at how tables are used across a night, to inform seating and table-management decisions.

The shared pipeline lives in [artemis.py](artemis.py); the notebook ([test.ipynb](test.ipynb)) imports it. There are two layers:

- **Per-order layer** — loads per-order exports (guest count, amount, open/close times), derives table duration and two revenue-rate metrics (VPCPM/TPCPM), and visualizes how they trend across party sizes and seating sections.
- **Time layer** — reconstructs what the floor actually looked like: which tables were occupied in each 15-minute slot, and how long each table sat empty between parties. The per-order layer examines one order at a time and so cannot see a table sitting idle between two healthy-looking checks.

## Status

**Active / exploratory.** The core pipeline (load → clean → section/capacity mapping → VPCPM/TPCPM → shrinkage-weighted section summaries) runs end to end with no known correctness bugs. See [CHANGELOG.md](CHANGELOG.md) for what's been fixed and when.

Run `python verify_artemis.py` to check the pipeline's invariants (row counts, service-day boundary, occupancy bounds, turn-gap reconciliation).

**Known open issues (not yet resolved):**
- **Multi-table/combined bookings are unrecoverable from Toast exports** — see [Combined bookings & the capacity mismatch](#combined-bookings--the-capacity-mismatch) below. Current mitigation is a flag (`Likely_Combined_Booking`) that splits these rows into a descriptive-only summary; this is a backburner item pending a POS-side or process-level fix, not something fixable in the notebook alone.
- **95% confidence intervals are paused** pending a proper significance-testing pass on the shrinkage-weighted estimates.
- **The LOOCV `k`-grid is coarse** (`[1, 2, 3, 5, 8, 12, 20, 30, 50, 75, 100, 150, 200]`) — good enough so far (selected values haven't landed on a grid boundary), but a finer or continuous search would be more rigorous.

## The time layer

Three concepts, all derived from `Opened` + `Duration` — no new data required.

- **Service day** — a Friday that runs to 1:30am counts as Friday. Dating orders by calendar date files late-night revenue under the following day; Friday is still at ~45% table occupancy at midnight, so this materially shifted the day-of-week picture (Friday +86 orders, Sunday −82). It is also why a bar closed on Mondays appeared to have Monday orders. The cutoff is 4am (`SERVICE_DAY_CUTOFF_HOUR`), verified to fall in genuinely dead time — no order in this dataset opens between 3am and 5am.
- **Turn gap** — the dead time between one party paying and the next being seated at that table, computed within a single service night. Toast records when a party *paid*, not when the table was *cleared*, so a gap conflates guests lingering after settling up, bussing speed, and nobody waiting to be seated. Those have different fixes and this export cannot separate them.
- **Occupancy timeline** — one row per (night, table, 15-minute slot), with each order's revenue spread evenly across the slots it occupied. This is what utilization and revenue-by-time-of-night are computed from.

Two data artifacts are handled explicitly rather than silently: gaps are never computed across two nights, and ~2% of consecutive same-table pairs *overlap* (the next party appears seated before the previous paid — the combined-check artifact). Overlapping pairs get a null gap and are counted in `Turn_Overlap` so the rate stays visible.

## Key finding: the constraint is demand, not capacity or turn speed

The turn-gap work was set up to test whether idle time between parties is a recoverable lever. **It isn't**, and the evidence is fairly conclusive:

- Gaps **collapse as the room fills** — 65 min when the room is under a quarter full, 24 min when over three quarters. Lingering guests and slow bussing would not behave that way; absence of waiting customers would.
- **The room never fills.** Zero 15-minute slots in six months had all 17 reservation tables occupied; only 16 slots (about four hours of trading) reached 15 of 17. Median utilization while open is 29%, peaking around 43% on Fri/Sat.
- **No individual table is chronically bad** — best to worst spans 13 minutes across 17 tables.
- Honest value of faster turning: **~$9K/yr**, against $156K if you assume every freed minute sells. Turn gaps are only **9.4%** of unsold table time; the other 90.6% is tables that never got a party at all.

Party-size steering fails the same test — only 1.3% of seatings put a small party at a bigger table while the room was busy enough for it to matter.

What does survive is a **floor-plan** finding: parties of 5+ are 15.6% of seatings and **30% of section revenue**, but exactly one table (`E3`) seats one without pushing furniture together, so three quarters of that segment is accommodated ad hoc. This is also the root cause of the combined-booking problem below.

Separately, parties per night fell from ~26 (Jan/Feb) to ~18 (Jun/Jul) while average party size held steady — a footfall decline, not a mix shift. Six months cannot separate that from seasonality.

## Order types

Orders are labelled `Seated` / `Event-Catering` / `To-Go`. Previously everything without a table fell through the `Duration >= 15` floor and disappeared — about **$104K** of real revenue (10.7% event/catering, 2.4% to-go), silently. These aren't seated tables so they still don't belong in per-seat metrics, but they're no longer invisible.

The split is by check size (`EVENT_AMOUNT_THRESHOLD`, currently $400), not time of day: untabled orders occur across the whole operating day, but a $2,200 untabled check is a catering booking whatever hour it was rung in. Durations on untabled rows are meaningless — they range up to 18 days — because nobody was sitting anywhere.

## Methodology

- **VPCPM** (Value Per guest, Per 15 Minutes) = `(Amount / # of Guests) / (Duration / 15)`. The core per-seat comparison metric — normalizes for both party size and how long a table was occupied.
- **TPCPM** (Total revenue Per table, Per 15 Minutes) = `Amount / (Duration / 15)`. Answers the capacity-planning question directly: for a given table, does a full party or a smaller one generate more $/15min?
- **Duration** comes from Toast's own `Duration (Opened to Paid)` field, not a `Closed - Opened` timestamp diff — the latter is inflated by late/batch POS close-outs and doesn't reflect actual guest turnover.
- Both metrics are right-skewed, so aggregates are computed on a log scale (`LogVPCPM`/`LogTPCPM`) and back-transformed via `exp` (i.e. geometric mean) for display.
- **Shrinkage**: low-order-count party sizes get pulled toward their section's overall mean, weighted by a per-section, per-metric `k` selected via leave-one-out cross-validation (LOOCV) — VPCPM and TPCPM each get their own `k`, since they have different skew/variance structures. Party sizes backed by fewer than 10 orders are flagged `Thin Sample` in the summary tables.
- Analysis is split by **Bar** (walk-up, no reservations — context/reference only) vs. **reservation-relevant sections** (Black Duck, Evangeline, Open Lounge — where the shrinkage/LOOCV treatment and recommendations apply).

## Setup

No virtual environment required — just install the dependencies globally or in whatever environment you normally use:

```bash
pip install -r requirements.txt
```

Then launch the notebook:

```bash
jupyter notebook test.ipynb
```

## Data

Order export CSVs (`OrderDetails_*.csv`) are not tracked in this repo — drop your own exports in the project root before running the notebook. Expected columns include `Amount`, `# of Guests`, `Opened`, `Closed`, `Duration (Opened to Paid)`, and `Table`.

## Seating sections

`Table` codes map to four seating areas: `B#` (Bar, 12 single-guest stools), `BD#` (Black Duck), `E#` (Evangeline), `O#` (Open Lounge). Each table's confirmed seat range is defined in the `CAPACITY_RANGES` mapping in the notebook (`Capacity_Min`/`Capacity_Max` columns):

- **Bar**: `B1`-`B12` seat 1 each. `B13`/`B14` are standing-wait placeholders (used when a guest is served while waiting for an actual bar stool to free up), not physical seats — excluded from capacity-based analysis but still counted in the Bar section's revenue analysis.
- **Black Duck**: `BD1` seats 2, `BD2` seats 2-3, `BD3` seats 3-4, `BD5` seats 2. `BD5` is **active**, not retired — it carries a comparable order volume to `BD2`/`BD3` in this data. `BD4` *is* retired; its historical orders (present in exports spanning when it was still active) are excluded entirely from the notebook, not just from capacity checks.
- **Evangeline**: `E1`/`E2` seat 2 each, `E3` flexes 5-6.
- **Open Lounge**: `O1` and `O8` seat 3; every other table, including `O10`, seats 2.

### Open Lounge table combinations

Four Open Lounge table pairs have a confirmed combined capacity (no seating-option distinction) for when a party is seated across both tables at once:

| Combo | Min | Max |
| --- | --- | --- |
| `O1`+`O2` | 4 | 5 |
| `O4`+`O5` | 3 | 4 |
| `O7`+`O8` | 4 | 5 |
| `O9`+`O10` | 3 | 4 |

These aren't modeled in the notebook's `Capacity_Min`/`Capacity_Max` columns: the raw `Table` field never records a combined code — each row is always a single table (e.g. `O1`), so there's no signal in the order data for when two tables were actually pushed together for one party.

## Combined bookings & the capacity mismatch

**This turns out to be a much bigger issue than a few edge cases.** Now that capacities are the real confirmed seat counts (not the old mode-inferred estimates), the overbooking sanity-check flags roughly **half of all rows** as exceeding their table's max capacity — Bar 80%, Black Duck 60%, Evangeline 27%, Open Lounge 27%. These have two different causes: for Black Duck/Evangeline/Open Lounge, the excess-guest distribution (guests minus capacity) is wide with a long tail — consistent with a party being seated across multiple physical tables for a large booking or private event, with the whole check landing on one anchor table. For Bar, 79% of overbooked rows are exactly one guest over a 1-seat stool — a routine 2-top, not an event.

**Root cause (confirmed against Toast's own API docs): Toast's data model ties one order to exactly one table.** A check has a single table reference, and "combining checks" moves items from multiple checks onto one destination check with no record of which other tables fed into it. This isn't a report/export setting — it's a platform limitation, and it means the true table count behind a multi-table booking is unrecoverable from historical exports after the fact.

**Current mitigation (not a fix): a `Likely_Combined_Booking` flag** (`# of Guests > Capacity_Max`) in the notebook splits these rows out of the single-table, per-seat VPCPM/TPCPM analysis into their own descriptive-only summary, so they don't dilute the section/party-size recommendations. This is a known open issue on the backburner, not resolved — a real fix would need either a Toast floor-plan combo-table configuration for recurring combos (like the four Open Lounge pairs above) or a staff tagging convention at merge time, neither of which is in place yet.
