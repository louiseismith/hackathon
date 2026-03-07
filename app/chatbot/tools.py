"""
Eight chatbot tools: get_cd_snapshot, get_top_risk_cds, get_fastest_accelerating,
get_factor_breakdown, query_combined_risk, compare_to_historical_analogs,
get_borough_rollup, get_agency_coordination_recommendations.
All query Supabase on demand via data_loader; return JSON-friendly dicts.
"""
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from .data_loader import query_for_date, query_for_two_dates
from .analogs import get_historical_analogs

# --- Pydantic input models for tools ---


class GetCdSnapshotInput(BaseModel):
    cd_id: str = Field(description="Community district ID, e.g. BX-03, MN-11")
    date: str = Field(description="Date in YYYY-MM-DD format")


class GetTopRiskCdsInput(BaseModel):
    date: str = Field(description="Date in YYYY-MM-DD format")
    top_k: int = Field(default=10, ge=1, le=59, description="Number of top districts to return")
    borough: str | None = Field(default=None, description="Optional borough name to filter")
    factor: Literal["heat", "hospital", "transit", "any"] = Field(
        default="any",
        description="Rank by this factor; 'any' = worst of the three",
    )


class GetFastestAcceleratingInput(BaseModel):
    date: str = Field(description="Date in YYYY-MM-DD format")
    window_days: int = Field(default=7, ge=1, le=90, description="Look back this many days for acceleration")
    top_k: int = Field(default=10, ge=1, le=59)
    borough: str | None = None
    factor: Literal["heat", "hospital", "transit", "any"] = "any"


class GetFactorBreakdownInput(BaseModel):
    cd_id: str = Field(description="Community district ID")
    date: str = Field(description="Date in YYYY-MM-DD format")


class QueryCombinedRiskInput(BaseModel):
    date: str = Field(description="Date in YYYY-MM-DD format")
    factors: list[str] = Field(description="List of factors, e.g. ['heat', 'hospital']")
    condition: str = Field(default="elevated", description="e.g. elevated, high, rising")
    top_k: int = Field(default=20, ge=1, le=59)


class CompareToHistoricalAnalogsInput(BaseModel):
    cd_id: str = Field(description="Community district ID")
    date: str = Field(description="Date in YYYY-MM-DD format")
    top_k: int = Field(default=5, ge=1, le=20)


class GetBoroughRollupInput(BaseModel):
    borough: str = Field(description="Borough name: Manhattan, Bronx, Brooklyn, Queens, Staten Island")
    date: str = Field(description="Date in YYYY-MM-DD format")


class GetAgencyCoordinationRecommendationsInput(BaseModel):
    cd_id: str = Field(description="Community district ID")
    date: str = Field(description="Date in YYYY-MM-DD format")


# --- Thresholds (plan section 15) ---
HEAT_HIGH = 50
HOSPITAL_HIGH = 85
TRANSIT_HIGH = 30


def _primary_concern(heat: float, hosp: float, transit: float) -> str:
    if heat >= HEAT_HIGH and hosp >= HOSPITAL_HIGH:
        return "multi-factor"
    if heat >= HEAT_HIGH and transit >= TRANSIT_HIGH:
        return "multi-factor"
    if hosp >= HOSPITAL_HIGH and transit >= TRANSIT_HIGH:
        return "multi-factor"
    if heat >= HEAT_HIGH:
        return "heat"
    if hosp >= HOSPITAL_HIGH:
        return "hospital"
    if transit >= TRANSIT_HIGH:
        return "transit"
    return "moderate"


def _main_risk_driver(heat: float, hosp: float, transit: float) -> str:
    if heat >= HEAT_HIGH and (hosp >= HOSPITAL_HIGH or transit >= TRANSIT_HIGH):
        return "heat and other factors"
    if hosp >= HOSPITAL_HIGH and (heat >= HEAT_HIGH or transit >= TRANSIT_HIGH):
        return "hospital strain and other factors"
    if transit >= TRANSIT_HIGH and (heat >= HEAT_HIGH or hosp >= HOSPITAL_HIGH):
        return "transit disruption and other factors"
    if heat >= HEAT_HIGH:
        return "heat"
    if hosp >= HOSPITAL_HIGH:
        return "hospital"
    if transit >= TRANSIT_HIGH:
        return "transit"
    return "moderate"


