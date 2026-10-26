-- Re-derive staging and analytics from raw after new files are loaded. load_raw.py runs this
-- automatically; by hand:
--   docker compose exec -T db psql -U artemis -d artemis -f - < sql/maintenance/refresh.sql
-- Order matters: each step reads the ones before it.
REFRESH MATERIALIZED VIEW staging.orders;
REFRESH MATERIALIZED VIEW staging.item_selections;
REFRESH MATERIALIZED VIEW staging.order_seating;
REFRESH MATERIALIZED VIEW analytics.dim_date;
REFRESH MATERIALIZED VIEW analytics.dim_seating_unit;
REFRESH MATERIALIZED VIEW analytics.dim_menu_item;
REFRESH MATERIALIZED VIEW analytics.fact_order;
REFRESH MATERIALIZED VIEW analytics.fact_item_selection;
REFRESH MATERIALIZED VIEW analytics.fact_table_occupancy;
ANALYZE;
