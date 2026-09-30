# Artemis — context for Claude

Analysis of one bar/restaurant's Toast POS order exports (Ronkonkoma, NY) to answer the owner's
seating, turn-time, pricing and opening-hours questions. Python + pandas; no web app, no DB.
Owner-facing deliverable is `owner_report.html`.

## Read this first, not everything

- **Don't read `analysis.ipynb` whole** — ~740 KB of embedded outputs. Find the cell you need
  with a `python3 -c` JSON scan of `cells[i]['source']` (59 cells; section headings at cells
  6, 26, 40, 47). Edit it with NotebookEdit.
- **Don't read `README.md` / `CHANGELOG.md` whole** (~19 KB / ~18 KB). Findings, methodology
  and history are summarized below; grep them for a specific number or date.
- **Don't cat CSVs** in `data/` or `weather_cache.csv`. Use pandas with `nrows`/`head`.
  Export format details are in `docs/column_inventory.md`.
- `owner_report.html` is hand-written prose (~30 KB); only open it when editing the report.

## Files

| File | Role |
| --- | --- |
| `artemis.py` | Shared pipeline. Constants (`SEATING_UNITS`, `CAPACITY_RANGES`, `RESERVATION_SECTIONS`, `SERVICE_DAY_CUTOFF_HOUR=4`, `EVENT_AMOUNT_THRESHOLD=400`, `DURATION_FLOOR_MINUTES=15`), `load_orders()`, `classify_order_type`, `apply_duration_floor`, time layer: `add_service_day`, `add_turn_gaps`, `build_occupancy`, `utilization_by_slot`. Single source of truth — notebook and scripts import it. |
| `merge_exports.py` | Upserts every `data/exports/OrderDetails_*.csv` into `data/orders_merged.csv` (+ `.meta.json` manifest). Identity = `Opened`+`Table`+`# of Guests`+occurrence index; newest pull wins field by field. `load_orders()` rebuilds it automatically when stale. |
| `load_raw.py`, `sql/`, `docker-compose.yml`, `tests/test_raw_load.py` | Phase 1 (design decisions in `DECISIONS.md`, owned by the user — don't edit): PostgreSQL raw layer. `docker compose up -d` (creds from `.env`) runs `sql/*.sql`; `python3 load_raw.py` loads `data/exports/` as-is into `raw.order_details_a/_b`, skipping files whose SHA256 is in `raw.load_log`. Independent of the old pipeline. Tests: `python3 -m unittest tests.test_raw_load` (needs a live Postgres). |
| `verify_artemis.py` | The test suite: 18 invariant checks, PASS/FAIL, nonzero exit on failure. ~1 s. |
| `report_figures.py` | Recomputes every number quoted in `owner_report.html`, in document order. |
| `weather.py` | Open-Meteo daily archive for Ronkonkoma, cached to `weather_cache.csv`; holiday calendar. |
| `analysis.ipynb` | Narrative analysis: VPCPM/TPCPM by party size & section → turn times & utilization → owner's 7 questions → revenue by time of day / weather. |
| `docs/column_inventory.md` | 2026-09-27 audit of the raw exports (two column layouts, duplicate rows, no order ID, key collisions). Feeds decisions D002/D008 in `DECISIONS.md`. |
| `Artemis.Rproj`, `.Rhistory` | Leftover RStudio files; unused. |

## Commands

`python` is not on PATH — always use `python3`. `jupyter` is not on PATH either; use `python3 -m jupyter`.

```bash
python3 verify_artemis.py            # run after any pipeline change
python3 merge_exports.py --dry-run   # merge report without writing
python3 report_figures.py            # figures for the owner report
python3 -m jupyter nbconvert --to notebook --execute --inplace analysis.ipynb   # re-run notebook
```

## Domain model (the non-obvious parts)

- **Sections:** Black Duck (BD), Evangeline (E), Open Lounge (O) = reservation sections, 17
  tables / 46 seats. Bar (B1–B12, 12 seats) is walk-up, reference only. `B13`/`B14` are
  standing-wait placeholders (no capacity). `BD4` retired and excluded; `BD5` active.
- **POS table code ≠ physical unit.** Banquettes/pairs: `BD1+BD2` (6), `BD3+BD5` (8),
  `E1+E2` (4), `E3` (5–6), `O1+O2` (5), `O4+O5` (4), `O7+O8` (5), `O9+O10` (4); `O3`, `O6`
  standalone 2-tops. Seat totals: OL 22, BD 14, E 10, Bar 12. Capacity checks use
  `Unit_Capacity`; `Capacity_Min/Max` are per-code solo ranges.
- **Service day** cuts at 4 am (a Friday running to 1:30 am is Friday).
- **Duration** = Toast's `Duration (Opened to Paid)`, never `Closed − Opened` (Closed is a batch
  close-out). Only the Jan–Jul export has it; older (Type B) exports have `Tax` instead of
  `Total`/`Duration`, so their rows drop out of turn-gap/occupancy layers.
- **Order_Type:** `Seated` / `Event-Catering` (untabled, ≥ $400) / `To-Go`. Only Seated feeds
  per-seat metrics.
- **VPCPM** = (Amount/guests)/(Duration/15); **TPCPM** = Amount/(Duration/15). Aggregated on log
  scale (geometric mean). Per-section, per-metric shrinkage `k` chosen by LOOCV; `Thin Sample`
  flag when < 10 orders. `Amount` is already net of discounts.
- **Toast limits:** one order ↔ one table; no order/check ID in exports; orders get amended
  after service. `Likely_Combined_Booking` (guests > unit capacity, ~100 rows, ~$41K) is
  unrecoverable and reported descriptively only.

## Settled findings (don't re-derive unless data changes)

- Constraint is **demand, not turn speed**: room never full; median utilization 29%; turn gaps
  shrink as room fills; faster turning worth ~$9K/yr.
- 81% of 5+ parties fit one physical unit — no floor-plan problem.
- Event rates $1,200 (BD) / $900 (E) are well priced. E3 should seat 4s; BD1+BD2 seat 5s.
- Hours: open 5 pm Tue–Thu, close midnight Tue/Wed/Sun, leave Fri/Sat (framed as break-even).
- Rain no effect. Decline vs seasonality **cannot be separated** in Jan–Jul (time/temp r=0.90);
  needs last year's Toast export.
- Open items: 95% CIs paused; LOOCV k-grid is coarse; combined bookings need a POS/process fix.

## Conventions

- Keep logic in `artemis.py`/`merge_exports.py`, not the notebook. New invariants go in
  `verify_artemis.py` (no pytest).
- If a change moves any reported number, run `report_figures.py` and reconcile
  `owner_report.html` and the README tables.
- Log notable changes in `CHANGELOG.md` (dated sections: Added / Changed / Fixed / Findings /
  Methodology / Retracted). Retract wrong claims explicitly rather than silently editing.
- Prose style: plain language, state what the data can't tell you, figures with context.
- Data (`*.csv`) is gitignored; never commit exports.
- Branch: work on feature branches (currently `occupancy-layer`); `main` is the PR base.
- Commits/PRs: no Claude co-author or AI attribution lines.
