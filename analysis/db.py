"""Read the warehouse's analytics tables into pandas. Analysis scripts import this.

    from analysis.db import query
    nightly = query("SELECT ... FROM analytics.fact_order ...")
"""
import sys
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import load_raw  # noqa: E402  (connection settings live there)

RESULTS = Path(__file__).resolve().parent / "results"


def query(sql, params=None):
    with psycopg.connect(**load_raw.connect_kwargs()) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def nightly():
    """One row per service date that traded: revenue split by order type, party and guest
    counts (seated, excluding $0 tickets), and the day's weather."""
    df = query("""
        SELECT d.service_date, d.day_name, d.iso_day_of_week, d.is_fri_or_sat, d.month_start, d.year,
               count(f.order_id)                                          AS orders,
               COALESCE(sum(f.amount), 0)                                 AS revenue,
               COALESCE(sum(f.amount) FILTER (WHERE f.order_type = 'Seated'), 0)          AS seated_revenue,
               COALESCE(sum(f.amount) FILTER (WHERE f.order_type = 'Event-Catering'), 0)  AS event_revenue,
               COALESCE(sum(f.amount) FILTER (WHERE f.order_type = 'To-Go'), 0)           AS togo_revenue,
               count(*) FILTER (WHERE f.order_type = 'Seated' AND f.amount > 0)           AS parties,
               COALESCE(sum(f.guests) FILTER (WHERE f.order_type = 'Seated' AND f.amount > 0
                                               AND NOT f.guests_implausible), 0)          AS guests
        FROM analytics.dim_date d
        LEFT JOIN analytics.fact_order f USING (date_key)
        GROUP BY 1, 2, 3, 4, 5, 6
        ORDER BY 1""")
    for c in ("revenue", "seated_revenue", "event_revenue", "togo_revenue"):
        df[c] = df[c].astype(float)
    df["service_date"] = pd.to_datetime(df["service_date"])
    df["month_start"] = pd.to_datetime(df["month_start"])
    import weather
    wx = weather.load_weather(df["service_date"].min().date().isoformat(),
                              df["service_date"].max().date().isoformat())
    return df.merge(wx, left_on="service_date", right_on="Service_Date", how="left").drop(columns="Service_Date")