# --- Tool 1: get_cd_snapshot ---


def get_cd_snapshot(cd_id: str, date_str: str) -> dict:
    """Return current or selected-date risk snapshot for one community district."""
    cd_id = cd_id.strip().upper()
    df = query_for_date(date_str, cd_id=cd_id)
    if df.empty:
        return {"error": f"No data for {cd_id} on {date_str}"}
    r = df.iloc[0]
    heat_risk = float(r["heat_index_risk"])
    cap       = float(r["total_capacity_pct"])
    trans     = float(r["transit_delay_index"])
    return {
        "cd_id": cd_id,
        "borough": str(r["borough"]),
        "community_district": int(r["community_district"]),
        "neighborhood": str(r["neighborhood"]),
        "date": date_str,
        "heat_index_risk": round(heat_risk, 2),
        "temperature_f": round(float(r["temperature_f"]), 2),
        "humidity_pct": round(float(r["humidity_pct"]), 2),
        "total_capacity_pct": round(cap, 2),
        "icu_capacity_pct": round(float(r["icu_capacity_pct"]), 2),
        "ed_wait_hours": round(float(r["ed_wait_hours"]), 2),
        "transit_delay_index": round(trans, 2),
        "primary_concern": _primary_concern(heat_risk, cap, trans),
    }


# --- Tool 2: get_top_risk_cds ---


def get_top_risk_cds(
    date_str: str,
    top_k: int = 10,
    borough: str | None = None,
    factor: str = "any",
) -> dict:
    """Return highest-risk community districts for a given date, ranked by chosen factor."""
    df = query_for_date(date_str, borough=borough)
    if df.empty:
        return {"date": date_str, "districts": []}

    sort_col = {"heat": "heat_index_risk", "hospital": "total_capacity_pct", "transit": "transit_delay_index"}.get(factor)
    if sort_col:
        df = df.sort_values(sort_col, ascending=False)
    else:
        df = df.assign(worst=df[["heat_index_risk", "total_capacity_pct", "transit_delay_index"]].max(axis=1))
        df = df.sort_values("worst", ascending=False)

    rows = []
    for _, r in df.head(top_k).iterrows():
        rows.append({
            "cd_id": str(r["cd_id"]),
            "district_name": str(r["neighborhood"]),
            "borough": str(r["borough"]),
            "heat_index_risk": round(float(r["heat_index_risk"]), 2),
            "total_capacity_pct": round(float(r["total_capacity_pct"]), 2),
            "transit_delay_index": round(float(r["transit_delay_index"]), 2),
            "main_risk_driver": _main_risk_driver(
                float(r["heat_index_risk"]), float(r["total_capacity_pct"]), float(r["transit_delay_index"])
            ),
        })
    return {"date": date_str, "districts": rows}


# --- Tool 3: get_fastest_accelerating ---


def get_fastest_accelerating(
    date_str: str,
    window_days: int = 7,
    top_k: int = 10,
    borough: str | None = None,
    factor: str = "any",
) -> dict:
    """Return districts where one or more risk factors are rising the fastest (7-day change)."""
    d = pd.to_datetime(date_str)
    prior_date_str = str((d - pd.Timedelta(days=7)).date())
    current, prior = query_for_two_dates(date_str, prior_date_str, borough=borough)

    if current.empty or prior.empty:
        return {"error": f"No data for {date_str} or prior week", "districts": []}

    cols = ["cd_id", "neighborhood", "borough", "heat_index_risk", "total_capacity_pct", "transit_delay_index"]
    merged = current[cols].merge(
        prior[["cd_id", "heat_index_risk", "total_capacity_pct", "transit_delay_index"]].rename(columns={
            "heat_index_risk": "prev_heat",
            "total_capacity_pct": "prev_hosp",
            "transit_delay_index": "prev_transit",
        }),
        on="cd_id",
    )
    merged["accel_heat"]   = merged["heat_index_risk"]    - merged["prev_heat"]
    merged["accel_hosp"]   = merged["total_capacity_pct"] - merged["prev_hosp"]
    merged["accel_transit"]= merged["transit_delay_index"]- merged["prev_transit"]
    merged["accel_any"]    = merged[["accel_heat", "accel_hosp", "accel_transit"]].max(axis=1)

    sort_col = {"heat": "accel_heat", "hospital": "accel_hosp", "transit": "accel_transit"}.get(factor, "accel_any")
    merged = merged.sort_values(sort_col, ascending=False).head(top_k)

    rows = []
    for _, r in merged.iterrows():
        fastest = "heat" if r["accel_heat"] >= max(r["accel_hosp"], r["accel_transit"]) else (
            "hospital" if r["accel_hosp"] >= r["accel_transit"] else "transit"
        )
        rows.append({
            "cd_id": str(r["cd_id"]),
            "district_name": str(r["neighborhood"]),
            "borough": str(r["borough"]),
            "current_heat_index_risk": round(float(r["heat_index_risk"]), 2),
            "prior_heat_index_risk": round(float(r["prev_heat"]), 2),
            "current_total_capacity_pct": round(float(r["total_capacity_pct"]), 2),
            "prior_total_capacity_pct": round(float(r["prev_hosp"]), 2),
            "current_transit_delay_index": round(float(r["transit_delay_index"]), 2),
            "prior_transit_delay_index": round(float(r["prev_transit"]), 2),
            "acceleration_heat_wow": round(float(r["accel_heat"]), 2),
            "acceleration_hospital_wow": round(float(r["accel_hosp"]), 2),
            "acceleration_transit_wow": round(float(r["accel_transit"]), 2),
            "fastest_rising_factor": fastest,
        })
    return {"date": date_str, "window_days": 7, "districts": rows}


