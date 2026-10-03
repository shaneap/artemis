# Changelog

All notable changes to the Artemis analysis are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## 2026-10-03

### Changed
- **Staging keeps the copy from the export whose date range ends latest** (parsed from the Toast file name), not the most recently loaded file, so loading an older export later can't overwrite newer data. Files without a dated name rank last; ties fall back to load order. Decided by Shane.

### Added
- **Dated floor plan and the combined-table fix** (`sql/006_floor_plan.sql`). `staging.floor_plan_tables` holds each table code's seats for each layout period: Black Duck and Evangeline as of Shane's 11/23/25 Toast screenshots (BD1 2, BD2 2-3, BD3 3-4, BD4 1, BD5 2; E1-E3 2, E4/E5 1), then the current layout. Change dates are inferred from last use of the retired codes: Evangeline 11/24/25, Black Duck 2/14/26. `staging.floor_plan_combinations` holds Shane's combinations (BD1+BD2, BD3+BD5, E1+E2, E1+E2+E3, O1+O2, O4+O5, O7+O8, O9+O10; E4+E5 in the old layout) plus whole-room buy-outs for Black Duck and Evangeline. `staging.order_seating` places every order: on its table, the smallest combination that seats the party, the whole room, or `over_capacity`; and flags guest counts over 30 (over 12 at the bar) as implausible. Raw is untouched.
- Placement on the full history: 7,305 orders fit their table, 3,134 a combination, 630 a whole room, 150 nothing (bar 8,087 and untabled 1,658 not assessed). 7 implausible guest counts.

### Findings
- **Floor plan corrected with Shane's answers:** E4 and E5 were 2-seaters in the old layout (E4+E5 seats 4; old Evangeline room 10); BD3+BD4+BD5 was a combination (7 seats); the old BD1+BD2 seated 6 (a party of 6 sat there on 11/22/25); old Black Duck room 13. Placement now: 7,370 table, 3,491 combination, 216 whole room, 142 nothing fits. The layout change dates stay inferred; Shane confirms the changes, not when. Open Lounge oversized parties left as `over_capacity` for now.
- **Missing combinations, by which tables sat empty during the oversized parties:** E4/E5 parties averaged 4 guests with the other one free 94-96% of the time (so E4+E5 seated ~4, not 2); BD4 parties averaged 6.3 with BD3 and BD5 free 81-85% but BD2 only 13% (suggests BD3+BD4+BD5); old-layout BD2 parties of 6-8 had BD1 free 95% (BD1+BD2 seated more than 5). Open Lounge has 108 orders too big for their pair, mostly O1 and O8 with 6-10 guests next to a free partner, and 38 parties averaging 9 guests. Awaiting Shane.
- **The floor plan doesn't match the "single seater" description of E4, E5 and BD4.** E5 seated 4 guests on 113 of 205 orders and E4 on 37 of 88; each was busy at the same time as E1/E2/E3 on 50-68% of its orders but at the same time as the other only 7-16%. BD4 averaged 6.1 guests (30 orders of 8) and was busy alongside BD2 on 84% of its orders. Evangeline also changed shape around Nov 24, 2025: E3 went from 2.1 to 5.3 average guests.
- **Parties larger than any listed combination:** Black Duck has 15-20 guest orders (~$600-1,900) rung on BD1/BD2/BD3/BD4/BD5, which look like whole-room events; E1 and E3 have 10-12 guest orders. A handful of guest counts are implausible (101 at B12, 91 at B1 and O10, 70 at B11, 50 at B1 for $0).

## 2026-10-01

### Added
- **Staging layer** (`sql/005_staging.sql`): views `staging.orders` and `staging.item_selections`, one row per Order Id / Item Selection Id (copy from the most recent load wins; `copies_in_raw` says how many there were). Types converted (IDs bigint, money numeric, Toast timestamps parsed without time-zone dependence, durations to intervals), blanks to NULL, `Checks` to an int array, `service_date` with the 4 am cutoff. D009: `is_long_session` (duration strictly over 6 h), `is_negative_duration`, and `duration_usable` for time metrics. Views, not tables, so a rule change is re-running the file (D010).
- `tests/test_staging.py`: edge cases (12 AM, 4 am cutoff, 6:00:00 vs 6:00:01, negative and blank durations, newest-load-wins, both item layouts) and invariants on the real exports (one row per ID, every timestamp parses, item Net Price reconciles to Amount, Total = Amount + Tax + Tip + Gratuity).
- Aug 31, 2025 item export loaded; every order with a nonzero Amount now has item rows.

