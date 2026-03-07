"""
Seven chatbot tools: get_cd_snapshot, get_top_risk_cds, get_fastest_accelerating,
query_combined_risk, compare_to_historical_analogs,
get_agency_coordination_recommendations, get_multiyear_trend.
All query Supabase on demand via data_loader; return JSON-friendly dicts.
"""
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from .data_loader import (
    query_for_date,
    query_for_two_dates,
    query_for_date_range,
    query_full_history,
)
from .analogs import get_historical_analogs

# --- Pydantic input models ---


class GetCdSnapshotInput(BaseModel):
    cd_id: str = Field(description="Community district ID, e.g. BX-03, MN-11")
    date: str = Field(description="Date in YYYY-MM-DD format")


class GetTopRiskCdsInput(BaseModel):
    date: str = Field(description="Date in YYYY-MM-DD format (end of range if start_date provided)")
    start_date: str | None = Field(default=None, description="If provided, rank by average risk over start_date–date range instead of a single day")
    top_k: int = Field(default=10, ge=1, le=59, description="Number of top districts to return")
    borough: str | None = Field(default=None, description="Optional borough name to filter")
    factor: Literal["heat", "hospital", "transit", "any"] = Field(
        default="any",
        description="Rank by this factor; 'any' = worst of the three",
    )


class GetFastestAcceleratingInput(BaseModel):
    date: str = Field(description="Date in YYYY-MM-DD format")
    window_days: int = Field(default=7, ge=1, le=90, description="Compare to this many days ago (7=week, 30=month, 365=year)")
    top_k: int = Field(default=10, ge=1, le=59)
    borough: str | None = None
    factor: Literal["heat", "hospital", "transit", "any"] = "any"


class QueryCombinedRiskInput(BaseModel):
    date: str = Field(description="Date in YYYY-MM-DD format (end of range if start_date provided)")
    start_date: str | None = Field(default=None, description="If provided, find CDs where factors were sustained above thresholds on average over this date range")
    factors: list[str] = Field(description="List of factors, e.g. ['heat', 'hospital']")
    condition: str = Field(default="elevated", description="e.g. elevated, high, rising")
    top_k: int = Field(default=20, ge=1, le=59)


class CompareToHistoricalAnalogsInput(BaseModel):
    cd_id: str = Field(description="Community district ID")
    date: str = Field(description="Date in YYYY-MM-DD format")
    top_k: int = Field(default=5, ge=1, le=20)


class GetAgencyCoordinationRecommendationsInput(BaseModel):
    cd_id: str = Field(description="Community district ID")
    date: str = Field(description="Date in YYYY-MM-DD format")


class GetMultiyearTrendInput(BaseModel):
    factor: Literal["heat", "hospital", "transit"] = Field(description="Risk factor to analyze: heat, hospital, or transit")
    cd_id: str | None = Field(default=None, description="Community district ID (e.g. BX-03). Provide either cd_id or borough.")
    borough: str | None = Field(default=None, description="Borough name: Manhattan, Bronx, Brooklyn, Queens, Staten Island. Alternative to cd_id.")
    month_start: int | None = Field(default=None, ge=1, le=12, description="Start month for seasonal filter (e.g. 6 for June). Omit for full year.")
    month_end: int | None = Field(default=None, ge=1, le=12, description="End month for seasonal filter (e.g. 8 for August). Omit for full year.")


# --- Thresholds ---
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


def _driver_fields(heat: float, hosp: float, transit: float) -> dict:
    drivers = (
        (["heat"] if heat >= HEAT_HIGH else []) +
        (["hospital"] if hosp >= HOSPITAL_HIGH else []) +
        (["transit"] if transit >= TRANSIT_HIGH else [])
    )
    return {
        "top_driver": drivers[0] if drivers else "moderate",
        "secondary_driver": drivers[1] if len(drivers) > 1 else (drivers[0] if drivers else None),
        "narrative": " and ".join(drivers) + " elevated." if drivers else "Conditions are moderate across factors.",
    }


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
        "ed_wait_hours": round(float(r["ed_wait_hours"]), 2),
        "transit_delay_index": round(trans, 2),
        "primary_concern": _primary_concern(heat_risk, cap, trans),
        **_driver_fields(heat_risk, cap, trans),
    }


# --- Tool 2: get_top_risk_cds ---


