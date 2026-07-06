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
- **Black Duck** (only `BD1`-`BD3` in use — `BD5` is retired, excluded like `B13`/`B14`): `BD1` seats 2, `BD2` seats 2-3, `BD3` seats 3-4.
- **Evangeline**: `E1`/`E2` seat 2 each, `E3` flexes 5-6.
- **Open Lounge**: `O1`, `O8`, `O10` seat 3; the rest seat 2.

### Open Lounge table combinations

Four Open Lounge table pairs have a confirmed combined capacity (no seating-option distinction) for when a party is seated across both tables at once:

| Combo | Min | Max |
| --- | --- | --- |
| `O1`+`O2` | 4 | 5 |
| `O4`+`O5` | 3 | 4 |
| `O7`+`O8` | 4 | 5 |
| `O9`+`O10` | 3 | 4 |

These aren't modeled in the notebook's `Capacity_Min`/`Capacity_Max` columns: the raw `Table` field never records a combined code — each row is always a single table (e.g. `O1`), so there's no signal in the order data for when two tables were actually pushed together for one party. This is also why the overbooking sanity-check in the notebook flags a meaningful number of Open Lounge (and Black Duck) rows — those are likely legitimate combined-table parties, not data errors.
