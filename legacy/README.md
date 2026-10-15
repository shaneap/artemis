# Legacy pandas pipeline

The original analysis (Jul–Aug 2026), before the PostgreSQL warehouse. The figures in
[`../reports/owner_report.html`](../reports/owner_report.html) come from here. Set aside rather than
deleted; new work goes in the warehouse (`../sql/`, `../analysis/`).

| File | Role |
| --- | --- |
| `artemis.py` | Shared pipeline: loading, cleaning, seating units, VPCPM/TPCPM, service day, turn gaps, occupancy. |
| `merge_exports.py` | Merges every `../data/exports/OrderDetails_*.csv` into `../data/orders_merged.csv`. |
| `verify_artemis.py` | 18 invariant checks, PASS/FAIL. |
| `report_figures.py` | Recomputes every number quoted in the owner report. |
| `analysis.ipynb` | The narrative analysis notebook. |

Run from the repository root (data paths are resolved from the files, so the working directory
doesn't matter):

```bash
python3 legacy/verify_artemis.py
python3 legacy/merge_exports.py --dry-run
python3 legacy/report_figures.py
python3 -m jupyter nbconvert --to notebook --execute --inplace legacy/analysis.ipynb
```

`weather.py` stays at the repository root because the warehouse analysis uses it too; the report
script and notebook add the root to `sys.path`.
