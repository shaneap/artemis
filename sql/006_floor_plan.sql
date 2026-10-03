-- Floor plan over time (D007) and the combined-table fix (D010).
--
-- Two hand-maintained reference tables, then a view that decides where each order sat.
-- Re-running this file rewrites the reference rows, so edit the INSERTs and re-run.
--
-- Dates are service dates; valid_from inclusive, valid_to exclusive, NULL = still current.
-- Sources:
--   * Old layout: Toast floor-plan screenshots from 11/23/25 (Shane, 2026-10-03).
--   * Current layout: artemis.py CAPACITY_RANGES / SEATING_UNITS (operator floor notes, Tock).
--   * Change dates are inferred, not known (Shane confirms the changes happened, not when): Evangeline from E4/E5's last use (11/23/25),
--     Black Duck from BD4's last use (2/13/26). Correct them here if Shane finds the real dates.

CREATE TABLE IF NOT EXISTS staging.floor_plan_tables (
    table_code  TEXT    NOT NULL,
    section     TEXT    NOT NULL,      -- Black Duck / Evangeline / Open Lounge / Bar
    seats_min   INTEGER NOT NULL,
    seats_max   INTEGER NOT NULL,      -- 0 = standing placeholder, not a seat
    valid_from  DATE    NOT NULL,
    valid_to    DATE,
    PRIMARY KEY (table_code, valid_from)
);

CREATE TABLE IF NOT EXISTS staging.floor_plan_combinations (
    combination   TEXT      NOT NULL,  -- e.g. 'BD1+BD2', 'Black Duck (whole room)'
    section       TEXT      NOT NULL,
    table_codes   TEXT[]    NOT NULL,
    seats         INTEGER   NOT NULL,
    is_whole_room BOOLEAN   NOT NULL,  -- room buy-out for an event
    valid_from    DATE      NOT NULL,
    valid_to      DATE,
    PRIMARY KEY (combination, valid_from)
);

TRUNCATE staging.floor_plan_tables, staging.floor_plan_combinations;

INSERT INTO staging.floor_plan_tables (table_code, section, seats_min, seats_max, valid_from, valid_to) VALUES
    -- Black Duck, opening layout (screenshot 11/23/25; BD4 last used 2/13/26)
    ('BD1', 'Black Duck', 2, 2, '2025-04-25', '2026-02-14'),
    ('BD2', 'Black Duck', 2, 3, '2025-04-25', '2026-02-14'),
    ('BD3', 'Black Duck', 3, 4, '2025-04-25', '2026-02-14'),
    ('BD4', 'Black Duck', 1, 1, '2025-04-25', '2026-02-14'),
    ('BD5', 'Black Duck', 2, 2, '2025-04-25', '2026-02-14'),
    -- Black Duck, current: BD4 retired
    ('BD1', 'Black Duck', 3, 4, '2026-02-14', NULL),
    ('BD2', 'Black Duck', 2, 3, '2026-02-14', NULL),
    ('BD3', 'Black Duck', 3, 4, '2026-02-14', NULL),
    ('BD5', 'Black Duck', 4, 5, '2026-02-14', NULL),
    -- Evangeline, opening layout (screenshot 11/23/25)
    ('E1', 'Evangeline', 2, 2, '2025-04-25', '2025-11-24'),
    ('E2', 'Evangeline', 2, 2, '2025-04-25', '2025-11-24'),
    ('E3', 'Evangeline', 2, 2, '2025-04-25', '2025-11-24'),
    -- E4/E5 show as 1-seaters in Toast, but their parties averaged 4 with the other one free;
    -- Shane (2026-10-03): "perhaps E4 and E5 were two seaters"
    ('E4', 'Evangeline', 1, 2, '2025-04-25', '2025-11-24'),
    ('E5', 'Evangeline', 1, 2, '2025-04-25', '2025-11-24'),
    -- Evangeline, current: E4/E5 gone, E3 is the large table
    ('E1', 'Evangeline', 2, 2, '2025-11-24', NULL),
    ('E2', 'Evangeline', 2, 2, '2025-11-24', NULL),
    ('E3', 'Evangeline', 5, 6, '2025-11-24', NULL),
    -- Open Lounge: no known change
    ('O1',  'Open Lounge', 3, 3, '2025-04-25', NULL),
    ('O2',  'Open Lounge', 2, 2, '2025-04-25', NULL),
    ('O3',  'Open Lounge', 2, 2, '2025-04-25', NULL),
    ('O4',  'Open Lounge', 2, 2, '2025-04-25', NULL),
    ('O5',  'Open Lounge', 2, 2, '2025-04-25', NULL),
    ('O6',  'Open Lounge', 2, 2, '2025-04-25', NULL),
    ('O7',  'Open Lounge', 2, 2, '2025-04-25', NULL),
    ('O8',  'Open Lounge', 3, 3, '2025-04-25', NULL),
    ('O9',  'Open Lounge', 2, 2, '2025-04-25', NULL),
    ('O10', 'Open Lounge', 2, 2, '2025-04-25', NULL),
    -- Bar: single stools, walk-up; B13/B14 are standing-wait placeholders
    ('B1',  'Bar', 1, 1, '2025-04-25', NULL), ('B2',  'Bar', 1, 1, '2025-04-25', NULL),
    ('B3',  'Bar', 1, 1, '2025-04-25', NULL), ('B4',  'Bar', 1, 1, '2025-04-25', NULL),
    ('B5',  'Bar', 1, 1, '2025-04-25', NULL), ('B6',  'Bar', 1, 1, '2025-04-25', NULL),
    ('B7',  'Bar', 1, 1, '2025-04-25', NULL), ('B8',  'Bar', 1, 1, '2025-04-25', NULL),
    ('B9',  'Bar', 1, 1, '2025-04-25', NULL), ('B10', 'Bar', 1, 1, '2025-04-25', NULL),
    ('B11', 'Bar', 1, 1, '2025-04-25', NULL), ('B12', 'Bar', 1, 1, '2025-04-25', NULL),
    ('B13', 'Bar', 0, 0, '2025-04-25', NULL), ('B14', 'Bar', 0, 0, '2025-04-25', NULL);