def get_top_risk_cds(
    date_str: str,
    top_k: int = 10,
    borough: str | None = None,
    factor: str = "any",
    start_date: str | None = None,
) -> dict:
    """Return highest-risk community districts for a date or averaged over a date range, ranked by chosen factor."""
    if start_date:
        df = query_for_date_range(start_date, date_str, borough=borough)
        if df.empty:
            return {"date_range": f"{start_date} to {date_str}", "districts": []}
        cols = ["cd_id", "neighborhood", "borough", "heat_index_risk", "total_capacity_pct", "transit_delay_index"]
        df = df[cols].groupby(["cd_id", "neighborhood", "borough"]).mean().reset_index()
        date_label = f"{start_date} to {date_str}"
        aggregated = True
    else:
        df = query_for_date(date_str, borough=borough)
        if df.empty:
            return {"date": date_str, "districts": []}
        date_label = date_str
        aggregated = False

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
    return {"date": date_label, "aggregated": aggregated, "districts": rows}


# --- Tool 3: get_fastest_accelerating ---


def get_fastest_accelerating(
    date_str: str,
    window_days: int = 7,
    top_k: int = 10,
    borough: str | None = None,
    factor: str = "any",
) -> dict:
    """Return districts where one or more risk factors are rising the fastest over the given window."""
    d = pd.to_datetime(date_str)
    prior_date_str = str((d - pd.Timedelta(days=window_days)).date())
    current, prior = query_for_two_dates(date_str, prior_date_str, borough=borough)

    if current.empty or prior.empty:
        return {"error": f"No data for {date_str} or {window_days} days prior", "districts": []}

    cols = ["cd_id", "neighborhood", "borough", "heat_index_risk", "total_capacity_pct", "transit_delay_index"]
    merged = current[cols].merge(
        prior[["cd_id", "heat_index_risk", "total_capacity_pct", "transit_delay_index"]].rename(columns={
            "heat_index_risk": "prev_heat",
            "total_capacity_pct": "prev_hosp",
            "transit_delay_index": "prev_transit",
        }),
        on="cd_id",
    )
    merged["accel_heat"]    = merged["heat_index_risk"]    - merged["prev_heat"]
    merged["accel_hosp"]    = merged["total_capacity_pct"] - merged["prev_hosp"]
    merged["accel_transit"] = merged["transit_delay_index"] - merged["prev_transit"]
    merged["accel_any"]     = merged[["accel_heat", "accel_hosp", "accel_transit"]].max(axis=1)

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
            "acceleration_heat": round(float(r["accel_heat"]), 2),
            "acceleration_hospital": round(float(r["accel_hosp"]), 2),
            "acceleration_transit": round(float(r["accel_transit"]), 2),
            "fastest_rising_factor": fastest,
        })
    return {"date": date_str, "window_days": window_days, "prior_date": prior_date_str, "districts": rows}


# --- Tool 4: query_combined_risk ---


def query_combined_risk(
    date_str: str,
    factors: list[str],
    condition: str = "elevated",
    top_k: int = 20,
    start_date: str | None = None,
) -> dict:
    """Return districts where multiple factors meet thresholds. With start_date, finds CDs with sustained combined risk over a period."""
    factors = [f.lower() for f in factors]

    if start_date:
        df = query_for_date_range(start_date, date_str)
        if df.empty:
            return {"date_range": f"{start_date} to {date_str}", "factors": factors, "districts": []}

        result_rows = []
        for cd_id, group in df.groupby("cd_id"):
            avg_heat  = float(group["heat_index_risk"].mean())
            avg_hosp  = float(group["total_capacity_pct"].mean())
            avg_trans = float(group["transit_delay_index"].mean())

            # Must be above threshold on average across the window for all requested factors
            if "heat"     in factors and avg_heat  < HEAT_HIGH:     continue
            if "hospital" in factors and avg_hosp  < HOSPITAL_HIGH: continue
            if "transit"  in factors and avg_trans < TRANSIT_HIGH:   continue

            r = group.iloc[0]
            result_rows.append({
                "cd_id": str(cd_id),
                "district_name": str(r["neighborhood"]),
                "borough": str(r["borough"]),
                "avg_heat_index_risk": round(avg_heat, 2),
                "avg_total_capacity_pct": round(avg_hosp, 2),
                "avg_transit_delay_index": round(avg_trans, 2),
                "days_heat_elevated": int((group["heat_index_risk"]    >= HEAT_HIGH).sum()),
                "days_hospital_elevated": int((group["total_capacity_pct"] >= HOSPITAL_HIGH).sum()),
                "days_transit_elevated": int((group["transit_delay_index"] >= TRANSIT_HIGH).sum()),
                "total_days_in_window": len(group),
                "combined_pattern_summary": _main_risk_driver(avg_heat, avg_hosp, avg_trans),
            })

        result_rows.sort(
            key=lambda x: x["avg_heat_index_risk"] + x["avg_total_capacity_pct"] + x["avg_transit_delay_index"],
            reverse=True,
        )
        return {
            "date_range": f"{start_date} to {date_str}",
            "factors": factors,
            "condition": f"sustained_{condition}",
            "districts": result_rows[:top_k],
        }
    else:
        df = query_for_date(date_str)
        if "heat"     in factors: df = df[df["heat_index_risk"]    >= HEAT_HIGH]
        if "hospital" in factors: df = df[df["total_capacity_pct"] >= HOSPITAL_HIGH]
        if "transit"  in factors: df = df[df["transit_delay_index"] >= TRANSIT_HIGH]
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


