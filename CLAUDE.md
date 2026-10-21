# Artemis — context for Claude

Analysis of one bar/restaurant's Toast POS order exports (Ronkonkoma, NY) to answer the owner's
seating, turn-time, pricing and opening-hours questions. Python + pandas, with a PostgreSQL warehouse (see **Warehouse**); no web app.
Owner-facing deliverable is `reports/owner_report.html` (gitignored: client-private, never commit). The old pandas pipeline lives in `legacy/`.

## Read this first, not everything

- **Don't read `legacy/analysis.ipynb` whole** — ~740 KB of embedded outputs. Find the cell you need
  with a `python3 -c` JSON scan of `cells[i]['source']` (59 cells; section headings at cells
  6, 26, 40, 47). Edit it with NotebookEdit.
- **Don't read `README.md` / `CHANGELOG.md` whole** (~19 KB / ~18 KB). Findings, methodology
  and history are summarized below; grep them for a specific number or date.
- **Don't cat CSVs** in `data/` or `weather_cache.csv`. Use pandas with `nrows`/`head`.
  Export format details are in `docs/column_inventory.md`.
- `reports/owner_report.html` is hand-written prose (~30 KB); only open it when editing the report.

## Files

| File | Role |
| --- | --- |
| `legacy/artemis.py` | Shared pipeline. Constants (`SEATING_UNITS`, `CAPACITY_RANGES`, `RESERVATION_SECTIONS`, `SERVICE_DAY_CUTOFF_HOUR=4`, `EVENT_AMOUNT_THRESHOLD=400`, `DURATION_FLOOR_MINUTES=15`), `load_orders()`, `classify_order_type`, `apply_duration_floor`, time layer: `add_service_day`, `add_turn_gaps`, `build_occupancy`, `utilization_by_slot`. Single source of truth — notebook and scripts import it. |
| `legacy/merge_exports.py` | Upserts every `data/exports/OrderDetails_*.csv` into `data/orders_merged.csv` (+ `.meta.json` manifest). Identity = `Opened`+`Table`+`# of Guests`+occurrence index; newest pull wins field by field. `load_orders()` rebuilds it automatically when stale. |
| `load_raw.py`, `sql/`, `docker-compose.yml`, `tests/` | The new PostgreSQL warehouse — see **Warehouse** below. |
| `legacy/verify_artemis.py` | The legacy test suite: 18 invariant checks, PASS/FAIL, nonzero exit on failure. ~1 s. |
| `legacy/report_figures.py` | Recomputes every number quoted in `reports/owner_report.html`, in document order. |
| `weather.py` | Open-Meteo daily archive for Ronkonkoma, cached to `weather_cache.csv`; holiday calendar. Stays at the root: used by `analysis/db.py` and by `legacy/` (which adds the root to `sys.path`). |
| `legacy/analysis.ipynb` | Narrative analysis: VPCPM/TPCPM by party size & section → turn times & utilization → owner's 7 questions → revenue by time of day / weather. |
| `docs/column_inventory.md` | 2026-09-27 audit of the raw exports (two column layouts, duplicate rows, no order ID, key collisions). Feeds decisions D002/D008 in `DECISIONS.md`. |
| `RESUME_LOG.md` | Gitignored, private: Shane's resume material. |

## Commands

`python` is not on PATH — always use `python3`. `jupyter` is not on PATH either; use `python3 -m jupyter`.

```bash
python3 legacy/verify_artemis.py     # run after any pipeline change
python3 legacy/merge_exports.py --dry-run   # merge report without writing
python3 legacy/report_figures.py     # figures for the owner report
python3 -m jupyter nbconvert --to notebook --execute --inplace legacy/analysis.ipynb   # re-run notebook
```

## Warehouse (the current direction; the old pandas pipeline is set aside)

