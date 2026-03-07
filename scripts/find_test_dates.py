"""
find_test_dates.py — Find dates in the DB where risk metrics are genuinely elevated.

Prints candidate event dates for use in validate_cd_summaries.py --date.

Usage:
    uv run scripts/find_test_dates.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from chatbot.data_loader import _run  # noqa: E402

# EJ-heavy CDs that should spike hardest on heat events
EJ_CDS = ("BX-01", "BX-02", "BX-03", "MN-11", "BK-16", "BK-05", "QN-04")
EJ_TUPLE = ", ".join(f"'{c}'" for c in EJ_CDS)

print("NYC Urban Risk — Event Date Discovery")
print("=" * 60)

# --- Top heat event days (summer) across EJ CDs ---
print("\nTop 10 HEAT event dates (avg heat_index_risk across EJ CDs):")
sql = f"""
    SELECT h.date,
           ROUND(AVG(h.heat_index_risk)::numeric, 1)  AS avg_heat,
           ROUND(MAX(h.heat_index_risk)::numeric, 1)  AS max_heat,
           COUNT(*) AS n_cds
    FROM heat_index h
    WHERE h.cd_id IN ({EJ_TUPLE})
    GROUP BY h.date
    ORDER BY avg_heat DESC
    LIMIT 10
"""
df = _run(sql, [])
print(df.to_string(index=False))

# --- Top hospital strain days (any season) across all CDs ---
print("\nTop 10 HOSPITAL strain dates (avg total_capacity_pct, all CDs):")
sql = """
    SELECT hc.date,
           ROUND(AVG(hc.total_capacity_pct)::numeric, 1) AS avg_hosp,
           ROUND(MAX(hc.total_capacity_pct)::numeric, 1) AS max_hosp
    FROM hospital_capacity hc
    GROUP BY hc.date
    ORDER BY avg_hosp DESC
    LIMIT 10
"""
df = _run(sql, [])
print(df.to_string(index=False))

# --- Top combined multi-factor stress days ---
print("\nTop 10 COMBINED stress dates (heat + hospital + transit, all CDs):")
sql = """
    SELECT h.date,
           ROUND(AVG(h.heat_index_risk)::numeric, 1)       AS avg_heat,
           ROUND(AVG(hc.total_capacity_pct)::numeric, 1)   AS avg_hosp,
           ROUND(AVG(t.transit_delay_index)::numeric, 1)   AS avg_transit,
           ROUND((
               AVG(h.heat_index_risk / 80.0) +
               AVG((hc.total_capacity_pct - 50) / 50.0) +
               AVG(t.transit_delay_index / 60.0)
           )::numeric / 3, 3)                              AS combined_score
    FROM heat_index h
    JOIN hospital_capacity hc ON hc.cd_id = h.cd_id AND hc.date = h.date
    JOIN transit_delays     t ON t.cd_id  = h.cd_id AND t.date  = h.date
    GROUP BY h.date
    ORDER BY combined_score DESC
    LIMIT 10
"""
df = _run(sql, [])
print(df.to_string(index=False))
