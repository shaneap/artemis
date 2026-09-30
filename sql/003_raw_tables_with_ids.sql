-- Raw tables for the 2026-09-30 exports, which carry Toast's own IDs.
-- Same rules as 002: all TEXT, original column names, blank cell = '', no de-duplication.
-- The same order or item selection can legitimately appear in several pulls, so the ID
-- columns are indexed but NOT unique here; picking the newest copy is a staging job.
--
--   order_details_c           OrderDetails with Order Id, Order #, Checks, Tax, Total, Duration
--   item_selection_details_a  ItemSelectionDetails, one row per item selection (18 columns)

CREATE TABLE raw.order_details_c (
    load_id                     BIGINT  NOT NULL REFERENCES raw.load_log (load_id),
    source_file                 TEXT    NOT NULL,
    source_row_number           INTEGER NOT NULL,  -- physical line in the file, header = 1
    "Order Id"                  TEXT,
    "Order #"                   TEXT,
    "Checks"                    TEXT,              -- list of check numbers, e.g. '9, 16, 17'
    "Opened"                    TEXT,
    "# of Guests"               TEXT,
    "Table"                     TEXT,
    "Discount Amount"           TEXT,
    "Amount"                    TEXT,
    "Tax"                       TEXT,
    "Tip"                       TEXT,
    "Gratuity"                  TEXT,
    "Total"                     TEXT,
    "Closed"                    TEXT,
    "Duration (Opened to Paid)" TEXT,
    PRIMARY KEY (load_id, source_row_number)
);
CREATE INDEX ON raw.order_details_c ("Order Id");

CREATE TABLE raw.item_selection_details_a (
    load_id             BIGINT  NOT NULL REFERENCES raw.load_log (load_id),
    source_file         TEXT    NOT NULL,
    source_row_number   INTEGER NOT NULL,          -- physical line in the file, header = 1
    "Order Id"          TEXT,
    "Order #"           TEXT,
    "Sent Date"         TEXT,
    "Order Date"        TEXT,
    "Check Id"          TEXT,
    "Table"             TEXT,
    "Dining Area"       TEXT,
    "Service"           TEXT,
    "Item Selection Id" TEXT,
    "Menu Item"         TEXT,
    "Menu Group"        TEXT,
    "Menu"              TEXT,
    "Sales Category"    TEXT,
    "Gross Price"       TEXT,
    "Discount"          TEXT,
    "Net Price"         TEXT,
    "Qty"               TEXT,
    "Void?"             TEXT,
    PRIMARY KEY (load_id, source_row_number)
);
CREATE INDEX ON raw.item_selection_details_a ("Order Id");
CREATE INDEX ON raw.item_selection_details_a ("Item Selection Id");