# --- Tool 4: get_factor_breakdown ---


def get_factor_breakdown(cd_id: str, date_str: str) -> dict:
    """Explain which risk factors are driving concern in a district."""
    cd_id = cd_id.strip().upper()
    df = query_for_date(date_str, cd_id=cd_id)
    if df.empty:
        return {"error": f"No data for {cd_id} on {date_str}"}
    r = df.iloc[0]
    heat_risk = float(r["heat_index_risk"])
    cap       = float(r["total_capacity_pct"])
    trans     = float(r["transit_delay_index"])
    drivers = (
        (["heat"] if heat_risk >= HEAT_HIGH else []) +
        (["hospital"] if cap >= HOSPITAL_HIGH else []) +
        (["transit"] if trans >= TRANSIT_HIGH else [])
    )
    return {
        "cd_id": cd_id,
        "date": date_str,
        "heat_index_risk": round(heat_risk, 2),
        "total_capacity_pct": round(cap, 2),
        "transit_delay_index": round(trans, 2),
        "top_driver": drivers[0] if drivers else "moderate",
        "secondary_driver": drivers[1] if len(drivers) > 1 else (drivers[0] if drivers else None),
        "narrative": " and ".join(drivers) + " elevated." if drivers else "Conditions are moderate across factors.",
    }


# --- Tool 5: query_combined_risk ---


def query_combined_risk(date_str: str, factors: list[str], condition: str = "elevated", top_k: int = 20) -> dict:
    """Return districts where multiple factors meet the condition (e.g. heat and hospital both elevated)."""
    df = query_for_date(date_str)
    factors = [f.lower() for f in factors]
    if "heat" in factors:
        df = df[df["heat_index_risk"] >= HEAT_HIGH]
    if "hospital" in factors:
        df = df[df["total_capacity_pct"] >= HOSPITAL_HIGH]
    if "transit" in factors:
        df = df[df["transit_delay_index"] >= TRANSIT_HIGH]
    rows = []
    for _, r in df.head(top_k).iterrows():
        rows.append({
            "cd_id": str(r["cd_id"]),
            "district_name": str(r["neighborhood"]),
            "borough": str(r["borough"]),
            "heat_index_risk": round(float(r["heat_index_risk"]), 2),
            "total_capacity_pct": round(float(r["total_capacity_pct"]), 2),
            "transit_delay_index": round(float(r["transit_delay_index"]), 2),
            "combined_pattern_summary": _main_risk_driver(
                float(r["heat_index_risk"]), float(r["total_capacity_pct"]), float(r["transit_delay_index"])
            ),
        })
    return {"date": date_str, "factors": factors, "condition": condition, "districts": rows}


# --- Tool 6: compare_to_historical_analogs ---


def compare_to_historical_analogs(cd_id: str, date_str: str, top_k: int = 5) -> dict:
    """Compare current district conditions to similar past days; return analogs and what happened next."""
    ensure_loaded()
    cd_id = cd_id.strip().upper()
    d = pd.to_datetime(date_str)
    analogs = get_historical_analogs(cd_id, d, top_k=top_k)
    return {"cd_id": cd_id, "date": date_str, "analogs": analogs}


