# Artemis

Exploratory analysis of restaurant order data — looking at how table value scales with party size.

The core notebook ([test.ipynb](test.ipynb)) loads per-order exports (guest count, amount, open/close times), derives table duration and a **VPCPM** metric (value per guest, per 15 minutes), and visualizes how it trends across party sizes.

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

Order export CSVs (`OrderDetails_*.csv`) are not tracked in this repo — drop your own exports in the project root before running the notebook. Expected columns include `Amount`, `# of Guests`, `Opened`, `Closed`, and `Table`.

## Seating sections

`Table` codes map to four seating areas: `B#` (Bar, 12 single-guest stools), `BD#` (Black Duck), `E#` (Evangeline), `O#` (Open Lounge). Each table's confirmed seat range is defined in the `TABLE_CAPACITY_RANGE` mapping in the notebook (`Capacity_Min`/`Capacity_Max` columns):

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

**This turns out to be a much bigger issue than a few edge cases.** Now that capacities are the real confirmed seat counts (not the old mode-inferred estimates), the overbooking sanity-check flags roughly **half of all rows** as exceeding their table's max capacity — Bar 78%, Black Duck 61%, Evangeline 30%, Open Lounge 28%. These have two different causes: for Black Duck/Evangeline/Open Lounge, the excess-guest distribution (guests minus capacity) is wide with a long tail — consistent with a party being seated across multiple physical tables for a large booking or private event, with the whole check landing on one anchor table. For Bar, 79% of overbooked rows are exactly one guest over a 1-seat stool — a routine 2-top, not an event.

**Root cause (confirmed against Toast's own API docs): Toast's data model ties one order to exactly one table.** A check has a single table reference, and "combining checks" moves items from multiple checks onto one destination check with no record of which other tables fed into it. This isn't a report/export setting — it's a platform limitation, and it means the true table count behind a multi-table booking is unrecoverable from historical exports after the fact.

**Current mitigation (not a fix): a `Likely_Combined_Booking` flag** (`# of Guests > Capacity_Max`) in the notebook splits these rows out of the single-table, per-seat VPCPM/TPCPM analysis into their own descriptive-only summary, so they don't dilute the section/party-size recommendations. This is a known open issue on the backburner, not resolved — a real fix would need either a Toast floor-plan combo-table configuration for recurring combos (like the four Open Lounge pairs above) or a staff tagging convention at merge time, neither of which is in place yet.
