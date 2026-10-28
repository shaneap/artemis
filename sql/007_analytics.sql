-- Analytics layer (D003): a small star schema built from staging.
--
--   dim_date            one row per service date
--   dim_seating_unit    tables, combinations and whole rooms, per layout period (D007)
--   dim_menu_item       one row per menu item per price version (D006, Type 2)
--   fact_order          one row per order: money, guests, duration, seating, order type,
--                       and the per-order spend-per-time metrics (VPCPM / TPCPM)
--   fact_item_selection one row per item selection on a check (D002 grain)
--   fact_table_occupancy one row per seated party per table it occupied, borrowed tables included
--
-- Materialized views, refreshed after every load (load_raw.py runs sql/maintenance/refresh.sql).
-- Surrogate keys are assigned in a fixed order on each refresh; facts are refreshed after
-- dims, so keys always agree.

DROP MATERIALIZED VIEW IF EXISTS analytics.fact_table_occupancy, analytics.fact_item_selection, analytics.fact_order,
    analytics.dim_menu_item, analytics.dim_seating_unit, analytics.dim_date;

-- Old pipeline rules, carried over unchanged (artemis.py):
CREATE OR REPLACE FUNCTION analytics.event_amount_threshold() RETURNS NUMERIC
LANGUAGE sql IMMUTABLE AS $$ SELECT 400::numeric $$;      -- untabled check >= this = event/catering
CREATE OR REPLACE FUNCTION analytics.duration_floor_minutes() RETURNS NUMERIC
LANGUAGE sql IMMUTABLE AS $$ SELECT 15::numeric $$;       -- shorter visits left out of VPCPM/TPCPM


CREATE MATERIALIZED VIEW analytics.dim_date AS
SELECT
    to_char(d, 'YYYYMMDD')::int             AS date_key,
    d::date                                 AS service_date,
    to_char(d, 'FMDay')                     AS day_name,
    extract(isodow FROM d)::int             AS iso_day_of_week,   -- 1 = Monday
    extract(isodow FROM d) IN (5, 6)        AS is_fri_or_sat,
    date_trunc('week', d)::date             AS week_start,        -- Monday
    date_trunc('month', d)::date            AS month_start,
    extract(year FROM d)::int               AS year
FROM generate_series(
        (SELECT COALESCE(min(service_date), current_date) FROM staging.orders),
        (SELECT COALESCE(max(service_date), current_date) FROM staging.orders),
        interval '1 day') AS d;

CREATE UNIQUE INDEX ON analytics.dim_date (date_key);


CREATE MATERIALIZED VIEW analytics.dim_seating_unit AS
WITH units AS (
    SELECT table_code AS unit_name, section, ARRAY[table_code] AS table_codes,
           seats_max AS seats,
           CASE WHEN section = 'Bar' THEN 'bar' ELSE 'table' END AS unit_type,
           valid_from, valid_to
    FROM staging.floor_plan_tables
    UNION ALL
    SELECT combination, section, table_codes, seats,
           CASE WHEN is_whole_room THEN 'whole_room' ELSE 'combination' END,
           valid_from, valid_to
    FROM staging.floor_plan_combinations
)
SELECT row_number() OVER (ORDER BY section, unit_name, valid_from)::int AS seating_unit_key,
       unit_name, unit_type, section, table_codes, seats, valid_from, valid_to,
       valid_to IS NULL AS is_current
FROM units;

CREATE UNIQUE INDEX ON analytics.dim_seating_unit (seating_unit_key);


