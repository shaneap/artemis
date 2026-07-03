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

`Table` codes map to four seating areas: `B#` (Bar, 12 single-guest stools), `BD#` (Black Duck), `E#` (Evangeline), `O#` (Open Lounge). Capacity per table is defined in the `TABLE_CAPACITY` mapping in the notebook.

### Open questions / data clarifications needed

- **Bar seats `B13`/`B14`** appear in the order data but aren't part of the known 12 bar stools — their meaning is unconfirmed, so they're currently excluded from capacity-based analysis.
- **Black Duck 4-seat vs 5-seat assignment** per specific table number isn't confirmed. The notebook infers capacity from each table's most frequent (`mode`) `# of Guests` rather than the max, since parties routinely get combined across tables (e.g. BD3/BD5 have recorded parties up to 15) which makes max useless as a capacity signal. Mode resolves Evangeline's layout cleanly but not Black Duck's — once the real floor plan is known, fill in `MANUAL_CAPACITY_OVERRIDES` in the capacity-mapping cell (e.g. `{'BD1': 4, 'BD3': 5}`) to override the estimate without changing any other code.
- **Evangeline's flexible table** (one of `E1`–`E3` seats 5–6 depending on setup) — mode-based inference identifies `E3` as this table (dominant mode of 6) and models its capacity as 6 for calculations, which should be verified.
