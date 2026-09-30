-- Raw layer (D003, D010, D011). Every source column is TEXT under its original
-- name; nothing is converted, trimmed or de-duplicated. A blank cell is stored as
-- the empty string, exactly as it appears in the file.
--
-- One table per export layout (see docs/column_inventory.md):
--   order_details_a  10 columns, has Total and "Duration (Opened to Paid)"
--   order_details_b   9 columns, has Tax, no Total or Duration

CREATE TABLE raw.load_log (
    load_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_file TEXT        NOT NULL,
    file_hash   TEXT        NOT NULL UNIQUE,   -- SHA256 of the file's bytes (D011)
    export_type TEXT        NOT NULL,          -- 'A' or 'B'
    row_count   INTEGER     NOT NULL,          -- data rows stored (header lines excluded)
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE raw.order_details_a (
    load_id                     BIGINT  NOT NULL REFERENCES raw.load_log (load_id),
    source_file                 TEXT    NOT NULL,
    source_row_number           INTEGER NOT NULL,  -- physical line in the file, header = 1
    "Opened"                    TEXT,
    "# of Guests"               TEXT,
    "Table"                     TEXT,
    "Discount Amount"           TEXT,
    "Amount"                    TEXT,
    "Tip"                       TEXT,
    "Gratuity"                  TEXT,
    "Total"                     TEXT,
    "Closed"                    TEXT,
    "Duration (Opened to Paid)" TEXT,
    PRIMARY KEY (load_id, source_row_number)
);

CREATE TABLE raw.order_details_b (
    load_id           BIGINT  NOT NULL REFERENCES raw.load_log (load_id),
    source_file       TEXT    NOT NULL,
    source_row_number INTEGER NOT NULL,            -- physical line in the file, header = 1
    "Opened"          TEXT,
    "# of Guests"     TEXT,
    "Table"           TEXT,
    "Discount Amount" TEXT,
    "Amount"          TEXT,
    "Tax"             TEXT,
    "Tip"             TEXT,
    "Gratuity"        TEXT,
    "Closed"          TEXT,
    PRIMARY KEY (load_id, source_row_number)
);