-- Menu item price versions (Type 2). Toast doesn't export the menu's price list, so the list
-- price is inferred from what was rung:
--   * "clean" selections only: not void, Qty 1, positive price, not split across checks
--     (doubles, upcharges, splits and comps would otherwise look like price changes);
--   * a month sets the price when one price is more than half of that month's clean sales
--     (and there are at least 3); months where prices are mixed (e.g. well vs. call pours rung
--     under one name) don't move the price;
--   * a new version starts on the first clean sale at the new price;
--   * an item that never has such a month gets one version at its overall dominant clean price
--     (again more than half of its clean sales), else no list price (open-price items like
--     Locker, Open Food).
-- The item's identity is its name: Toast's Item Id was not exported.
CREATE MATERIALIZED VIEW analytics.dim_menu_item AS
WITH items AS MATERIALIZED (
    SELECT menu_item, menu_group, menu, sales_category, gross_price, discount, net_price,
           qty, is_void, sent_at, (sent_at - interval '4 hours')::date AS sday
    FROM staging.item_selections
), clean AS (
    SELECT menu_item, gross_price, sent_at, date_trunc('month', sent_at)::date AS month
    FROM items
    WHERE NOT is_void AND qty = 1 AND gross_price > 0 AND net_price = gross_price - discount
), price_counts AS (
    SELECT menu_item, month, gross_price, count(*) AS n,
           sum(count(*)) OVER (PARTITION BY menu_item, month) AS month_n
    FROM clean GROUP BY 1, 2, 3
), established AS (       -- months with a dominant price
    SELECT menu_item, month, gross_price AS price
    FROM price_counts WHERE month_n >= 3 AND n * 2 > month_n
), overall AS (           -- fallback: dominant price over the item's whole history
    SELECT menu_item, price FROM (
        SELECT menu_item, gross_price AS price, count(*) AS n,
               sum(count(*)) OVER (PARTITION BY menu_item) AS total_n,
               row_number() OVER (PARTITION BY menu_item ORDER BY count(*) DESC, gross_price) AS rk
        FROM clean GROUP BY 1, 2) x
    WHERE rk = 1 AND n * 2 > total_n
), changes AS (          -- months where the established price differs from the one before
    SELECT menu_item, month, price FROM (
        SELECT *, lag(price) OVER (PARTITION BY menu_item ORDER BY month) AS prev
        FROM established) e
    WHERE prev IS DISTINCT FROM price
), starts AS (           -- each version starts at its first clean sale at that price, that month
    SELECT ch.menu_item, ch.price, min(c.sent_at) AS first_sale
    FROM changes ch
    JOIN clean c ON c.menu_item = ch.menu_item AND c.month = ch.month AND c.gross_price = ch.price
    GROUP BY ch.menu_item, ch.price, ch.month
), first_seen AS (
    SELECT menu_item, min(sent_at) AS first_sale FROM items GROUP BY 1
), versions AS (
    -- the first version of every item starts when the item first appears at all
    SELECT s.menu_item, s.price,
           CASE WHEN row_number() OVER (PARTITION BY s.menu_item ORDER BY s.first_sale) = 1
                THEN f.first_sale ELSE s.first_sale END AS valid_from_ts
    FROM starts s JOIN first_seen f USING (menu_item)
    UNION ALL
    SELECT f.menu_item, ov.price, f.first_sale
    FROM first_seen f LEFT JOIN overall ov USING (menu_item)
    WHERE NOT EXISTS (SELECT 1 FROM starts s WHERE s.menu_item = f.menu_item)
), dated AS (
    SELECT row_number() OVER () AS vid, * FROM (
        SELECT menu_item, price,
               (valid_from_ts - interval '4 hours')::date AS valid_from,
               (lead(valid_from_ts) OVER (PARTITION BY menu_item ORDER BY valid_from_ts)
                   - interval '4 hours')::date             AS valid_to
        FROM versions) v
    WHERE valid_to IS NULL OR valid_to > valid_from   -- two changes on one service day: keep the later
), described AS (        -- group / menu / category as most often rung during the version
    SELECT d.vid,
           mode() WITHIN GROUP (ORDER BY i.menu_group)     AS menu_group,
           mode() WITHIN GROUP (ORDER BY i.menu)           AS menu,
           mode() WITHIN GROUP (ORDER BY i.sales_category) AS sales_category
    FROM dated d
    JOIN items i ON i.menu_item = d.menu_item AND i.sday >= d.valid_from
                AND (d.valid_to IS NULL OR i.sday < d.valid_to)
    GROUP BY d.vid
)
SELECT row_number() OVER (ORDER BY d.menu_item, d.valid_from)::int AS menu_item_key,
       d.menu_item, x.menu_group, x.menu, x.sales_category,
       d.price AS list_price, d.valid_from, d.valid_to, d.valid_to IS NULL AS is_current