### Findings
- 20,964 orders (Apr 25, 2025 - Sep 29, 2026), 106,241 item selections. Durations: 448 over 6 h (113 over 24 h), 9 negative (all $0 untabled morning tickets closed weeks later), 6 blank; 20,501 usable.
- `Gross Price` is a unit price: Gross x Qty - Discount = Net on 94,281 item rows; the other 2,815 are items split across checks (Net = half). Net Price is the figure that reconciles. Qty can be 0.5 (half pours).
- **The floor plan changed:** `E4`/`E5` were last used 2025-11-23 and `BD4` 2026-02-13, so table-to-unit mapping needs dates (D007).

## 2026-09-30

### Added
- **Phase 1 raw layer** (nothing in the existing pipeline changed): `docker-compose.yml` (PostgreSQL 16, password from `.env`), `sql/001_schemas.sql` (`raw`/`staging`/`analytics`), `sql/002_raw_tables.sql` (`raw.load_log`, `raw.order_details_a`, `raw.order_details_b`), `load_raw.py`, and `tests/test_raw_load.py`. Every source column is stored as text under its original name, with `load_id`, `source_file` and `source_row_number` (physical line, header = 1). A file whose SHA256 is already in `raw.load_log` is skipped; otherwise the log row and all data rows commit in one transaction.
- `docs/column_inventory.md`: audit of the raw exports (two column layouts, no order ID, key collisions).

