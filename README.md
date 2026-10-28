# Artemis

Analysis of one bar/restaurant's Toast POS order exports (Ronkonkoma, NY), answering the owner's questions on seating, table turns, event pricing, opening hours and revenue trend. Data: Apr 25, 2025 – Sep 29, 2026.

## Repository layout

| Path | What it is |
| --- | --- |
| [`sql/`](sql/), [`load_raw.py`](load_raw.py), [`docker-compose.yml`](docker-compose.yml) | **PostgreSQL warehouse (current).** Raw exports → typed, de-duplicated staging → analytics facts and dimensions. |
| [`analysis/`](analysis/) | Analysis scripts on the warehouse; results in [`analysis/results/`](analysis/results/). See [analysis/README.md](analysis/README.md). |
| [`tests/`](tests/) | Warehouse tests (unittest, scratch databases). |
| [`weather.py`](weather.py) | Daily Ronkonkoma weather (Open-Meteo), cached; holiday calendar. |
| [`legacy/`](legacy/) | The original pandas pipeline and notebook (Jul–Aug 2026). See [legacy/README.md](legacy/README.md). |
| [`docs/`](docs/), [DECISIONS.md](DECISIONS.md), [CHANGELOG.md](CHANGELOG.md) | Export audit, decision log, history. |
| `reports/` | The owner-facing report (private; not in the repo). |

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env                 # set a real password
docker compose up -d                 # PostgreSQL 16; schema built from sql/
python3 load_raw.py                  # load data/exports/*.csv, refresh staging + analytics
python3 -m unittest tests.test_raw_load tests.test_staging tests.test_analytics
python3 analysis/trend.py            # likewise hours.py, menu.py
```

Toast exports (`OrderDetails`, `ItemSelectionDetails`) are not tracked; put them in `data/exports/`.

## Warehouse

- **raw**: files as received, all text, each load logged by SHA-256.
- **staging**: one row per Toast ID (where exports overlap, the one whose date range ends latest wins), typed, dated to a **service day** that cuts at 4 am. Also a dated floor plan, and each party placed on its own table, the smallest combination that seats it, or flagged over capacity.
- **analytics**: `dim_date`, `dim_seating_unit`, `dim_menu_item` (inferred price versions), `fact_order`, `fact_item_selection`, and `fact_table_occupancy` (every table each party occupied, including the partner of a banquette or pair that Toast doesn't record). Aggregation happens in `analysis/`.

## Findings

| Question | Answer |
| --- | --- |
| How full does the room get? | **Fri/Sat peaks run at or near capacity**: 80% of tables in use at 8–10 pm (median), and every table taken at once on about a quarter of weekend nights. Midweek and Sunday are limited by demand (a quarter to a third of table time used). An earlier "never full" finding was wrong; see CHANGELOG 2026-10-26. |
| Turn tables faster / seat 2–3s back to back? | Worth ~$38K/yr (~2.4% of sales) if busy-room tables turned as fast as staff already manage when busy (25 min), nearly 90% of it on Fri/Sat evenings. Gaps shrink as the room fills. |
| Floor plan for large parties? | No problem to solve: 81% of 5+ parties fit one physical unit. |
| Should `E3` seat a 4? `BD1`+`BD2` a 5? | Yes to both. |
| $1,200 (Black Duck) / $900 (Evangeline) event rates? | Well priced; each beats 99% of nights' best 3-hour blocks. |
| Opening hours? | Open 5 pm Tue–Thu; close at midnight Tue/Wed/Sun; leave Fri/Sat alone. A break-even, since the cost of an hour isn't in the data. |
| Decline or seasonality? | **Both.** Winter is the strong season, but May–Sep 2026 vs 2025 is −10% regular revenue/night and −16% parties. Net of day of week and season, parties are falling 14%/yr (95% CI −19% to −8%). Spend per guest is up 8%, mostly menu mix (like-for-like prices +2%). |
| Weather? | Rain has no effect. |

Current numbers: [analysis/results/](analysis/results/) and `python3 legacy/report_figures.py`.

## Metrics and domain notes

- **VPCPM** = (Amount / guests) / (Duration / 15); **TPCPM** = Amount / (Duration / 15). Seated orders only, 15 min–6 h. Averaged as geometric means, with small party sizes shrunk toward their section's mean (`k` by leave-one-out CV).
- **Duration** is Toast's `Duration (Opened to Paid)`, never `Closed − Opened` (Closed is a batch close-out).
- **Order type**: `Seated`, `Event-Catering` (untabled, ≥ $400) or `To-Go`.
- **Sections**: Black Duck (14 seats), Evangeline (10) and Open Lounge (22) take reservations; the Bar (12) is walk-up. A POS table code is not a physical unit: banquettes and table pairs span two codes (e.g. `BD1`+`BD2` is one 6-seat banquette). The floor plan changed on Nov 24, 2025 (Evangeline) and Feb 14, 2026 (Black Duck).
- Mondays are closed except for private bookings and are left out of trend and hours work.

## Known limitations

- **Combined bookings can't be recovered.** Toast ties each order to one table, so ~100 parties (~$41K) that spanned several units can't be placed. They are reported descriptively only; fixing this needs a POS or process change.
- **Occupancy is inferred for combined parties.** Toast records one table; the partner tables come from the floor plan (the smallest combination that seats the party), and are only counted when no other party was rung on them. Toast doesn't record seating before the first order or lingering after payment, so real occupancy is a little higher than measured.
- Turn gaps measure payment to next seating, not table clearing, so lingering, bussing and an empty queue can't be told apart. Toast also can't show parties turned away, so demand at full-room moments is unknown.
- Pending: 95% CIs on the per-section VPCPM/TPCPM summaries; a finer grid for the shrinkage `k`.
