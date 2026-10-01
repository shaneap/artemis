-- Staging layer (D003, D009, D010, D011): one row per Toast ID, typed, with data-quality
-- flags. These are views over raw, so changing a rule here and re-running this file
-- "rebuilds" staging; raw is never touched.
--
-- Which copy wins: Order Id / Item Selection Id repeat across exports (adjacent pulls share
-- their boundary date, and re-pulls repeat everything). The copy from the most recent load
-- (highest load_id) is kept. All repeats seen so far are identical.
--
-- Not done here yet: combined-table fix (D010, rule not defined), table code -> seating
-- unit mapping (D007, floor plan changed over time), order type (Seated / Event / To-Go).

-- Toast writes local wall-clock times as 'M/D/YY H:MM AM'. Parsed into a timestamp with no
-- time zone, independent of the session's TimeZone/DateStyle settings.
CREATE OR REPLACE FUNCTION staging.parse_toast_ts(t TEXT) RETURNS TIMESTAMP
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT make_timestamp(
        2000 + m[3]::int, m[1]::int, m[2]::int,
        (m[4]::int % 12) + CASE WHEN m[6] = 'PM' THEN 12 ELSE 0 END,
        m[5]::int, 0)
    FROM (SELECT regexp_match(t, '^(\d{1,2})/(\d{1,2})/(\d{2}) (\d{1,2}):(\d{2}) (AM|PM)$') AS m) x
    WHERE m IS NOT NULL
$$;

-- 'H:MM:SS' with any number of hours ('147:09:50'). Toast writes negative durations with
-- every part negative ('-378:-17:-58'); those parse to a negative interval.
CREATE OR REPLACE FUNCTION staging.parse_toast_duration(t TEXT) RETURNS INTERVAL
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT make_interval(hours => m[1]::int, mins => m[2]::int, secs => m[3]::int)
    FROM (SELECT regexp_match(t, '^(-?\d+):(-?\d{1,2}):(-?\d{1,2})$') AS m) x
    WHERE m IS NOT NULL
$$;

CREATE OR REPLACE VIEW staging.orders AS
WITH ranked AS (
    SELECT r.*,
           row_number() OVER (PARTITION BY "Order Id" ORDER BY load_id DESC) AS copy_rank,
           count(*)     OVER (PARTITION BY "Order Id")                       AS copies_in_raw
    FROM raw.order_details_c r
), typed AS (
    SELECT
        "Order Id"::bigint                                          AS order_id,
        "Order #"::int                                              AS order_number,
        string_to_array(replace("Checks", ' ', ''), ',')::int[]     AS check_numbers,
        staging.parse_toast_ts("Opened")                            AS opened_at,
        "# of Guests"::int                                          AS guests,
        NULLIF("Table", '')                                         AS table_code,
        "Discount Amount"::numeric(10,2)                            AS discount_amount,
        "Amount"::numeric(10,2)                                     AS amount,   -- net of discounts
        "Tax"::numeric(10,2)                                        AS tax,
        "Tip"::numeric(10,2)                                        AS tip,
        "Gratuity"::numeric(10,2)                                   AS gratuity,
        "Total"::numeric(10,2)                                      AS total,
        staging.parse_toast_ts(NULLIF("Closed", ''))                AS closed_at,  -- batch close-out, not departure
        staging.parse_toast_duration(NULLIF("Duration (Opened to Paid)", '')) AS duration,
        load_id, source_file, source_row_number, copies_in_raw
    FROM ranked
    WHERE copy_rank = 1
)
SELECT
    order_id, order_number, check_numbers, opened_at,
    (opened_at - interval '4 hours')::date                          AS service_date,  -- 4 am cutoff
    guests, table_code, discount_amount, amount, tax, tip, gratuity, total,
    closed_at, duration,
    round(extract(epoch FROM duration) / 60, 2)                     AS duration_minutes,
    duration > interval '6 hours'                                   AS is_long_session,      -- D009
    duration < interval '0'                                         AS is_negative_duration,
    -- usable for time-based metrics (VPCPM, TPCPM, turn gaps, occupancy)
    COALESCE(duration >= interval '0' AND duration <= interval '6 hours', false)
                                                                    AS duration_usable,
    load_id, source_file, source_row_number, copies_in_raw
FROM typed;

CREATE OR REPLACE VIEW staging.item_selections AS
WITH unioned AS (
    -- both ItemSelectionDetails layouts; the _a layout's extra "Service" column was always blank
    SELECT load_id, source_file, source_row_number, "Order Id", "Order #", "Sent Date",
           "Order Date", "Check Id", "Table", "Dining Area", "Item Selection Id", "Menu Item",
           "Menu Group", "Menu", "Sales Category", "Gross Price", "Discount", "Net Price",
           "Qty", "Void?"
    FROM raw.item_selection_details_a
    UNION ALL
    SELECT load_id, source_file, source_row_number, "Order Id", "Order #", "Sent Date",
           "Order Date", "Check Id", "Table", "Dining Area", "Item Selection Id", "Menu Item",
           "Menu Group", "Menu", "Sales Category", "Gross Price", "Discount", "Net Price",
           "Qty", "Void?"
    FROM raw.item_selection_details_b
), ranked AS (
    SELECT u.*,
           row_number() OVER (PARTITION BY "Item Selection Id" ORDER BY load_id DESC) AS copy_rank,
           count(*)     OVER (PARTITION BY "Item Selection Id")                       AS copies_in_raw
    FROM unioned u
)
SELECT
    "Item Selection Id"::bigint                 AS item_selection_id,
    "Order Id"::bigint                          AS order_id,
    "Check Id"::bigint                          AS check_id,
    "Order #"::int                              AS order_number,
    staging.parse_toast_ts("Order Date")        AS ordered_at,
    staging.parse_toast_ts("Sent Date")         AS sent_at,
    NULLIF("Table", '')                         AS table_code,
    NULLIF("Dining Area", '')                   AS dining_area,
    "Menu Item"                                 AS menu_item,
    NULLIF("Menu Group", '')                    AS menu_group,
    NULLIF("Menu", '')                          AS menu,
    NULLIF("Sales Category", '')                AS sales_category,
    "Gross Price"::numeric(10,2)                AS gross_price,  -- unit price
    "Discount"::numeric(10,2)                   AS discount,
    "Net Price"::numeric(10,2)                  AS net_price,    -- line total; sums to orders.amount
    "Qty"::numeric(6,2)                         AS qty,          -- can be fractional (0.5 pours)
    "Void?" = 'true'                            AS is_void,
    load_id, source_file, source_row_number, copies_in_raw
FROM ranked
WHERE copy_rank = 1;