FROM dated d LEFT JOIN described x USING (vid);

CREATE UNIQUE INDEX ON analytics.dim_menu_item (menu_item_key);
CREATE INDEX ON analytics.dim_menu_item (menu_item, valid_from);


CREATE MATERIALIZED VIEW analytics.fact_order AS
SELECT
    o.order_id,
    to_char(o.service_date, 'YYYYMMDD')::int        AS date_key,
    su.seating_unit_key,
    o.table_code,
    COALESCE(s.section, 'No table')                 AS section,
    CASE WHEN o.table_code IS NOT NULL THEN 'Seated'
         WHEN o.amount >= analytics.event_amount_threshold() THEN 'Event-Catering'
         ELSE 'To-Go' END                           AS order_type,
    s.seating_fit,
    o.opened_at,
    o.guests,
    cardinality(o.check_numbers)                    AS checks,
    o.discount_amount, o.amount, o.tax, o.tip, o.gratuity, o.total,
    o.duration_minutes,
    o.is_long_session, o.is_negative_duration, o.duration_usable,
    s.guests_implausible,
    -- usable for spend-per-time metrics: seated, real duration of 15 min to 6 h, real guests
    (o.table_code IS NOT NULL AND o.duration_usable
     AND o.duration_minutes >= analytics.duration_floor_minutes()
     AND o.guests > 0 AND NOT s.guests_implausible) AS in_time_metrics,
    -- VPCPM: spend per guest per 15 minutes; TPCPM: spend per table per 15 minutes
    CASE WHEN o.table_code IS NOT NULL AND o.duration_usable
              AND o.duration_minutes >= analytics.duration_floor_minutes()
              AND o.guests > 0 AND NOT s.guests_implausible
         THEN round((o.amount / o.guests) / (o.duration_minutes / 15), 4) END AS vpcpm,
    CASE WHEN o.table_code IS NOT NULL AND o.duration_usable
              AND o.duration_minutes >= analytics.duration_floor_minutes()
              AND o.guests > 0 AND NOT s.guests_implausible
         THEN round(o.amount / (o.duration_minutes / 15), 4) END AS tpcpm
FROM staging.orders o
JOIN staging.order_seating s USING (order_id)
LEFT JOIN analytics.dim_seating_unit su
       ON su.unit_name = s.seating_unit
      AND o.service_date >= su.valid_from AND (su.valid_to IS NULL OR o.service_date < su.valid_to);

CREATE UNIQUE INDEX ON analytics.fact_order (order_id);
CREATE INDEX ON analytics.fact_order (date_key);


CREATE MATERIALIZED VIEW analytics.fact_item_selection AS
SELECT
    i.item_selection_id,
    i.order_id,
    i.check_id,
    to_char(COALESCE(o.service_date, (i.sent_at - interval '4 hours')::date), 'YYYYMMDD')::int AS date_key,
    m.menu_item_key,
    i.sent_at,
    round(extract(epoch FROM i.sent_at - o.opened_at) / 60, 1) AS minutes_after_open,
    i.qty, i.gross_price, i.discount, i.net_price, i.is_void
FROM staging.item_selections i
LEFT JOIN staging.orders o USING (order_id)
JOIN analytics.dim_menu_item m
  ON m.menu_item = i.menu_item
 AND (i.sent_at - interval '4 hours')::date >= m.valid_from
 AND (m.valid_to IS NULL OR (i.sent_at - interval '4 hours')::date < m.valid_to);

CREATE UNIQUE INDEX ON analytics.fact_item_selection (item_selection_id);
CREATE INDEX ON analytics.fact_item_selection (order_id);
CREATE INDEX ON analytics.fact_item_selection (menu_item_key);


