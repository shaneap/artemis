# Legacy pandas pipeline

The original analysis (Jul–Aug 2026), before the PostgreSQL warehouse. The figures in
the owner report (`../reports/owner_report.html`, private, not in the repo) come from here. Set aside rather than
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

## How it works

- **Merging exports.** Drop each Toast pull into `data/exports/` and keep the old ones;
  `merge_exports.py` upserts them into `data/orders_merged.csv` (`load_orders()` rebuilds it when
  stale). Older pulls carry `Tax` instead of `Total`/`Duration`, so their rows drop out of the time
  layer. These exports have no order ID, so identity is `Opened` + `Table` + `# of Guests` +
  an occurrence index (split checks rung in the same minute). Toast amends orders after service,
  so the newest pull wins field by field.
- **Seating units.** `SEATING_UNITS` maps POS codes to physical furniture (`BD1`+`BD2` 6,
  `BD3`+`BD5` 8, `E1`+`E2` 4, `E3` 5–6, `O1`+`O2` 5, `O4`+`O5` 4, `O7`+`O8` 5, `O9`+`O10` 4,
  `O3`/`O6` 2). The pairings are confirmed by the order data: when one code seats a party too big
  for it, its partner is empty 92–100% of the time. `BD4` is retired and excluded; `B13`/`B14` are
  standing-wait placeholders with no capacity.
- **Time layer.** Service day (4 am cutoff); turn gaps within a night (overlapping same-table
  pairs, ~2%, get a null gap and are counted in `Turn_Overlap`); an occupancy timeline of
  (night, table, 15-minute slot), with each order's revenue spread evenly over its slots.
- **Combined bookings.** `Likely_Combined_Booking` = guests > unit capacity; those rows go into a
  descriptive summary only. The Bar is excluded from it, since a 2-guest check on a stool is a
  normal 2-top.

The full pre-reorganization README, with the derivations behind each finding, is in git history
(`git show caabc61:README.md`).
