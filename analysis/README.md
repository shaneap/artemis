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
