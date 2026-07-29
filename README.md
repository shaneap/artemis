# Artemis

Exploratory analysis of restaurant order data — looking at how table value scales with party size, to inform seating and table-management decisions.

The core notebook ([test.ipynb](test.ipynb)) loads per-order exports (guest count, amount, open/close times), derives table duration and two revenue-rate metrics, and visualizes how they trend across party sizes and seating sections.

## Status

**Active / exploratory.** The core pipeline (load → clean → section/capacity mapping → VPCPM/TPCPM → shrinkage-weighted section summaries) runs end to end with no known correctness bugs. See [CHANGELOG.md](CHANGELOG.md) for what's been fixed and when.

**Known open issues (not yet resolved):**
- **Multi-table/combined bookings are unrecoverable from Toast exports** — see [Combined bookings & the capacity mismatch](#combined-bookings--the-capacity-mismatch) below. Current mitigation is a flag (`Likely_Combined_Booking`) that splits these rows into a descriptive-only summary; this is a backburner item pending a POS-side or process-level fix, not something fixable in the notebook alone.
- **95% confidence intervals are paused** pending a proper significance-testing pass on the shrinkage-weighted estimates.
- **The LOOCV `k`-grid is coarse** (`[1, 2, 3, 5, 8, 12, 20, 30, 50, 75, 100, 150, 200]`) — good enough so far (selected values haven't landed on a grid boundary), but a finer or continuous search would be more rigorous.

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
