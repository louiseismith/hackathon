"""
On-demand data access for the chatbot: query Supabase only for what each tool needs.
"""
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load .env from hackathon root
_THIS_DIR = Path(__file__).resolve().parent
load_dotenv(_THIS_DIR.parent.parent / ".env")
load_dotenv()  # fallback to cwd


def _get_engine():
    host     = os.getenv("SUPABASE_HOST")
    port     = os.getenv("SUPABASE_PORT", "5432")
    dbname   = os.getenv("SUPABASE_DB", "postgres")
    user     = os.getenv("SUPABASE_USER", "postgres")
    password = os.getenv("SUPABASE_PASSWORD", "")
    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}?sslmode=require&connect_timeout=10"
    return create_engine(url)


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
    # Convert %s placeholders to SQLAlchemy named params (:p0, :p1, ...)
    for i in range(len(params)):
        sql = sql.replace("%s", f":p{i}", 1)
    engine = _get_engine()
    with engine.connect() as conn:
        df = pd.read_sql_query(text(sql), conn,
                               params={f"p{i}": v for i, v in enumerate(params)})
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


def query_for_date_range(start_date: str, end_date: str, cd_id: str | None = None, borough: str | None = None) -> pd.DataFrame:
    """All columns for a date range. Optionally narrow to one CD or one borough."""
    where, params = ["h.date BETWEEN %s AND %s"], [start_date, end_date]
    if cd_id:
        where.append("h.cd_id = %s")
        params.append(cd_id)
    if borough:
        where.append("cd.borough ILIKE %s")
        params.append(borough)
    return _run(_BASE_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY h.date", params)


def query_monthly_baseline(cd_id: str, month: int, exclude_date: str, current_values: dict | None = None) -> dict:
    """Percentile distribution for a CD for a specific calendar month across all years, excluding today.

    Returns p50/p90 for each metric, plus the percentile rank of each current value if provided.
    """
    sql = (
        _BASE_SELECT
        + " WHERE h.cd_id = %s AND EXTRACT(MONTH FROM h.date) = %s AND h.date != %s"
    )
    df = _run(sql, [cd_id, month, exclude_date])
    if df.empty:
        return {}

    result: dict = {"years_of_data": int(df["date"].dt.year.nunique())}

    _metrics = [
        ("heat_index_risk",    "heat_index_risk"),
        ("total_capacity_pct", "total_capacity_pct"),
        ("transit_delay_index","transit_delay_index"),
        ("ed_wait_hours",      "ed_wait_hours"),
    ]
    for key, col in _metrics:
        result[f"{key}_p50"] = round(float(df[col].quantile(0.50)), 2)
        result[f"{key}_p90"] = round(float(df[col].quantile(0.90)), 2)
        if current_values and key in current_values:
            result[f"{key}_percentile"] = round(
                float((df[col] <= current_values[key]).mean() * 100), 1
            )

    return result


def query_full_history(cd_id: str | None = None, borough: str | None = None) -> pd.DataFrame:
    """Full history for one CD or borough — used by the multiyear trend tool."""
    where, params = [], []
    if cd_id:
        where.append("h.cd_id = %s")
        params.append(cd_id)
    if borough:
        where.append("cd.borough ILIKE %s")
        params.append(borough)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return _run(_BASE_SELECT + clause + " ORDER BY h.date", params)
