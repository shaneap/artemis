# Artemis

Exploratory analysis of restaurant order data — looking at how table value scales with party size, and at how tables are used across a night, to inform seating and table-management decisions.

The shared pipeline lives in [artemis.py](artemis.py); the analysis notebook ([analysis.ipynb](analysis.ipynb)) imports it. There are two layers:

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

Large parties are the most valuable per hour of table time — 15.6% of seatings, **30% of section revenue** — but there is no layout problem to solve: **81% of parties of 5+ fit entirely within a single physical unit**, and 30 of the 46 reservation seats sit in units that take five or more. (An earlier version of this README claimed `E3` was the only such table; that was an artifact of the pre-banquette capacity model and is retracted.)

Separately, parties per night fell from ~26 (Jan/Feb) to ~18 (Jun/Jul) while average party size held steady — a footfall decline, not a mix shift. Six months cannot separate that from seasonality.

## The owner-facing report

[owner_report.html](owner_report.html) is the deliverable — a plain-language write-up for the operator covering their three original questions, the four seating and pricing questions from the bar visit, and the Tock access request. Open it in a browser, or publish it as an artifact.

It is hand-written prose rather than a generated page, because the narrative is the substance. To keep it from going stale, **`python report_figures.py [export.csv]` recomputes every number the report quotes**, labelled and in the order they appear — drop in a newer export, run it, and update the figures against the output.

## The owner's questions

`analysis.ipynb` closes with a section answering the operator's seven written questions directly. In brief:

| Question | Answer |
| --- | --- |
| Seat 2/3-guest parties back to back? | Not where the money is — worth ~$9K/yr, and only if someone is waiting |
| Revenue by time of day? | In progress — utilization by day is done, demand curves are next |
| Value per person per 15 min? | Done — ~$6–8/guest; more usefully, $61/table-hour for a 2-top vs $126 for a 6-top |
| Are the $1,200 / $900 event rates priced well? | **Yes** — each beats 99% of nights' best 3-hour blocks |
| Should `E3` seat a 4? | **Yes** — the conflict arises about once every five nights, and those parties still got seated |
| Should `BD1`+`BD2` seat a 5? | **Yes**, and it already happens — they are one 6-seat banquette |
| Weight larger parties in 15-min intervals? | Already handled — TPCPM does this by construction; the allowance isn't binding either |

Two refinements on event pricing: the midweek premium is much larger than the weekend one (~$830 on a Tuesday vs ~$458 on a Saturday), so midweek discounting is nearly free; and Black Duck's best-ever 3-hour block of $1,440 exceeds the $1,200 rate, so peak weekends are slightly underpriced.

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
jupyter notebook analysis.ipynb
```

## Data

Order export CSVs (`OrderDetails_*.csv`) are not tracked in this repo — drop your own exports in the project root before running the notebook. Expected columns include `Amount`, `# of Guests`, `Opened`, `Closed`, `Duration (Opened to Paid)`, and `Table`.

## Seating units

**The POS table code is not the physical unit.** Black Duck and Evangeline are banquettes subdivided into two codes each, and most Open Lounge tables pair up. Toast records a whole-banquette booking against one of its codes, so comparing guest count to that code's own capacity makes an ordinary booking look like an overflow. `SEATING_UNITS` in [artemis.py](artemis.py) models the real furniture:

| Unit | POS codes | Seats |
| --- | --- | --- |
| Black Duck large banquette | `BD3` + `BD5` | 8 |
| Black Duck small banquette | `BD1` + `BD2` | 6 |
| Evangeline pair | `E1` + `E2` | 4 |
| Evangeline large | `E3` | 5-6 |
| `O1`+`O2` | combo pair | 5 |
| `O4`+`O5` | combo pair | 4 |
| `O7`+`O8` | combo pair | 5 |
| `O9`+`O10` | combo pair | 4 |
| `O3`, `O6` | never combine | 2 each |
| Bar | `B1`-`B12` | 1 each |

Section totals: **Open Lounge 22, Black Duck 14, Evangeline 10, Bar 12** — matching the operator's own figures exactly.

The pairings are confirmed against Tock and independently against the order data: when a code hosts a party too large for its own half, its partner is empty 92-100% of the time, versus 20-66% for small parties. Non-adjacent control pairs show no such effect. `verify_artemis.py` enforces this as an invariant.

`Capacity_Min`/`Capacity_Max` remain per-code as the *solo* range — what a code seats when its partner is in separate use. Notes:

- **Bar**: `B13`/`B14` are standing-wait placeholders (used when a guest is served while waiting for a stool to free up), not physical seats — no capacity, excluded from capacity checks but still counted in Bar revenue.
- **Black Duck**: `BD5` is **active**, not retired. `BD4` *is* retired; its historical orders are excluded entirely from the notebook.
- **Open Lounge**: only `O1` and `O8` seat 3. `O10` seats 2 — it reads as a 3-seater in some notes, but Tock says 2 and the data agrees (46% two-guest, 44% four-guest, only 9% threes — the signature of a 2-top that becomes a 4-top with `O9`).

## Combined bookings — mostly resolved

**This was the repo's largest open issue.** The overbooking check previously flagged roughly half of all rows. The cause was measurement, not operations: guest counts were being compared against half a banquette. Against whole-unit capacity:

| Section | Exceeds solo code | Exceeds whole unit |
| --- | --- | --- |
| Black Duck | 49% | **9%** |
| Evangeline | 27% | **7%** |
| Open Lounge | 27% | **1%** |

(Earlier README versions quoted Black Duck at 60%, computed when `BD1` and `BD5` were modelled as 2-seaters.)

**What remains is genuine.** About 100 reservation-section rows — median 8 guests, up to 18, ~$41K — really do span multiple units. **Root cause, confirmed against Toast's API docs: Toast ties one order to exactly one table.** A check has a single table reference, and combining checks moves items onto one destination check with no record of which others fed in. That is a platform limitation, not an export setting, so the true unit count behind those bookings is unrecoverable after the fact.

`Likely_Combined_Booking` (now `# of Guests > Unit_Capacity`) splits them into a descriptive-only summary so the revenue stays visible without diluting per-seat metrics. The old per-code definition is retained as `Exceeds_Solo_Capacity` so the difference stays measurable. The remaining fix is unchanged in kind but far smaller in scope: a Toast floor-plan combo configuration, or a staff tagging convention at merge time.

**The Bar is a separate case** and still flags ~78% of its rows — a 2-guest check on a 1-seat stool is a routine 2-top, not a multi-unit booking. It is excluded from the combined-booking summary for that reason.
