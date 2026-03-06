"""
Eight chatbot tools: get_cd_snapshot, get_top_risk_cds, get_fastest_accelerating,
get_factor_breakdown, query_combined_risk, compare_to_historical_analogs,
get_borough_rollup, get_agency_coordination_recommendations.
All use data_loader and analogs; return JSON-friendly dicts.
"""
from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from . import data_loader
from .data_loader import ensure_loaded
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
    ensure_loaded()
    cd_lookup = data_loader.cd_lookup
    heat_df, hospital_df, transit_df = data_loader.heat_df, data_loader.hospital_df, data_loader.transit_df
    d = pd.to_datetime(date_str).date()
    cd_id = cd_id.strip().upper()
    if cd_id not in cd_lookup["cd_id"].values:
        return {"error": f"Unknown cd_id: {cd_id}"}

    row_cd = cd_lookup[cd_lookup["cd_id"] == cd_id].iloc[0]
    h = heat_df[(heat_df["cd_id"] == cd_id) & (heat_df["date"].dt.date == d)]
    hosp = hospital_df[(hospital_df["cd_id"] == cd_id) & (hospital_df["date"].dt.date == d)]
    t = transit_df[(transit_df["cd_id"] == cd_id) & (transit_df["date"].dt.date == d)]

    if h.empty or hosp.empty or t.empty:
        return {"error": f"No data for {cd_id} on {date_str}"}

    heat_risk = float(h.iloc[0]["heat_index_risk"])
    temp = float(h.iloc[0]["temperature_f"])
    hum = float(h.iloc[0]["humidity_pct"])
    cap = float(hosp.iloc[0]["total_capacity_pct"])
    icu = float(hosp.iloc[0]["icu_capacity_pct"])
    ed = float(hosp.iloc[0]["ed_wait_hours"])
    trans = float(t.iloc[0]["transit_delay_index"])

    return {
        "cd_id": cd_id,
        "borough": str(row_cd["borough"]),
        "community_district": int(row_cd["community_district"]),
        "neighborhood": str(row_cd["neighborhood"]),
        "date": date_str,
        "heat_index_risk": round(heat_risk, 2),
        "temperature_f": round(temp, 2),
        "humidity_pct": round(hum, 2),
        "total_capacity_pct": round(cap, 2),
        "icu_capacity_pct": round(icu, 2),
        "ed_wait_hours": round(ed, 2),
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
    ensure_loaded()
    heat_df, hospital_df, transit_df = data_loader.heat_df, data_loader.hospital_df, data_loader.transit_df
    cd_lookup = data_loader.cd_lookup
    d = pd.to_datetime(date_str).date()
    merged = (
        heat_df[heat_df["date"].dt.date == d][["cd_id", "heat_index_risk"]]
        .merge(
            hospital_df[hospital_df["date"].dt.date == d][["cd_id", "total_capacity_pct"]],
            on="cd_id",
        )
        .merge(
            transit_df[transit_df["date"].dt.date == d][["cd_id", "transit_delay_index"]],
            on="cd_id",
        )
    )
    merged = merged.merge(cd_lookup[["cd_id", "borough", "neighborhood"]], on="cd_id")
    if borough:
        merged = merged[merged["borough"].str.lower() == borough.lower()]

    if factor == "heat":
        merged = merged.sort_values("heat_index_risk", ascending=False)
    elif factor == "hospital":
        merged = merged.sort_values("total_capacity_pct", ascending=False)
    elif factor == "transit":
        merged = merged.sort_values("transit_delay_index", ascending=False)
    else:
        merged["worst"] = merged[["heat_index_risk", "total_capacity_pct", "transit_delay_index"]].max(axis=1)
        merged = merged.sort_values("worst", ascending=False)

    top = merged.head(top_k)
    rows = []
    for _, r in top.iterrows():
        rows.append({
            "cd_id": str(r["cd_id"]),
            "district_name": str(r["neighborhood"]),
            "borough": str(r["borough"]),
            "heat_index_risk": round(float(r["heat_index_risk"]), 2),
            "total_capacity_pct": round(float(r["total_capacity_pct"]), 2),
            "transit_delay_index": round(float(r["transit_delay_index"]), 2),
            "main_risk_driver": _main_risk_driver(
                float(r["heat_index_risk"]),
                float(r["total_capacity_pct"]),
                float(r["transit_delay_index"]),
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
    """Return districts where one or more risk factors are rising the fastest (WoW or N-day change)."""
    ensure_loaded()
    wow_df = data_loader.wow_df
    heat_df, hospital_df, transit_df = data_loader.heat_df, data_loader.hospital_df, data_loader.transit_df
    cd_lookup = data_loader.cd_lookup
    d = pd.to_datetime(date_str)
    # Use WoW (7-day) if window_days is 7; else we'd need to compute N-day in data_loader. For MVP use wow_df.
    if window_days != 7:
        window_days = 7  # wow_df is 7-day
    current = wow_df[wow_df["date"] == d].copy()
    if current.empty:
        return {"error": f"No WoW data for {date_str}", "districts": []}

    current["accel_heat"] = current["heat_index_risk_wow"]
    current["accel_hosp"] = current["total_capacity_pct_wow"]
    current["accel_transit"] = current["transit_delay_index_wow"]
    current["accel_any"] = current[["accel_heat", "accel_hosp", "accel_transit"]].max(axis=1)

    if factor == "heat":
        current = current.sort_values("accel_heat", ascending=False)
    elif factor == "hospital":
        current = current.sort_values("accel_hosp", ascending=False)
    elif factor == "transit":
        current = current.sort_values("accel_transit", ascending=False)
    else:
        current = current.sort_values("accel_any", ascending=False)

    current = current.merge(cd_lookup[["cd_id", "borough", "neighborhood"]], on="cd_id")
    if borough:
        current = current[current["borough"].str.lower() == borough.lower()]
    current = current.head(top_k)

    # Get current values from merged tables
    merged = heat_df[heat_df["date"] == d][["cd_id", "heat_index_risk"]].merge(
        hospital_df[hospital_df["date"] == d][["cd_id", "total_capacity_pct"]], on="cd_id"
    ).merge(transit_df[transit_df["date"] == d][["cd_id", "transit_delay_index"]], on="cd_id")
    prior_date = d - pd.Timedelta(days=7)
    prior = heat_df[heat_df["date"] == prior_date][["cd_id", "heat_index_risk"]].merge(
        hospital_df[hospital_df["date"] == prior_date][["cd_id", "total_capacity_pct"]], on="cd_id"
    ).merge(transit_df[transit_df["date"] == prior_date][["cd_id", "transit_delay_index"]], on="cd_id")

    rows = []
    for _, r in current.iterrows():
        cid = r["cd_id"]
        cur = merged[merged["cd_id"] == cid]
        pr = prior[prior["cd_id"] == cid]
        fastest = "heat" if r["accel_heat"] >= max(r["accel_hosp"], r["accel_transit"]) else (
            "hospital" if r["accel_hosp"] >= r["accel_transit"] else "transit"
        )
        rows.append({
            "cd_id": str(cid),
            "district_name": str(r["neighborhood"]),
            "borough": str(r["borough"]),
            "current_heat_index_risk": round(float(cur.iloc[0]["heat_index_risk"]), 2) if not cur.empty else None,
            "prior_heat_index_risk": round(float(pr.iloc[0]["heat_index_risk"]), 2) if not pr.empty else None,
            "current_total_capacity_pct": round(float(cur.iloc[0]["total_capacity_pct"]), 2) if not cur.empty else None,
            "prior_total_capacity_pct": round(float(pr.iloc[0]["total_capacity_pct"]), 2) if not pr.empty else None,
            "current_transit_delay_index": round(float(cur.iloc[0]["transit_delay_index"]), 2) if not cur.empty else None,
            "prior_transit_delay_index": round(float(pr.iloc[0]["transit_delay_index"]), 2) if not pr.empty else None,
            "acceleration_heat_wow": round(float(r["accel_heat"]), 2) if pd.notna(r["accel_heat"]) else None,
            "acceleration_hospital_wow": round(float(r["accel_hosp"]), 2) if pd.notna(r["accel_hosp"]) else None,
            "acceleration_transit_wow": round(float(r["accel_transit"]), 2) if pd.notna(r["accel_transit"]) else None,
            "fastest_rising_factor": fastest,
        })
    return {"date": date_str, "window_days": window_days, "districts": rows}


# --- Tool 4: get_factor_breakdown ---


def get_factor_breakdown(cd_id: str, date_str: str) -> dict:
    """Explain which risk factors are driving concern in a district."""
    ensure_loaded()
    cd_id = cd_id.strip().upper()
    d = pd.to_datetime(date_str).date()
    h = heat_df[(heat_df["cd_id"] == cd_id) & (heat_df["date"].dt.date == d)]
    hosp = hospital_df[(hospital_df["cd_id"] == cd_id) & (hospital_df["date"].dt.date == d)]
    t = transit_df[(transit_df["cd_id"] == cd_id) & (transit_df["date"].dt.date == d)]
    if h.empty or hosp.empty or t.empty:
        return {"error": f"No data for {cd_id} on {date_str}"}

    heat_risk = float(h.iloc[0]["heat_index_risk"])
    cap = float(hosp.iloc[0]["total_capacity_pct"])
    trans = float(t.iloc[0]["transit_delay_index"])
    drivers = []
    if heat_risk >= HEAT_HIGH:
        drivers.append("heat")
    if cap >= HOSPITAL_HIGH:
        drivers.append("hospital")
    if trans >= TRANSIT_HIGH:
        drivers.append("transit")
    top_driver = drivers[0] if drivers else "moderate"
    secondary_driver = drivers[1] if len(drivers) > 1 else (drivers[0] if drivers else None)
    narrative = " and ".join(drivers) + " elevated." if drivers else "Conditions are moderate across factors."
    return {
        "cd_id": cd_id,
        "date": date_str,
        "heat_index_risk": round(heat_risk, 2),
        "total_capacity_pct": round(cap, 2),
        "transit_delay_index": round(trans, 2),
        "top_driver": top_driver,
        "secondary_driver": secondary_driver,
        "narrative": narrative,
    }


# --- Tool 5: query_combined_risk ---


def query_combined_risk(date_str: str, factors: list[str], condition: str = "elevated", top_k: int = 20) -> dict:
    """Return districts where multiple factors meet the condition (e.g. heat and hospital both elevated)."""
    ensure_loaded()
    heat_df, hospital_df, transit_df = data_loader.heat_df, data_loader.hospital_df, data_loader.transit_df
    cd_lookup = data_loader.cd_lookup
    d = pd.to_datetime(date_str).date()
    merged = (
        heat_df[heat_df["date"].dt.date == d][["cd_id", "heat_index_risk"]]
        .merge(hospital_df[hospital_df["date"].dt.date == d][["cd_id", "total_capacity_pct"]], on="cd_id")
        .merge(transit_df[transit_df["date"].dt.date == d][["cd_id", "transit_delay_index"]], on="cd_id")
        .merge(cd_lookup[["cd_id", "borough", "neighborhood"]], on="cd_id")
    )
    factors = [f.lower() for f in factors]
    if "heat" in factors:
        merged = merged[merged["heat_index_risk"] >= HEAT_HIGH]
    if "hospital" in factors:
        merged = merged[merged["total_capacity_pct"] >= HOSPITAL_HIGH]
    if "transit" in factors:
        merged = merged[merged["transit_delay_index"] >= TRANSIT_HIGH]
    merged = merged.head(top_k)
    rows = []
    for _, r in merged.iterrows():
        rows.append({
            "cd_id": str(r["cd_id"]),
            "district_name": str(r["neighborhood"]),
            "borough": str(r["borough"]),
            "heat_index_risk": round(float(r["heat_index_risk"]), 2),
            "total_capacity_pct": round(float(r["total_capacity_pct"]), 2),
            "transit_delay_index": round(float(r["transit_delay_index"]), 2),
            "combined_pattern_summary": _main_risk_driver(
                float(r["heat_index_risk"]),
                float(r["total_capacity_pct"]),
                float(r["transit_delay_index"]),
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
    ensure_loaded()
    heat_df, hospital_df, transit_df = data_loader.heat_df, data_loader.hospital_df, data_loader.transit_df
    cd_lookup = data_loader.cd_lookup
    d = pd.to_datetime(date_str).date()
    merged = (
        heat_df[heat_df["date"].dt.date == d][["cd_id", "heat_index_risk"]]
        .merge(hospital_df[hospital_df["date"].dt.date == d][["cd_id", "total_capacity_pct"]], on="cd_id")
        .merge(transit_df[transit_df["date"].dt.date == d][["cd_id", "transit_delay_index"]], on="cd_id")
        .merge(cd_lookup[["cd_id", "borough", "neighborhood"]], on="cd_id")
    )
    b = merged[merged["borough"].str.lower() == borough.lower()]
    if b.empty:
        return {"error": f"No data for borough: {borough}", "borough": borough, "date": date_str}

    avg_heat = b["heat_index_risk"].mean()
    avg_cap = b["total_capacity_pct"].mean()
    avg_transit = b["transit_delay_index"].mean()
    top_heat = b.nlargest(3, "heat_index_risk")[["cd_id", "neighborhood", "heat_index_risk"]].to_dict("records")
    top_hosp = b.nlargest(3, "total_capacity_pct")[["cd_id", "neighborhood", "total_capacity_pct"]].to_dict("records")
    top_transit = b.nlargest(3, "transit_delay_index")[["cd_id", "neighborhood", "transit_delay_index"]].to_dict("records")
    drivers = []
    if avg_heat >= HEAT_HIGH:
        drivers.append("heat")
    if avg_cap >= HOSPITAL_HIGH:
        drivers.append("hospital")
    if avg_transit >= TRANSIT_HIGH:
        drivers.append("transit")
    trend = "elevated" if drivers else "moderate"
    return {
        "borough": borough,
        "date": date_str,
        "average_heat_index_risk": round(avg_heat, 2),
        "average_total_capacity_pct": round(avg_cap, 2),
        "average_transit_delay_index": round(avg_transit, 2),
        "highest_concern_cds_heat": top_heat,
        "highest_concern_cds_hospital": top_hosp,
        "highest_concern_cds_transit": top_transit,
        "main_borough_drivers": drivers,
        "borough_trend": trend,
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
