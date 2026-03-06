"""
Historical analogs: for a given (cd_id, date), find similar past days by
heat_index_risk, total_capacity_pct, transit_delay_index; include "what happened next".
Computed on demand; uses data from data_loader and get_combined().
"""
from __future__ import annotations

import pandas as pd
from data_loader import get_combined

# Normalization ranges for similarity (align with DATA_GENERATION.md)
_HEAT_RANGE = (0.0, 100.0)
_CAPACITY_RANGE = (0.0, 100.0)
# transit_delay_index can vary; use 0–10 as typical scale, cap for normalization
_TRANSIT_MAX = 10.0


def _normalize_series(s: pd.Series, low: float, high: float) -> pd.Series:
    out = (s - low) / (high - low) if high > low else s * 0
    return out.clip(0.0, 1.0)


def _similarity_row(
    row: pd.Series,
    ref_heat: float,
    ref_cap: float,
    ref_transit: float,
) -> float:
    """Euclidean distance in normalized 0–1 space; return 1 / (1 + distance) as similarity."""
    h = _normalize_series(pd.Series([row["heat_index_risk"]]), _HEAT_RANGE[0], _HEAT_RANGE[1]).iloc[0]
    c = _normalize_series(pd.Series([row["total_capacity_pct"]]), _CAPACITY_RANGE[0], _CAPACITY_RANGE[1]).iloc[0]
    t = _normalize_series(
        pd.Series([min(row["transit_delay_index"], _TRANSIT_MAX)]),
        0.0,
        _TRANSIT_MAX,
    ).iloc[0]
    ref_h = (ref_heat - _HEAT_RANGE[0]) / (_HEAT_RANGE[1] - _HEAT_RANGE[0])
    ref_h = max(0.0, min(1.0, ref_h))
    ref_c = (ref_cap - _CAPACITY_RANGE[0]) / (_CAPACITY_RANGE[1] - _CAPACITY_RANGE[0])
    ref_c = max(0.0, min(1.0, ref_c))
    ref_t = min(ref_transit, _TRANSIT_MAX) / _TRANSIT_MAX
    dist = ((h - ref_h) ** 2 + (c - ref_c) ** 2 + (t - ref_t) ** 2) ** 0.5
    return 1.0 / (1.0 + dist)


def get_analogs(
    cd_id: str,
    date: str | pd.Timestamp,
    top_k: int = 5,
    exclude_same_date: bool = True,
) -> list[dict]:
    """
    For (cd_id, date), return top-k similar historical (past) dates for the same CD,
    with similarity score and "what happened next" summary.

    Returns list of dicts: analog_date, similarity_score, what_happened_next (str), narrative (str).
    """
    combined = get_combined()
    combined["date"] = pd.to_datetime(combined["date"])
    if isinstance(date, str):
        date = pd.to_datetime(date)
    cd_df = combined.loc[combined["cd_id"] == cd_id].copy()
    if cd_df.empty:
        return []
    row_ref = cd_df.loc[cd_df["date"] == date]
    if row_ref.empty:
        return []
    ref = row_ref.iloc[0]
    ref_heat = float(ref["heat_index_risk"])
    ref_cap = float(ref["total_capacity_pct"])
    ref_transit = float(ref["transit_delay_index"])

    # Only past dates (strictly before `date`) for analogs
    past = cd_df.loc[cd_df["date"] < date].copy()
    if past.empty:
        return []

    past["similarity"] = past.apply(
        lambda r: _similarity_row(r, ref_heat, ref_cap, ref_transit),
        axis=1,
    )
    top = past.nlargest(top_k, "similarity")

    out = []
    for _, r in top.iterrows():
        analog_date = r["date"]
        sim = float(r["similarity"])
        whn = _what_happened_next(combined, cd_id, analog_date)
        narrative = _short_narrative(r, ref_heat, ref_cap, ref_transit, whn)
        out.append({
            "analog_date": analog_date.strftime("%Y-%m-%d"),
            "similarity_score": round(sim, 4),
            "what_happened_next": whn,
            "narrative": narrative,
        })
    return out


def _what_happened_next(combined: pd.DataFrame, cd_id: str, analog_date: pd.Timestamp, days_ahead: int = 7) -> str:
    """Summarize the next `days_ahead` days after analog_date for this CD."""
    combined = combined.copy()
    combined["date"] = pd.to_datetime(combined["date"])
    cd_df = combined.loc[combined["cd_id"] == cd_id].sort_values("date").reset_index(drop=True)
    idx = cd_df[cd_df["date"] == analog_date].index
    if len(idx) == 0:
        return "No follow-up data."
    i = int(idx[0])
    start = cd_df.iloc[i]
    # Next N days
    next_rows = cd_df.iloc[i + 1 : i + 1 + days_ahead]
    if next_rows.empty:
        return "No subsequent days in dataset."
    heat_delta = float(next_rows["heat_index_risk"].iloc[-1]) - float(start["heat_index_risk"])
    cap_delta = float(next_rows["total_capacity_pct"].iloc[-1]) - float(start["total_capacity_pct"])
    trans_delta = float(next_rows["transit_delay_index"].iloc[-1]) - float(start["transit_delay_index"])
    parts = []
    if abs(heat_delta) >= 1:
        parts.append(f"heat risk {heat_delta:+.1f}")
    if abs(cap_delta) >= 1:
        parts.append(f"hospital capacity {cap_delta:+.1f}%")
    if abs(trans_delta) >= 0.2:
        parts.append(f"transit delay index {trans_delta:+.2f}")
    if not parts:
        return "Conditions remained relatively stable over the following week."
    return "Over the next week: " + "; ".join(parts) + "."


def _short_narrative(
    row: pd.Series,
    ref_heat: float,
    ref_cap: float,
    ref_transit: float,
    whn: str,
) -> str:
    """One-line narrative for this analog."""
    parts = []
    if abs(float(row["heat_index_risk"]) - ref_heat) < 2:
        parts.append("similar heat")
    if abs(float(row["total_capacity_pct"]) - ref_cap) < 2:
        parts.append("similar hospital strain")
    if abs(float(row["transit_delay_index"]) - ref_transit) < 0.3:
        parts.append("similar transit disruption")
    summary = ", ".join(parts) if parts else "similar overall risk profile"
    return f"Historical match ({summary}). {whn}"