-- Combinations Shane listed (2026-10-03), plus whole-room buy-outs for Black Duck and
-- Evangeline. Current seat counts come from artemis.py's banquette units; where no count is
-- known (opening layout) the combination seats the sum of its tables' maximums.
INSERT INTO staging.floor_plan_combinations (combination, section, table_codes, seats, is_whole_room, valid_from, valid_to) VALUES
    -- Black Duck, opening layout
    -- BD1+BD2 seated 6 (a party of 6 sat there on 11/22/25); BD3+BD4+BD5 confirmed by Shane
    ('BD1+BD2', 'Black Duck', '{BD1,BD2}', 6, false, '2025-04-25', '2026-02-14'),
    ('BD3+BD5', 'Black Duck', '{BD3,BD5}', 6, false, '2025-04-25', '2026-02-14'),
    ('BD3+BD4+BD5', 'Black Duck', '{BD3,BD4,BD5}', 7, false, '2025-04-25', '2026-02-14'),
    ('Black Duck (whole room)', 'Black Duck', '{BD1,BD2,BD3,BD4,BD5}', 13, true, '2025-04-25', '2026-02-14'),
    -- Black Duck, current
    ('BD1+BD2', 'Black Duck', '{BD1,BD2}', 6, false, '2026-02-14', NULL),
    ('BD3+BD5', 'Black Duck', '{BD3,BD5}', 8, false, '2026-02-14', NULL),
    ('Black Duck (whole room)', 'Black Duck', '{BD1,BD2,BD3,BD5}', 14, true, '2026-02-14', NULL),
    -- Evangeline, opening layout ("E4 and E5 were often combined to seat a party of 2")
    ('E1+E2',    'Evangeline', '{E1,E2}',    4, false, '2025-04-25', '2025-11-24'),
    ('E1+E2+E3', 'Evangeline', '{E1,E2,E3}', 6, false, '2025-04-25', '2025-11-24'),
    ('E4+E5',    'Evangeline', '{E4,E5}',    4, false, '2025-04-25', '2025-11-24'),
    ('Evangeline (whole room)', 'Evangeline', '{E1,E2,E3,E4,E5}', 10, true, '2025-04-25', '2025-11-24'),
    -- Evangeline, current
    ('E1+E2',    'Evangeline', '{E1,E2}',    4, false, '2025-11-24', NULL),
    ('E1+E2+E3', 'Evangeline', '{E1,E2,E3}', 10, false, '2025-11-24', NULL),
    ('Evangeline (whole room)', 'Evangeline', '{E1,E2,E3}', 10, true, '2025-11-24', NULL),
    -- Open Lounge pairs (O3 and O6 never combine)
    ('O1+O2',  'Open Lounge', '{O1,O2}',  5, false, '2025-04-25', NULL),
    ('O4+O5',  'Open Lounge', '{O4,O5}',  4, false, '2025-04-25', NULL),
    ('O7+O8',  'Open Lounge', '{O7,O8}',  5, false, '2025-04-25', NULL),
    ('O9+O10', 'Open Lounge', '{O9,O10}', 4, false, '2025-04-25', NULL);