- **Exports with Toast IDs** (`sql/003_raw_tables_with_ids.sql`): `raw.order_details_c` (OrderDetails with Order Id / Order # / Checks) and `raw.item_selection_details_a` (ItemSelectionDetails: Order Id, Check Id, Item Selection Id, Table, Gross/Net Price, Qty, Void?). `load_raw.py` reads UTF-8 and falls back to Windows-1252 (ItemSelectionDetails is cp1252). Existing databases need 003 applied by hand; only a fresh volume runs it automatically.

- `sql/004_raw_item_selection_details_b.sql`: ItemSelectionDetails layout without the always-blank `Service` column, which is what the 2026 re-export uses (`item_selection_details_a`, with Service, is now unused). `load_raw.py` and its tests cover it.

### Fixed
- `load_raw.py` numbered a record by the line it *ended* on, so a record whose quoted cell contains a line break (one menu item name in the July 2025 item file, line 153) got the wrong `source_row_number`. It now records the line the record starts on. The row-count and trace tests now work on parsed records rather than physical lines, and a test covers the multi-line case. The dev database was rebuilt from scratch.

### Findings
- **Full history loaded (Apr 25, 2025 - Sep 30, 2026; 25 files, 128,682 rows):** 21,161 order rows = 20,964 distinct Order Ids; 107,521 item rows = 106,059 distinct Item Selection Ids. Repeated copies are all identical. Non-void item Net Price equals Amount on all 19,801 orders that have items. **Gap:** the August 2025 item file is named `08_01-08_30`, so Aug 31, 2025 has 38 orders ($3,606) with no item rows; that day needs an item pull. Three other oddities are harmless: two $0 orders with no items (2026-04-27, 2026-08-10) and one $250 "Open Food" item sent 12/15/25 on an order opened 12/4/25.
- **Full 2026 re-export (Jan 1 - Sep 30), loaded into raw:** 9,985 order rows = 9,923 distinct Order Ids; 53,033 item rows = 51,571 distinct Item Selection Ids. Every repeat comes from two adjacent files both containing their shared boundary date, and every repeated pair is identical, so staging can keep one copy per ID. After that, non-void item Net Price sums to Amount on all 9,508 orders that have items; the 342 orders with no items are all $0. The one item order missing from OrderDetails was opened 9/30 4:17 PM, after the Order Details pull. Service days with no orders are Mondays plus a few holidays/closures (1/25-26, 2/22-23, 4/5-6, 7/4), the same gaps the old merge report showed, so no sign of a missing export.
- On the Jun 30 - Sep 30 OrderDetails pull, Order Id is unique (3,219 of 3,219 rows); on the August ItemSelectionDetails pull, Item Selection Id is unique (5,312 of 5,312) and every item's Order Id is in OrderDetails. Per order, non-void Net Price sums to Amount exactly (1,051 of 1,051). `Order #` resets daily and is not a key. `Checks` in OrderDetails is a list of check numbers, not the Check Id. Identical item rows in one order are real repeat orders, not duplicates.

### Methodology
- Raw keeps exact duplicate rows and blank cells (as empty strings). The one thing not stored is a line identical to the header (the 01_15 export repeats it at line 3522); its line number is simply skipped.

## 2026-08-26

### Added
- **`merge_exports.py`** — merges every Toast pull in `data/exports/` into one continuous dataset at `data/orders_merged.csv`, so pulling a fresh export extends the analysis instead of replacing it. `artemis.load_orders()` with no argument reads the merged file and rebuilds it whenever the exports on disk have changed; a manifest sidecar (`orders_merged.meta.json`) is what makes that staleness check cheap. Run it directly (`--dry-run` reports without writing) for the merge report: per-pull accounting, service-day coverage, gaps of 2+ consecutive days, and any days left with no duration data.
- The three existing exports moved from the project root into `data/exports/`.

### Methodology
- **Schema drift between pulls is reconciled rather than ignored.** The January export carries `Total` and `Duration (Opened to Paid)`; the two earlier ones carry `Tax` and no duration — so neither older file could be loaded at all before. `Total = Amount + Tax + Tip + Gratuity` holds exactly on every overlapping row, so whichever is missing is derived. Duration cannot be reconstructed (`Closed` is a batch close-out, not guest departure) and stays null; those rows drop out of the turn-gap and occupancy layers on their own, and both the merge report and `load_orders`' summary now say how many.
- **Orders are amended after service, so rows are matched on identity, not content.** One 5 June check appears as Tip $23.70 / closed 9:02pm in the May pull and Tip $47.38 / closed the next evening in the July one. Content-based deduplication would have kept both and double-counted it. Identity is `Opened` + `Table` + `# of Guests` — the fields Toast doesn't revise — and the newest pull wins field by field, with any field it doesn't carry falling back to the value an earlier pull supplied. That fallback is what keeps `Duration` intact if the Toast report is ever reconfigured without that column.
- **Split checks are preserved.** ~0.7% of rows share an identity — separate checks rung the same minute at the same table, up to three deep — and are distinguished by an occurrence index ordered by check size, so they survive the merge separately and still match their own earlier versions.
- Pull recency comes from the date range in the filename, with file mtime as a tiebreak.

### Changed
- `verify_artemis.py` no longer asserts a hardcoded `EXPECTED_ROWS = 6233`, which would have failed on every future pull. In its place are four merge invariants that hold at any dataset size: no order appears twice, the file agrees with its manifest, the merged set is current with the exports on disk, no export's orders go missing, and revenue on single-source dates is conserved.
- `report_figures.py` and the notebook's load cell default to the merged dataset. `report_figures.py` still accepts a path to read one raw export.

### Verified
- The merge is a no-op on the current data: 6,609 merged rows and 6,233 after cleaning, identical to what the single January export produced, and `report_figures.py` output is byte-for-byte unchanged.
- Adding a simulated later pull (447 already-known rows including one amended, plus 708 new nights) grows the merged set by exactly 708, resolves the amendment to the new value, and leaves all 18 checks passing. A simulated pull with the duration column dropped leaves duration coverage untouched at 6,600 rows.

## 2026-08-06 (Phase 3)

### Added
- **`weather.py`** — daily Ronkonkoma observations from Open-Meteo's historical archive, cached to `weather_cache.csv` (gitignored) so the notebook runs offline after the first execution. Includes a holiday calendar weighted to what a bar notices (Valentine's, Mother's/Father's Day) rather than the federal list. Handles the macOS SSL-root problem explicitly: prefers `certifi`, falls back to extracting system keychain roots, and raises an actionable error if neither works.
- **"Revenue by Time of Day" notebook section** — hourly demand curves per day of week, the opening-hours break-even, weather and holiday effects, and the seasonality analysis.
- Phase 3 figures added to `report_figures.py`.