-- Which tables each seated party occupied, and when. Toast rings a party on one table code even
-- when it sat at a banquette or a pushed-together pair, so counting recorded codes alone shows
-- the partner table as free while people sit at it (it made the room look never full).
--
-- Each party occupies its recorded table, plus the other tables of the seating unit
-- staging.order_seating placed it on (combination, whole room, or the largest option for an
-- over-capacity party). A borrowed table is claimed only if no other party was rung on it at
-- any point during the stay: when one was, that table was in separate use, so the large party
-- must have sat some other way (extra chairs) and the table is left to its own party. Two
-- parties can't borrow the same table at once either: a listed combination beats a whole-room or
-- over-capacity guess, then the earlier party keeps it.
-- Implausible guest counts (likely typos) borrow nothing.
--
-- Same parties as the time metrics: reservation sections, usable duration, 15 min floor.
-- The stay is Toast's opened-to-paid time, so seating before the first ring and lingering after
-- paying are not counted; both make real occupancy a little higher than this.
CREATE MATERIALIZED VIEW analytics.fact_table_occupancy AS
WITH stays AS (
    SELECT o.order_id, o.service_date, o.table_code, s.section, s.seating_fit, s.seating_unit,
           s.guests_implausible,
           o.opened_at                AS start_at,
           o.opened_at + o.duration   AS end_at
    FROM staging.orders o
    JOIN staging.order_seating s USING (order_id)
    WHERE s.section IN ('Black Duck', 'Evangeline', 'Open Lounge')
      AND o.duration_usable
      AND o.duration_minutes >= analytics.duration_floor_minutes()
),
candidates AS (
    SELECT st.*, t.table_code AS occupied_code
    FROM stays st
    CROSS JOIN LATERAL (
        SELECT st.table_code
        UNION
        SELECT unnest(fc.table_codes)
        FROM staging.floor_plan_combinations fc
        WHERE fc.combination = st.seating_unit
          AND NOT st.guests_implausible
          AND st.service_date >= fc.valid_from
          AND (fc.valid_to IS NULL OR st.service_date < fc.valid_to)
    ) t(table_code)
),
claims AS (   -- recorded tables, and borrowed tables no party was rung on during the stay
    SELECT c.*,
           CASE c.seating_fit WHEN 'combination' THEN 1 WHEN 'whole_room' THEN 2 ELSE 3 END AS fit_rank
    FROM candidates c
    WHERE c.occupied_code = c.table_code
       OR NOT EXISTS (
            SELECT 1 FROM stays o2
            WHERE o2.table_code = c.occupied_code
              AND o2.service_date = c.service_date
              AND o2.order_id <> c.order_id
              AND o2.start_at < c.end_at AND o2.end_at > c.start_at)
)
SELECT
    c.order_id,
    to_char(c.service_date, 'YYYYMMDD')::int    AS date_key,
    c.service_date,
    c.occupied_code                             AS table_code,
    c.section,
    c.occupied_code = c.table_code              AS is_recorded_table,
    c.seating_fit,
    c.start_at,
    c.end_at,
    round(extract(epoch FROM c.end_at - c.start_at) / 60, 2) AS minutes
FROM claims c
WHERE c.occupied_code = c.table_code
   OR NOT EXISTS (   -- another party borrowing the same table at the same time, with priority
        SELECT 1 FROM claims c2
        WHERE c2.occupied_code = c.occupied_code
          AND c2.occupied_code <> c2.table_code
          AND c2.service_date = c.service_date
          AND c2.order_id <> c.order_id
          AND c2.start_at < c.end_at AND c2.end_at > c.start_at
          AND (c2.fit_rank, c2.start_at, c2.order_id) < (c.fit_rank, c.start_at, c.order_id));

CREATE UNIQUE INDEX ON analytics.fact_table_occupancy (order_id, table_code);
CREATE INDEX ON analytics.fact_table_occupancy (service_date, table_code);