# --- Tool 7: get_borough_rollup ---


def get_borough_rollup(borough: str, date_str: str) -> dict:
    """Summarize district-level conditions at borough level."""
    df = query_for_date(date_str, borough=borough)
    if df.empty:
        return {"error": f"No data for borough: {borough}", "borough": borough, "date": date_str}
    avg_heat    = df["heat_index_risk"].mean()
    avg_cap     = df["total_capacity_pct"].mean()
    avg_transit = df["transit_delay_index"].mean()
    drivers = (
        (["heat"] if avg_heat >= HEAT_HIGH else []) +
        (["hospital"] if avg_cap >= HOSPITAL_HIGH else []) +
        (["transit"] if avg_transit >= TRANSIT_HIGH else [])
    )
    return {
        "borough": borough,
        "date": date_str,
        "average_heat_index_risk": round(avg_heat, 2),
        "average_total_capacity_pct": round(avg_cap, 2),
        "average_transit_delay_index": round(avg_transit, 2),
        "highest_concern_cds_heat":     df.nlargest(3, "heat_index_risk")[["cd_id", "neighborhood", "heat_index_risk"]].to_dict("records"),
        "highest_concern_cds_hospital": df.nlargest(3, "total_capacity_pct")[["cd_id", "neighborhood", "total_capacity_pct"]].to_dict("records"),
        "highest_concern_cds_transit":  df.nlargest(3, "transit_delay_index")[["cd_id", "neighborhood", "transit_delay_index"]].to_dict("records"),
        "main_borough_drivers": drivers,
        "borough_trend": "elevated" if drivers else "moderate",
    }


# --- Tool 8: get_agency_coordination_recommendations ---


def get_agency_coordination_recommendations(cd_id: str, date_str: str) -> dict:
    """Map district risk factors to agencies to notify and suggested actions (rule-based)."""
    ensure_loaded()
    snap = get_cd_snapshot(cd_id, date_str)
    if "error" in snap:
        return snap
    heat = snap["heat_index_risk"]
    hosp = snap["total_capacity_pct"]
    trans = snap["transit_delay_index"]

    agencies = []
    reason = []
    actions = []
    urgency = "moderate"

    if heat >= HEAT_HIGH and hosp >= HOSPITAL_HIGH:
        agencies = ["Emergency Management", "Public Health / Hospitals", "EMS / Urgent Care"]
        reason.append("High heat and hospital strain")
        actions.append("Coordinate cooling centers and hospital surge capacity")
        urgency = "high"
    elif heat >= HEAT_HIGH and trans >= TRANSIT_HIGH:
        agencies = ["Emergency Management", "Public Health", "Transit Ops"]
        reason.append("High heat and transit disruption")
        actions.append("Cooling centers and transit service communication")
        urgency = "high"
    elif hosp >= HOSPITAL_HIGH and trans >= TRANSIT_HIGH:
        agencies = ["Transit Ops", "Emergency Management", "Public Health / Hospitals"]
        reason.append("Hospital strain and transit disruption")
        actions.append("Field logistics and service communication")
        urgency = "high"
    elif heat >= HEAT_HIGH:
        agencies = ["Emergency Management", "Public Health"]
        reason.append("Elevated heat stress")
        actions.append("Cooling center / city services coordination")
        urgency = "elevated"
    elif hosp >= HOSPITAL_HIGH:
        agencies = ["Emergency Management", "Public Health / Hospitals"]
        reason.append("Hospital capacity strain")
        actions.append("Monitor ED wait times and surge capacity")
        urgency = "elevated"
    elif trans >= TRANSIT_HIGH:
        agencies = ["Transit Ops", "Emergency Management"]
        reason.append("Transit disruption")
        actions.append("Field logistics / service communication")
        urgency = "elevated"
    else:
        agencies = []
        reason.append("Conditions within normal range")
        actions.append("Routine monitoring")

    return {
        "cd_id": cd_id,
        "date": date_str,
        "agencies_to_notify": agencies,
        "suggested_coordination_reason": "; ".join(reason),
        "suggested_actions": actions,
        "urgency_level": urgency,
    }
