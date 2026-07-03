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
