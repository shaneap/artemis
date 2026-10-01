-- ItemSelectionDetails without the "Service" column (always blank in the August pull;
-- left unticked in the 2026 re-export). Same rules as 002/003: all TEXT, original column
-- names, blank cell = '', no de-duplication. item_selection_details_a (with Service) is
-- kept for files that still carry that column.
CREATE TABLE raw.item_selection_details_b (
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
CREATE INDEX ON raw.item_selection_details_b ("Order Id");
CREATE INDEX ON raw.item_selection_details_b ("Item Selection Id");
