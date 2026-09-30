-- D003: raw = each export exactly as received; staging = typed and cleaned;
-- analytics = dimensional model. Only raw is populated so far.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analytics;
