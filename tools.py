"""
NYC Urban Risk chatbot tools 1–4: get_cd_snapshot, get_top_risk_cds,
get_fastest_accelerating, get_factor_breakdown.
Uses data_loader and analogs; Pydantic schemas for args and results.
"""
from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from data_loader import get_combined, load_community_districts

# Factor names for ranking and filtering
FactorKind = Literal["heat", "hospital", "transit", "any"]

# Elevated thresholds (heat_index_risk 0–100; total_capacity_pct 0–100; transit_delay_index)
HEAT_ELEVATED = 50.0
CAPACITY_ELEVATED = 80.0  # high utilization = strain
TRANSIT_ELEVATED = 2.5


# ----- Tool 1: get_cd_snapshot -----

class GetCdSnapshotArgs(BaseModel):
    cd_id: str = Field(description="Community district ID, e.g. BX-03, MN-11")
    date: str = Field(description="Date in YYYY-MM-DD format")


class GetCdSnapshotResult(BaseModel):
    cd_id: str
    borough: str
    neighborhood: str
    date: str
    heat_index_risk: float
    temperature_f: float
    humidity_pct: float
    total_capacity_pct: float
    icu_capacity_pct: float
    ed_wait_hours: float
    transit_delay_index: float
    primary_concern: str  # "heat" | "hospital" | "transit" | "multi-factor" | "low"


def _primary_concern(heat: float, cap: float, transit: float) -> str:
    elevated = []
    if heat >= HEAT_ELEVATED:
        elevated.append("heat")
    if cap >= CAPACITY_ELEVATED:
        elevated.append("hospital")
    if transit >= TRANSIT_ELEVATED:
        elevated.append("transit")
    if len(elevated) > 1:
        return "multi-factor"
    if len(elevated) == 1:
        return elevated[0]
    return "low"


def get_cd_snapshot(cd_id: str, date: str) -> GetCdSnapshotResult | None:
    """
    Current or selected-date risk snapshot for one community district.
    Returns None if (cd_id, date) not found.
    """
    df = get_combined()
    df["date"] = pd.to_datetime(df["date"])
    dt = pd.to_datetime(date)
    row = df[(df["cd_id"] == cd_id) & (df["date"] == dt)]
    if row.empty:
        return None
    r = row.iloc[0]
    primary = _primary_concern(
        float(r["heat_index_risk"]),
        float(r["total_capacity_pct"]),
        float(r["transit_delay_index"]),
    )
    return GetCdSnapshotResult(
        cd_id=str(r["cd_id"]),
        borough=str(r["borough"]),
        neighborhood=str(r["neighborhood"]),
        date=str(r["date"].strftime("%Y-%m-%d")),
        heat_index_risk=float(r["heat_index_risk"]),
        temperature_f=float(r["temperature_f"]),
        humidity_pct=float(r["humidity_pct"]),
        total_capacity_pct=float(r["total_capacity_pct"]),
        icu_capacity_pct=float(r["icu_capacity_pct"]),
        ed_wait_hours=float(r["ed_wait_hours"]),
        transit_delay_index=float(r["transit_delay_index"]),
        primary_concern=primary,
    )


# ----- Tool 2: get_top_risk_cds -----

class GetTopRiskCdsArgs(BaseModel):
    date: str = Field(description="Date in YYYY-MM-DD format")
    top_k: int = Field(default=10, ge=1, le=59, description="Number of top districts to return")
    borough: str | None = Field(default=None, description="Optional borough to filter (e.g. Queens)")
    factor: FactorKind = Field(default="any", description="Rank by: heat, hospital, transit, or any (worst of three)")


class TopRiskCdEntry(BaseModel):
    cd_id: str
    district_name: str
    borough: str
    heat_index_risk: float
    total_capacity_pct: float
    transit_delay_index: float
    main_risk_driver: str


class GetTopRiskCdsResult(BaseModel):
    date: str
    entries: list[TopRiskCdEntry]


def _main_risk_driver(heat: float, cap: float, transit: float) -> str:
    """Single factor that is the dominant driver (highest relative to threshold)."""
    scores = []
    if HEAT_ELEVATED > 0:
        scores.append(("heat", heat / HEAT_ELEVATED))
    scores.append(("hospital", cap / CAPACITY_ELEVATED))
    scores.append(("transit", transit / TRANSIT_ELEVATED))
    best = max(scores, key=lambda x: x[1])
    return best[0] if best[1] >= 0.5 else "low"


