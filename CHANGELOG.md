# Changelog

All notable changes to the Artemis analysis are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