- **Decisions** live in `DECISIONS.md` (owned by the user — don't edit). When talking to the
  user, describe a decision in words, never by its D-number. Unanswered questions for the user
  are in `OPEN_QUESTIONS.md` (gitignored, private); add to it rather than to the README.
- **Run:** Docker Desktop (`open -a Docker`; CLI at `/Applications/Docker.app/Contents/Resources/bin`,
  not on PATH), `docker compose up -d` (creds in `.env`). `python3 load_raw.py` loads new files
  from `data/exports/` and refreshes staging + analytics (~6 s). After editing rules in
  `sql/005-007`: `docker compose exec -T db psql -U artemis -d artemis -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/maintenance/rebuild.sql`.
  Tests: `python3 -m unittest tests.test_raw_load tests.test_staging tests.test_analytics`
  (scratch DBs, ~20 s; unittest, not pytest).
- **Exports:** Toast `OrderDetails` (3-month files) and `ItemSelectionDetails` (monthly), Apr 25,
  2025 onward, with Order Id / Check Id / Item Selection Id. Item files are Windows-1252.
  Adjacent files overlap on their boundary date.
- **raw** (`sql/002-004`): files as received, all TEXT, `raw.load_log` by SHA256. Live tables:
  `order_details_c`, `item_selection_details_b`; `_a/_b`/`item_..._a` are legacy layouts.
- **staging** (`sql/005-006`, materialized views — plain views made the planner pick a
  2-billion-row join): `orders`, `item_selections` (one row per ID; the export whose date range
  ends latest wins; typed; `service_date` 4 am cutoff; long/negative-duration flags,
  `duration_usable`), dated floor plan `floor_plan_tables` / `floor_plan_combinations`
  (hand-maintained INSERTs; old layout until 11/24/25 Evangeline, 2/14/26 Black Duck), and
  `order_seating` (party → own table, smallest listed combination, whole room, or
  `over_capacity`; `guests_implausible` over 30, or over 12 at the bar).
- **analytics** (`sql/007`, materialized views): `dim_date`, `dim_seating_unit`, `dim_menu_item`
  (price versions inferred from the dominant monthly price of clean Qty-1 sales; identity is the
  item name), `fact_order` (order type, VPCPM/TPCPM per order when seated, 15 min–6 h, real
  guests), `fact_item_selection`. Aggregation (geometric means, shrinkage) belongs in analysis
  scripts/notebooks on top of these.
- Net Price is the line total and sums to the order's Amount; Gross Price is a unit price.
- **Analysis** lives in `analysis/` (see its README): scripts using `analysis/db.py`
  (`query()`, `nightly()` with weather), writing `analysis/results/*.md`. Mondays are closed
  (private bookings only) and left out of trend/hours work; untabled event/to-go checks are
  rung in the morning, so hour-of-night analysis uses seated trade only.

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
  shrink as room fills; faster turning worth ~$18K/yr (~1% of sales; the old "$9K/yr" was a 6-month total;
  `report_figures.py` now annualizes it).
- 81% of 5+ parties fit one physical unit — no floor-plan problem.
- Event rates $1,200 (BD) / $900 (E) are well priced. E3 should seat 4s; BD1+BD2 seat 5s.
- Hours: open 5 pm Tue–Thu, close midnight Tue/Wed/Sun, leave Fri/Sat (framed as break-even).
- Rain no effect. Decline vs seasonality (warehouse, Apr 2025–Sep 2026): **both**. Winter is the
  strong season, but same months May–Sep 2026 vs 2025 are −10% regular revenue/night, −16%
  parties; after day of week + season, parties −14%/yr (95% CI −19% to −8%). Spend per guest +8%
  via menu mix (like-for-like prices +2%). The old "cannot be separated" (Jan–Jul only) is superseded.
- Open items: 95% CIs on the per-section VPCPM/TPCPM summaries paused (trend CIs exist); LOOCV k-grid is coarse; combined bookings need a POS/process fix.

## Conventions

- Legacy pipeline: keep logic in `legacy/artemis.py`/`legacy/merge_exports.py`, not the notebook.
  New invariants go in `legacy/verify_artemis.py` (no pytest).
- If a change moves any reported number, run `legacy/report_figures.py` and reconcile
  `reports/owner_report.html` and the README tables.
- After notable progress, also add a dated entry to `RESUME_LOG.md` (gitignored, private; Shane's
  resume material — instructions at its top).
- Log notable changes in `CHANGELOG.md` (dated sections: Added / Changed / Fixed / Findings /
  Methodology / Retracted). Retract wrong claims explicitly rather than silently editing.
- Prose style: plain language, state what the data can't tell you, figures with context.
- Data (`*.csv`) is gitignored; never commit exports.
- Branch: work on feature branches (currently `occupancy-layer`); `main` is the PR base.
- Commits/PRs: no Claude co-author or AI attribution lines.