def get_top_risk_cds(
    date: str,
    top_k: int = 10,
    borough: str | None = None,
    factor: FactorKind = "any",
) -> GetTopRiskCdsResult:
    """
    Highest-risk community districts for a given date, ranked by chosen factor or multi-factor.
    """
    df = get_combined()
    df["date"] = pd.to_datetime(df["date"])
    dt = pd.to_datetime(date)
    sub = df[df["date"] == dt].copy()
    if sub.empty:
        return GetTopRiskCdsResult(date=date, entries=[])
    if borough:
        sub = sub[sub["borough"].str.strip().str.lower() == borough.strip().lower()]
    if sub.empty:
        return GetTopRiskCdsResult(date=date, entries=[])

    if factor == "heat":
        sub = sub.sort_values("heat_index_risk", ascending=False).head(top_k)
    elif factor == "hospital":
        sub = sub.sort_values("total_capacity_pct", ascending=False).head(top_k)
    elif factor == "transit":
        sub = sub.sort_values("transit_delay_index", ascending=False).head(top_k)
    else:
        # "any": rank by max of normalized scores
        sub["_score"] = (
            sub["heat_index_risk"] / 100.0
            + sub["total_capacity_pct"] / 100.0
            + sub["transit_delay_index"].clip(upper=10) / 10.0
        )
        sub = sub.nlargest(top_k, "_score").drop(columns=["_score"], errors="ignore")

    entries = []
    for _, r in sub.iterrows():
        driver = _main_risk_driver(
            float(r["heat_index_risk"]),
            float(r["total_capacity_pct"]),
            float(r["transit_delay_index"]),
        )
        entries.append(
            TopRiskCdEntry(
                cd_id=str(r["cd_id"]),
                district_name=str(r["neighborhood"]),
                borough=str(r["borough"]),
                heat_index_risk=float(r["heat_index_risk"]),
                total_capacity_pct=float(r["total_capacity_pct"]),
                transit_delay_index=float(r["transit_delay_index"]),
                main_risk_driver=driver,
            )
        )
    return GetTopRiskCdsResult(date=date, entries=entries)


# ----- Tool 3: get_fastest_accelerating -----

class GetFastestAcceleratingArgs(BaseModel):
    date: str = Field(description="Reference date YYYY-MM-DD")
    window_days: int = Field(default=7, ge=1, le=90, description="Days back for prior value (e.g. 7 for WoW)")
    top_k: int = Field(default=10, ge=1, le=59)
    borough: str | None = Field(default=None)
    factor: FactorKind = Field(default="any", description="Which factor to rank by: heat, hospital, transit, any")


class AcceleratingEntry(BaseModel):
    cd_id: str
    heat_current: float
    heat_prior: float
    heat_delta: float
    hospital_current: float
    hospital_prior: float
    hospital_delta: float
    transit_current: float
    transit_prior: float
    transit_delta: float
    fastest_rising_factor: str
    heat_rising: bool
    hospital_rising: bool
    transit_rising: bool


class GetFastestAcceleratingResult(BaseModel):
    date: str
    window_days: int
    entries: list[AcceleratingEntry]