# --- Tool 5: compare_to_historical_analogs ---


def compare_to_historical_analogs(cd_id: str, date_str: str, top_k: int = 5) -> dict:
    """Compare current district conditions to similar past days; return analogs and what happened next."""
    cd_id = cd_id.strip().upper()
    d = pd.to_datetime(date_str)
    analogs = get_historical_analogs(cd_id, d, top_k=top_k)
    return {"cd_id": cd_id, "date": date_str, "analogs": analogs}


# --- Tool 6: get_agency_coordination_recommendations ---


def get_agency_coordination_recommendations(cd_id: str, date_str: str) -> dict:
    """Map district risk factors to agencies to notify and suggested actions (rule-based)."""
    snap = get_cd_snapshot(cd_id, date_str)
    if "error" in snap:
        return snap
    heat  = snap["heat_index_risk"]
    hosp  = snap["total_capacity_pct"]
    trans = snap["transit_delay_index"]

    agencies = []
    reason   = []
    actions  = []
    urgency  = "moderate"

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


# --- Tool 7: get_multiyear_trend ---


def get_multiyear_trend(
    factor: str,
    cd_id: str | None = None,
    borough: str | None = None,
    month_start: int | None = None,
    month_end: int | None = None,
) -> dict:
    """Show how a risk factor has changed year-over-year for a CD or borough (2020–present).

    Use month_start/month_end to isolate a season (e.g. 6–8 for summer heat trend).
    Returns annual averages and a slope (units/year) to surface long-term divergence or decay.
    """
    if not cd_id and not borough:
        return {"error": "Provide either cd_id or borough."}

    col = {"heat": "heat_index_risk", "hospital": "total_capacity_pct", "transit": "transit_delay_index"}.get(factor)
    if not col:
        return {"error": f"Unknown factor: {factor}. Use heat, hospital, or transit."}

    if cd_id:
        cd_id = cd_id.strip().upper()
        df = query_full_history(cd_id=cd_id)
        scope = cd_id
    else:
        df = query_full_history(borough=borough)
        scope = borough

    if df.empty:
        return {"error": f"No data for {scope}"}

    if month_start is not None and month_end is not None:
        if month_start <= month_end:
            df = df[df["date"].dt.month.between(month_start, month_end)]
        else:
            # Cross-year range e.g. December–February
            df = df[(df["date"].dt.month >= month_start) | (df["date"].dt.month <= month_end)]
        month_label = f"months {month_start}–{month_end}"
    elif month_start is not None:
        df = df[df["date"].dt.month >= month_start]
        month_label = f"month {month_start} onward"
    elif month_end is not None:
        df = df[df["date"].dt.month <= month_end]
        month_label = f"through month {month_end}"
    else:
        month_label = "full year"

    if df.empty:
        return {"error": f"No data for {scope} in {month_label}"}

    df = df.copy()
    df["year"] = df["date"].dt.year
    yearly = df.groupby("year")[col].mean()

    years  = [int(y) for y in yearly.index]
    values = [round(float(v), 2) for v in yearly.values]

    slope = float(np.polyfit(years, values, 1)[0]) if len(years) >= 2 else 0.0

    return {
        "scope": scope,
        "factor": factor,
        "metric": col,
        "season": month_label,
        "annual_averages": {y: v for y, v in zip(years, values)},
        "slope_per_year": round(slope, 3),
        "total_change_over_period": round(values[-1] - values[0], 2) if len(values) >= 2 else 0.0,
        "trend_direction": "increasing" if slope > 0.05 else ("decreasing" if slope < -0.05 else "stable"),
        "years_covered": f"{years[0]}–{years[-1]}" if years else "none",
    }