-- Guest counts above these are almost certainly typos (e.g. 101 guests on one bar stool).
-- They are flagged, not changed: the order stays, per-guest metrics should skip it.
CREATE OR REPLACE FUNCTION staging.guests_implausible(guests INTEGER, section TEXT)
RETURNS BOOLEAN LANGUAGE sql IMMUTABLE AS $$
    SELECT guests > 30 OR (section = 'Bar' AND guests > 12)
$$;

-- Where each order sat. The fix for "one order, one table code" in Toast: a party bigger than
-- its table is assumed to have used the smallest listed combination (valid on that day) that
-- contains the table and seats the party, then the whole room. Nothing in raw is changed.
--   seating_fit:
--     'table'          party fits the table code alone
--     'combination'    fits a listed combination containing the code
--     'whole_room'     fits only a whole-room buy-out (Black Duck / Evangeline)
--     'over_capacity'  bigger than every option; unit = whole room if there is one
--     'bar'            bar stool or standing placeholder (walk-up; not assessed)
--     'no_table'       no table code (to-go, events rung without a table)
--     'unknown_table'  code not on the floor plan for that day
CREATE OR REPLACE VIEW staging.order_seating AS
SELECT
    o.order_id, o.service_date, o.table_code, o.guests,
    t.section,
    CASE
        WHEN o.table_code IS NULL                    THEN 'no_table'
        WHEN t.table_code IS NULL                    THEN 'unknown_table'
        WHEN t.section = 'Bar'                       THEN 'bar'
        WHEN o.guests <= t.seats_max                 THEN 'table'
        WHEN c.combination IS NOT NULL               THEN 'combination'
        WHEN w.combination IS NOT NULL               THEN 'whole_room'
        ELSE 'over_capacity'
    END                                                   AS seating_fit,
    CASE
        WHEN t.table_code IS NULL OR t.section = 'Bar' THEN NULL
        WHEN o.guests <= t.seats_max                 THEN o.table_code
        ELSE COALESCE(c.combination, w.combination, r.combination)
    END                                                   AS seating_unit,
    CASE
        WHEN t.table_code IS NULL OR t.section = 'Bar' THEN NULL
        WHEN o.guests <= t.seats_max                 THEN t.seats_max
        ELSE COALESCE(c.seats, w.seats, r.seats)
    END                                                   AS unit_seats,
    staging.guests_implausible(o.guests, t.section)       AS guests_implausible
FROM staging.orders o
LEFT JOIN staging.floor_plan_tables t
       ON t.table_code = o.table_code
      AND o.service_date >= t.valid_from AND (t.valid_to IS NULL OR o.service_date < t.valid_to)
LEFT JOIN LATERAL (   -- smallest listed (non-room) combination that seats the party
    SELECT combination, seats FROM staging.floor_plan_combinations fc
    WHERE NOT fc.is_whole_room AND o.table_code = ANY (fc.table_codes) AND fc.seats >= o.guests
      AND o.service_date >= fc.valid_from AND (fc.valid_to IS NULL OR o.service_date < fc.valid_to)
    ORDER BY fc.seats, cardinality(fc.table_codes) LIMIT 1
) c ON true
LEFT JOIN LATERAL (   -- whole room, if it seats the party
    SELECT combination, seats FROM staging.floor_plan_combinations fc
    WHERE fc.is_whole_room AND o.table_code = ANY (fc.table_codes) AND fc.seats >= o.guests
      AND o.service_date >= fc.valid_from AND (fc.valid_to IS NULL OR o.service_date < fc.valid_to)
    LIMIT 1
) w ON true
LEFT JOIN LATERAL (   -- the largest option there is, for parties that fit nothing
    SELECT combination, seats FROM staging.floor_plan_combinations fc
    WHERE o.table_code = ANY (fc.table_codes)
      AND o.service_date >= fc.valid_from AND (fc.valid_to IS NULL OR o.service_date < fc.valid_to)
    ORDER BY fc.seats DESC LIMIT 1
) r ON true;