def get_fastest_accelerating(
    date: str,
    window_days: int = 7,
    top_k: int = 10,
    borough: str | None = None,
    factor: FactorKind = "any",
) -> GetFastestAcceleratingResult:
    """
    Districts where risk factors are rising the fastest (e.g. week-over-week).
    """
    df = get_combined()
    df["date"] = pd.to_datetime(df["date"])
    dt = pd.to_datetime(date)
    prior_dt = dt - pd.Timedelta(days=window_days)
    current = df[df["date"] == dt].copy()
    prior = df[df["date"] == prior_dt].set_index("cd_id")
    if current.empty or prior.empty:
        return GetFastestAcceleratingResult(date=date, window_days=window_days, entries=[])

    current = current[current["cd_id"].isin(prior.index)].copy()
    if current.empty:
        return GetFastestAcceleratingResult(date=date, window_days=window_days, entries=[])

    if borough:
        current = current[current["borough"].str.strip().str.lower() == borough.strip().lower()]
    if current.empty:
        return GetFastestAcceleratingResult(date=date, window_days=window_days, entries=[])

    # Deltas: for heat and hospital and transit, positive delta = worsening (risk up)
    current["heat_delta"] = current.apply(
        lambda r: float(r["heat_index_risk"]) - float(prior.loc[r["cd_id"], "heat_index_risk"]),
        axis=1,
    )
    current["hospital_delta"] = current.apply(
        lambda r: float(r["total_capacity_pct"]) - float(prior.loc[r["cd_id"], "total_capacity_pct"]),
        axis=1,
    )
    current["transit_delta"] = current.apply(
        lambda r: float(r["transit_delay_index"]) - float(prior.loc[r["cd_id"], "transit_delay_index"]),
        axis=1,
    )
    # Rank by worst acceleration: use max of (heat_delta, hospital_delta, transit_delta) when factor=="any"
    if factor == "heat":
        current = current.nlargest(top_k, "heat_delta")
    elif factor == "hospital":
        current = current.nlargest(top_k, "hospital_delta")
    elif factor == "transit":
        current = current.nlargest(top_k, "transit_delta")
    else:
        current["_max_delta"] = current[["heat_delta", "hospital_delta", "transit_delta"]].max(axis=1)
        current = current.nlargest(top_k, "_max_delta").drop(columns=["_max_delta"], errors="ignore")

    entries = []
    for _, r in current.iterrows():
        cd = r["cd_id"]
        pr = prior.loc[cd]
        h_cur = float(r["heat_index_risk"])
        h_pri = float(pr["heat_index_risk"])
        c_cur = float(r["total_capacity_pct"])
        c_pri = float(pr["total_capacity_pct"])
        t_cur = float(r["transit_delay_index"])
        t_pri = float(pr["transit_delay_index"])
        h_d = float(r["heat_delta"])
        c_d = float(r["hospital_delta"])
        t_d = float(r["transit_delta"])
        fastest = "heat" if h_d >= c_d and h_d >= t_d else ("hospital" if c_d >= t_d else "transit")
        entries.append(
            AcceleratingEntry(
                cd_id=str(cd),
                heat_current=h_cur,
                heat_prior=h_pri,
                heat_delta=round(h_d, 4),
                hospital_current=c_cur,
                hospital_prior=c_pri,
                hospital_delta=round(c_d, 4),
                transit_current=t_cur,
                transit_prior=t_pri,
                transit_delta=round(t_d, 4),
                fastest_rising_factor=fastest,
                heat_rising=h_d > 0,
                hospital_rising=c_d > 0,
                transit_rising=t_d > 0,
            )
        )
    return GetFastestAcceleratingResult(date=date, window_days=window_days, entries=entries)


# ----- Tool 4: get_factor_breakdown -----

class GetFactorBreakdownArgs(BaseModel):
    cd_id: str = Field(description="Community district ID")
    date: str = Field(description="Date YYYY-MM-DD")


class GetFactorBreakdownResult(BaseModel):
    cd_id: str
    date: str
    heat_index_risk: float
    total_capacity_pct: float
    transit_delay_index: float
    top_driver: str
    secondary_driver: str | None
    narrative: str


def get_factor_breakdown(cd_id: str, date: str) -> GetFactorBreakdownResult | None:
    """
    Explain which risk factors are driving concern in a district.
    """
    df = get_combined()
    df["date"] = pd.to_datetime(df["date"])
    dt = pd.to_datetime(date)
    row = df[(df["cd_id"] == cd_id) & (df["date"] == dt)]
    if row.empty:
        return None
    r = row.iloc[0]
    heat = float(r["heat_index_risk"])
    cap = float(r["total_capacity_pct"])
    transit = float(r["transit_delay_index"])

    # Rank factors by severity (how far above threshold)
    factors = [
        ("heat", heat, heat >= HEAT_ELEVATED),
        ("hospital", cap, cap >= CAPACITY_ELEVATED),
        ("transit", transit, transit >= TRANSIT_ELEVATED),
    ]
    # Order by magnitude (normalized) for drivers
    factors.sort(key=lambda x: (x[2], x[1]), reverse=True)
    elevated = [f[0] for f in factors if f[2]]
    top_driver = factors[0][0] if factors else "low"
    secondary = factors[1][0] if len(factors) > 1 and factors[1][2] else None
    if not elevated:
        narrative = "Risk factors are within normal ranges; no single driver elevated."
    elif len(elevated) == 1:
        narrative = f"{top_driver.capitalize()} is the primary concern (elevated)."
    else:
        narrative = f"{', '.join(e.capitalize() for e in elevated)} elevated; {top_driver.capitalize()} is the top driver."

    return GetFactorBreakdownResult(
        cd_id=str(r["cd_id"]),
        date=str(r["date"].strftime("%Y-%m-%d")),
        heat_index_risk=heat,
        total_capacity_pct=cap,
        transit_delay_index=transit,
        top_driver=top_driver,
        secondary_driver=secondary,
        narrative=narrative,
    )
