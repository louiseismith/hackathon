"""
Historical analogs: for a given (cd_id, date), find similar past days and "what happened next".
On-demand computation (per CD only) to avoid huge precompute.
"""
import pandas as pd
import numpy as np

from .data_loader import query_cd_history

# Normalized columns for similarity (0-100 scale or similar)
FEATURE_COLS = ["heat_index_risk", "total_capacity_pct", "transit_delay_index"]


def _get_cd_merged(cd_id: str) -> pd.DataFrame:
    """Fetch full history for one CD from Supabase."""
    return query_cd_history(cd_id)


def _similarity_row(target: pd.Series, candidate: pd.Series) -> float:
    """Euclidean distance in normalized feature space (negated so higher = more similar). Use 1 / (1 + dist)."""
    t = target[FEATURE_COLS].astype(float)
    c = candidate[FEATURE_COLS].astype(float)
    dist = np.sqrt(((t - c) ** 2).sum())
    return 1.0 / (1.0 + dist)


def get_historical_analogs(cd_id: str, date: pd.Timestamp, top_k: int = 5) -> list[dict]:
    """
    For (cd_id, date), return top-k similar historical dates (excluding same date and future).
    Each result: {date, similarity_score, what_happened_next: str}.
    """
    merged = _get_cd_merged(cd_id)
    if merged.empty:
        return []

    target_date = pd.Timestamp(date)
    if target_date not in merged["date"].values:
        return []

    target_row = merged[merged["date"] == target_date].iloc[0]
    # Only past dates (strictly before target_date)
    past = merged[merged["date"] < target_date].copy()
    if past.empty:
        return []

    past["similarity"] = past.apply(lambda r: _similarity_row(target_row, r), axis=1)
    top = past.nlargest(top_k, "similarity")

    results = []
    for _, row in top.iterrows():
        hist_date = row["date"]
        sim = float(row["similarity"])
        # What happened next: 7 days after hist_date, same CD
        next_date = hist_date + pd.Timedelta(days=7)
        next_rows = merged[merged["date"] == next_date]
        if next_rows.empty:
            next_rows = merged[merged["date"] > hist_date].head(1)
        what_next = "No follow-up data in range."
        if not next_rows.empty:
            n = next_rows.iloc[0]
            parts = []
            if n["heat_index_risk"] > 50:
                parts.append(f"heat index risk was {n['heat_index_risk']:.0f}")
            if n["total_capacity_pct"] > 85:
                parts.append(f"hospital capacity was {n['total_capacity_pct']:.0f}%")
            if n["transit_delay_index"] > 30:
                parts.append(f"transit delay index was {n['transit_delay_index']:.0f}")
            what_next = "Seven days later: " + ("; ".join(parts)) if parts else "Seven days later: conditions moderated."
        results.append({
            "date": str(hist_date.date()),
            "similarity_score": round(sim, 4),
            "what_happened_next": what_next,
        })
    return results
