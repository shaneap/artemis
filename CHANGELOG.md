# Changelog

All notable changes to the Artemis analysis are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## 2026-09-30

### Added
- **Phase 1 raw layer** (nothing in the existing pipeline changed): `docker-compose.yml` (PostgreSQL 16, password from `.env`), `sql/001_schemas.sql` (`raw`/`staging`/`analytics`), `sql/002_raw_tables.sql` (`raw.load_log`, `raw.order_details_a`, `raw.order_details_b`), `load_raw.py`, and `tests/test_raw_load.py`. Every source column is stored as text under its original name, with `load_id`, `source_file` and `source_row_number` (physical line, header = 1). A file whose SHA256 is already in `raw.load_log` is skipped; otherwise the log row and all data rows commit in one transaction.
- `docs/column_inventory.md`: audit of the raw exports (two column layouts, no order ID, key collisions).

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
