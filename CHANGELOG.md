# Changelog

All notable changes to the Artemis analysis are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
