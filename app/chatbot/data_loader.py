"""
On-demand data access for the chatbot: query Supabase only for what each tool needs.
"""
import os
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

# Load .env from hackathon root
_THIS_DIR = Path(__file__).resolve().parent
load_dotenv(_THIS_DIR.parent.parent / ".env")
load_dotenv()  # fallback to cwd


def _get_conn():
    return psycopg2.connect(
        host=os.getenv("SUPABASE_HOST"),
        port=int(os.getenv("SUPABASE_PORT", "5432")),
        dbname=os.getenv("SUPABASE_DB", "postgres"),
        user=os.getenv("SUPABASE_USER", "postgres"),
        password=os.getenv("SUPABASE_PASSWORD", ""),
        connect_timeout=10,
        sslmode="require",
    )


# Base SELECT joining all four tables into one flat row per (cd, date)
_BASE_SELECT = """
    SELECT
        cd.cd_id, cd.borough, cd.neighborhood, cd.community_district,
        h.date,
        h.temperature_f, h.humidity_pct, h.heat_index_f, h.heat_index_risk,
        hc.total_capacity_pct, hc.icu_capacity_pct, hc.ed_wait_hours,
        t.transit_delay_index
    FROM heat_index h
    JOIN community_districts cd ON cd.cd_id = h.cd_id
    JOIN hospital_capacity   hc ON hc.cd_id = h.cd_id AND hc.date = h.date
    JOIN transit_delays       t ON t.cd_id  = h.cd_id AND t.date  = h.date
"""


def _run(sql: str, params: list) -> pd.DataFrame:
    conn = _get_conn()
    try:
        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def query_for_date(date_str: str, cd_id: str | None = None, borough: str | None = None) -> pd.DataFrame:
    """All columns for a specific date. Optionally narrow to one CD or one borough."""
    where, params = ["h.date = %s"], [date_str]
    if cd_id:
        where.append("h.cd_id = %s")
        params.append(cd_id)
    if borough:
        where.append("cd.borough ILIKE %s")
        params.append(borough)
    return _run(_BASE_SELECT + " WHERE " + " AND ".join(where), params)


def query_for_two_dates(date_str: str, prior_date_str: str, borough: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch current and prior dates in one round trip; return as (current_df, prior_df)."""
    where, params = ["h.date IN (%s, %s)"], [date_str, prior_date_str]
    if borough:
        where.append("cd.borough ILIKE %s")
        params.append(borough)
    df = _run(_BASE_SELECT + " WHERE " + " AND ".join(where), params)
    current = df[df["date"] == pd.Timestamp(date_str)].copy()
    prior   = df[df["date"] == pd.Timestamp(prior_date_str)].copy()
    return current, prior


def query_cd_history(cd_id: str) -> pd.DataFrame:
    """Full history for one CD — used by the historical analogs tool."""
    return _run(_BASE_SELECT + " WHERE h.cd_id = %s ORDER BY h.date", [cd_id])
