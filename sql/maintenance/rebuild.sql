-- Re-create staging and analytics after changing a rule in sql/005-007 (e.g. the floor plan).
-- Raw is untouched. The sql/ folder is mounted in the container, so:
--   docker compose exec -T db psql -U artemis -d artemis -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/maintenance/rebuild.sql
\ir ../005_staging.sql
\ir ../006_floor_plan.sql
\ir ../007_analytics.sql
ANALYZE;