### Findings
- **The week splits into three businesses.** Fri/Sat take $7,318/$8,149 and run past 1am. Tue–Thu take $2,154–3,287 and are done by 11. Sunday is an afternoon trade — 25% of takings between 4 and 6pm, dead after 11.
- **Opening hours, as a break-even rather than a recommendation** (labour cost isn't in the data): the 4–5pm hour earns $46 Tue / $64 Wed / $77 Thu, against $403 Sat. The midnight hour earns $20 Tue / $42 Wed / $11 Sun against $494 Fri / $612 Sat. Suggests opening at 5pm Tue–Thu, closing at midnight Tue/Wed/Sun, and leaving Fri/Sat untouched.
- **Rain has no effect** — wet Fri/Sat $7,592 vs dry $7,903, inside the noise.
- **July 4th was the only dark Saturday in six months**, on the highest-earning day of the week.

### Methodology
- **The decline-or-seasonality question cannot be answered from this window, and the notebook now demonstrates why rather than asserting it.** Elapsed time and temperature correlate at r = +0.901 over Jan–Jul; time-only R² = 0.858, temperature-only 0.861, both 0.861. Adding either to the other gains ≈0. The discriminating within-month test is too weak to break the tie (pooled r = −0.221, sign flips between months on 6–10 nights each).
- Reported as a bound instead: flat if entirely seasonal, −$57/night per week elapsed if none of it is. **The fix is last year's Toast export** — an existing report, no new permission — which is now the first ask in the owner report, ahead of Tock.
- The Fri/Sat temperature correlation of −0.719 is presented **with** that caveat rather than as a finding, since it is inseparable from the time trend.

### Fixed
- Whole-night totals in the break-even table were computed from the chart-clipped 15:00–26:00 window, dropping ~$924 of early-afternoon seatings across six months. Now computed from the unclipped hourly data; the notebook and `report_figures.py` agree exactly (Fri $7,318, Sat $8,149, Sun $2,735).

## 2026-08-06 (Step 3)

### Added
- **`owner_report.html`** — the owner-facing deliverable. Covers the three original questions, the four seating/pricing questions from the bar visit, the floor-plan correction, the footfall trend, and the Tock access request. Written as a plain report rather than a dashboard, at the operator's request.
- **`report_figures.py`** — recomputes every figure quoted in the report, labelled and in document order, so a newer export can be reflected without re-deriving anything by hand. Deliberately not a page generator: the report's prose is the substance and templating it would make it worse.

### Note
- The report is deliberately hand-written. `report_figures.py` is the guard against it going stale — run it whenever the underlying export changes and reconcile the numbers.

## 2026-08-06 (Step 2)

### Added
- **"The Owner's Questions" notebook section** — each of the operator's seven written questions answered from the data, with a summary of all seven at the end.
- **Event-pricing analysis.** Values a 3-hour private-event block against what that section earns in its best three hours of ordinary service, by day of week, via a rolling 12-slot sum over the occupancy timeline. Cross-checked against whole-night section revenue (asserted in-cell).

### Changed
- `test.ipynb` → **`analysis.ipynb`**. It was never a test — `verify_artemis.py` is the test suite — and the old name was misleading. Renamed with `git mv` so history follows; references updated in `README.md` and `artemis.py`.

### Findings
- **Both event rates are well priced.** $1,200 (Black Duck) beats the section's best 3-hour block on 99% of nights (median $616); $900 (Evangeline) likewise (median $581). Two refinements: the midweek premium is far larger than the weekend one (~$830 on a Tuesday vs ~$458 on a Saturday), and Black Duck's best-ever 3-hour block of $1,440 exceeds the $1,200 price, so peak weekends are slightly underpriced.
- **E3 should seat parties of 4.** A 5-or-6 party finds E3 held by a smaller party about once every five nights, and in every observed case was still seated — both Black Duck banquettes take that size too.
- **BD1&2 already seat 5s, correctly.** They are one 6-seat banquette, so a five needs no combining; 30 such parties, $115/table-hour. Both banquettes are idle for ~half of peak hours.
- **The reservation allowance is not binding.** 43–56% of every party size runs past it, but the room was >75% full during only 5% of those overstays. On weighting larger parties in 15-minute intervals: TPCPM already does this by construction.

## 2026-08-06 (later)

### Added
- **`SEATING_UNITS`** in `artemis.py` — models the real physical furniture rather than POS codes. Black Duck is a 6-seat (`BD1`+`BD2`) and an 8-seat (`BD3`+`BD5`) banquette; Evangeline is a 2+2 pair plus `E3`; the Open Lounge has four combo pairs plus two standalone tables. New `Seating_Unit` / `Unit_Capacity` columns, and `section_seats()` / `section_units()` helpers.
- Seat-total and partner-free invariants in `verify_artemis.py` (14 checks, all passing).

### Changed
- **`Likely_Combined_Booking` now measures against whole-unit capacity** instead of per-code capacity. The old per-code definition is retained as `Exceeds_Solo_Capacity` so the difference stays measurable rather than silent.
- **Black Duck capacities corrected**: `BD1` 2 → 3-4 and `BD5` 2 → 4-5, giving the section its real 14 seats instead of 11. Cross-referenced against Tock. Open Lounge and Evangeline per-code capacities were already correct and are unchanged.
- The VPCPM/TPCPM section summary now covers party sizes up to 8 in Black Duck (previously 1-4), because whole-banquette bookings are no longer misclassified as combined bookings and excluded. LOOCV-selected `k` values shifted accordingly (Black Duck VPCPM 50 → 20, TPCPM 8 → 2).

### Findings
- **The combined-booking problem was mostly a measurement error.** Flag rate falls from 49% → 9% (Black Duck), 27% → 7% (Evangeline), 27% → 1% (Open Lounge). Guest counts had been compared against half a banquette. What remains — ~108 rows, ~$41K, median 8 guests — genuinely spans units and is still unrecoverable from Toast.
- **The banquette pairings are independently confirmed by the data.** When a code hosts a party too large for its own half, its partner is free 92-100% of the time versus 20-66% for small parties; non-adjacent control pairs show no effect.

### Retracted
- **"`E3` is the only table seating 5+, and 75% of large parties are seated ad hoc"** — an artifact of the pre-banquette capacity model. Corrected: **81% of parties of 5+ fit entirely within one physical unit**, and 30 of 46 reservation seats sit in units taking five or more. The floor plan serves this segment well. Notebook, README and the prior changelog entry updated.

## 2026-08-06

### Added
- **"Turn Times & Table Utilization" notebook section** — gap distribution by section/day/hour, per-table ranking, the gap-vs-room-fullness test, three sizing scenarios, unsold-time decomposition, party-size economics, and the large-party floor-plan analysis.

### Findings
- **The turn-time hypothesis was wrong.** Idle time between parties is not a recoverable lever: gaps collapse from a 65-min median when the room is under a quarter full to 24 min when it is over three quarters full, which is the signature of missing demand rather than slow operations. The room never once reached full occupancy in six months (median utilization while open: 29%). Honest value of faster turning is **~$9K/yr**, not the $156K a naive every-minute-sells calculation produces. Turn gaps are 9.4% of unsold table time; 90.6% is tables that never got a party.
- **No individual table is chronically badly turned** — 13-minute spread across 17 tables. `BD3`'s 296-minute Friday was a single bad night, not a pattern; its median gap is average.
- **Party-size steering is not actionable** — only 1.3% of seatings put a small party at a larger table while the room was busy enough for it to matter.
- **Floor plan versus demand mix** — parties of 5+ are 15.6% of seatings and 30% of section revenue, but only `E3` seats one without combining tables. 75% of that segment is seated ad hoc, which is the root cause of the scale of the `Likely_Combined_Booking` issue.
- **The decline is footfall, not mix** — parties/night fell ~26 → ~18 while average party size held. Six months cannot separate this from seasonality.

### Fixed
- Large-party blocking analysis initially counted parties seated *at* `E3` as blocked by `E3`, since a party occupies its own table in its own arrival slot. Corrected to exclude them: of the 405 5+ parties seated elsewhere, `E3` was occupied for 186 and free for 219.

## 2026-08-04

### Added
- **`artemis.py`** — the loading/cleaning pipeline moved out of the notebook into a shared module, so the notebook and any report generator use one copy. Cleaning rules are unchanged; `CAPACITY_RANGES` and `get_section` now live there as the single source of truth.
- **Time layer** (`add_service_day`, `add_turn_gaps`, `build_occupancy`, `utilization_by_slot`) — reconstructs which tables were occupied in each 15-minute slot and how long each table sat empty between parties. Everything the per-order metrics structurally could not see: on 2026-02-13, the highest-revenue Friday in the dataset, BD3 sat empty for 296 consecutive minutes between two otherwise healthy-looking checks.
- **`Order_Type`** (`Seated` / `Event-Catering` / `To-Go`) — see Fixed below.
- **`verify_artemis.py`** — runnable invariant checks (row count, service-day boundary, occupancy bounds, turn-gap reconciliation).
- Full timestamps preserved as `Opened_DT` / `Closed_DT` / `Paid_DT`. The display cells overwrite `Opened`/`Closed` with time-only strings, which previously destroyed the date and made any time-of-night analysis impossible.

### Fixed
- **Orders were dated by calendar date, not by service night.** Friday business running past midnight was filed under Saturday. Reattributing it moved 86 orders onto Friday and 82 off Sunday, and explained the 21 "Monday" orders at a bar that closes Mondays — 18 of the 19 that remain have no table at all (catering and pickups rung in on a closed day; exactly one seated order in six months). **This changes previously-reported day-of-week revenue numbers.**
- **~$104K of untabled revenue was disappearing silently** through the `Duration >= 15` floor — 10.7% of all revenue in event/catering bookings plus 2.4% in to-go. Now classified via `Order_Type` and reported rather than dropped. Still excluded from per-seat VPCPM/TPCPM, which is correct: nobody was seated.
- Nine event/catering rows have no duration at all; they now get a null `Paid_DT` instead of triggering a pandas NaT-cast warning.

### Verified
- The shrinkage-weighted section summary is **numerically identical** before and after the refactor, as are the LOOCV-selected `k` values, TPCPM-by-section, combined-booking, and Bar reference tables. The only output changes are row-index renumbering (`reset_index`) and the two cells whose content was intentionally replaced.

## 2026-07-28

### Fixed
- **Duration was computed from raw `Closed - Opened` timestamps instead of Toast's own `Duration (Opened to Paid)` column**, and was systematically inflated as a result (median 128 min vs. the real 83 min) — `Closed` often reflects a late/batch POS close-out, not actual guest departure. Since VPCPM/TPCPM both divide by `Duration`, roughly 31% of rows had a "true" VPCPM more than 2x higher than what was previously reported. Switched to parsing `Duration (Opened to Paid)` directly.
- **Untabled "Unknown/To-Go" orders were polluting the headline party-size chart** (e.g. a $7,000 event miscoded as a 1-guest order with a 66-second duration, landing in the party-size-1 bucket). These are now excluded from the pooled chart via a `seated_df` filter; they were already correctly excluded from every section-level analysis further down.
- **TPCPM shrinkage was reusing the LOOCV `k` tuned on `LogVPCPM`**, even though TPCPM has its own skew/variance structure and was never log-transformed. Added a `LogTPCPM` column and a separate LOOCV-selected `k` per section for TPCPM (values now genuinely diverge from VPCPM's, e.g. Black Duck: VPCPM k=50 vs. TPCPM k=8, confirming the shared-k assumption was wrong).

### Added
- `Thin Sample` flag (Orders < 10) on the section summary and Bar reference tables, so a single-order estimate isn't mistaken for a stable one.
- Inline confirmation that `Amount` is already net of any `Discount Amount` (verified against the raw export), resolving a previously-unflagged ambiguity about whether VPCPM/TPCPM are built on gross or realized revenue.

### Removed
- Dead code (`# df['Table'].split()`), the disabled `itables` notebook-init line, and the now-unused `itables` entry in `requirements.txt`.
- Duplicate "Value per Guest based on Party Size" chart (kept the boxplot version, which is a superset of the removed bar+scatter version).

### Docs
- Fixed README reference to a `TABLE_CAPACITY_RANGE` mapping that doesn't exist in the notebook (actual name: `CAPACITY_RANGES`).
- Refreshed stale overbooking percentages (Bar 78%→80%, Black Duck 61%→60%, Evangeline 30%→27%, Open Lounge 28%→27%) to match the current dataset and the duration fix above.
- Restructured README around current status, methodology, and open issues; moved this change history out into this file.
