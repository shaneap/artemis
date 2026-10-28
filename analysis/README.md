# Analysis on the warehouse

Scripts that read the `analytics` tables (via `analysis/db.py`) and write a plain-text report
to `analysis/results/<name>.md`. Run from the repo root with Postgres up, e.g.
`python3 analysis/trend.py`. Results are regenerated on each run; the committed copies are the
latest numbers.

| Script | Question |
| --- | --- |
| `trend.py` | Is trade declining, or was the 2026 drop seasonal? (same months 2025 vs 2026; trend net of day of week and season) |
| `hours.py` | What does each hour of the night earn, by night of the week? (opening hours) |
| `menu.py` | What sells, why spend per guest rose, and how menu prices changed |
| `occupancy.py` | How full do the reservation sections get (combined parties occupying every table they used), and what is faster turning worth? |
| `seating_slack.py` | Fri/Sat 6-10pm: could one more party of 2, 4 or 6 have been seated, as the floor was used, by re-seating the same parties, or not at all? (integer program, SciPy/HiGHS; ~10 min) |
