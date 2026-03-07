"""
backend.py — Python data layer for NYC Urban Risk Shiny app.
Called via reticulate::source_python("backend.py") from app.R.
"""

import os
import psycopg2
from dotenv import load_dotenv

# Look for .env in app dir then parent
for p in (".", ".."):
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), p, ".env")
    if os.path.exists(env_file):
        load_dotenv(env_file)
        break

# BoroCD -> cd_id mapping (filters out park districts)
_BORO_PREFIX = {1: "MN", 2: "BX", 3: "BK", 4: "QN", 5: "SI"}
_VALID_CDS = {
    f"{_BORO_PREFIX[b]}-{n:02d}"
    for b, (lo, hi) in [(1, (1,12)), (2, (1,12)), (3, (1,18)), (4, (1,14)), (5, (1,3))]
    for n in range(lo, hi+1)
}

def borocd_to_cd_id(borocd: int) -> str | None:
    boro = borocd // 100
    cd   = borocd % 100
    prefix = _BORO_PREFIX.get(boro)
    if not prefix:
        return None
    cd_id = f"{prefix}-{cd:02d}"
    return cd_id if cd_id in _VALID_CDS else None


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


def get_risk_data(date_str: str) -> list[dict]:
    """
    Fetch 7-day average risk metrics for every CD ending on the given date.
    Returns a list of dicts, one per CD, with all risk columns.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    h.cd_id,
                    cd.borough,
                    cd.neighborhood,
                    AVG(h.heat_index_risk)      AS heat_index_risk,
                    AVG(hc.total_capacity_pct) AS total_capacity_pct,
                    AVG(hc.icu_capacity_pct)   AS icu_capacity_pct,
                    AVG(hc.ed_wait_hours)      AS ed_wait_hours,
                    MAX(t.transit_delay_index) AS transit_delay_index
                FROM heat_index h
                JOIN community_districts cd ON cd.cd_id = h.cd_id
                JOIN hospital_capacity  hc  ON hc.cd_id = h.cd_id AND hc.date = h.date
                JOIN transit_delays     t   ON t.cd_id  = h.cd_id AND t.date  = h.date
                WHERE h.date BETWEEN (%s::date - INTERVAL '6 days') AND %s::date
                GROUP BY h.cd_id, cd.borough, cd.neighborhood
                ORDER BY h.cd_id
            """, (date_str, date_str))
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
        def _clean(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return v

        return [
            {k: _clean(v) if k not in ("cd_id", "borough", "neighborhood") else v
             for k, v in zip(cols, row)}
            for row in rows
        ]
    finally:
        conn.close()


def get_date_range() -> dict:
    """Return the min and max dates available in the dataset."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MIN(date), MAX(date) FROM heat_index")
            min_date, max_date = cur.fetchone()
        return {"min": str(min_date), "max": str(max_date)}
    finally:
        conn.close()


def get_risk_series(cd_id: str, start_date: str, end_date: str) -> list[dict]:
    """
    Fetch 7-day average risk metrics for one CD over a date range (one row per date).
    Returns a list of dicts with keys: date, heat_index_risk, total_capacity_pct,
    icu_capacity_pct, ed_wait_hours, transit_delay_index.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    h.date,
                    AVG(h.heat_index_risk)      AS heat_index_risk,
                    AVG(hc.total_capacity_pct) AS total_capacity_pct,
                    AVG(hc.icu_capacity_pct)   AS icu_capacity_pct,
                    AVG(hc.ed_wait_hours)      AS ed_wait_hours,
                    MAX(t.transit_delay_index) AS transit_delay_index
                FROM heat_index h
                JOIN hospital_capacity hc ON hc.cd_id = h.cd_id AND hc.date = h.date
                JOIN transit_delays     t  ON t.cd_id  = h.cd_id AND t.date  = h.date
                WHERE h.cd_id = %s
                  AND h.date BETWEEN (%s::date - INTERVAL '6 days') AND %s::date
                  AND h.date >= %s::date
                GROUP BY h.date
                ORDER BY h.date
            """, (cd_id, start_date, end_date, start_date))
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
        def _clean(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return v

        return [
            {k: str(v) if k == "date" else _clean(v) for k, v in zip(cols, row)}
            for row in rows
        ]
    finally:
        conn.close()
