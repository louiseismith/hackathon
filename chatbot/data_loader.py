"""
Load and validate CSVs; expose shared dataframes.
Compute week-over-week deltas for heat_index_risk, total_capacity_pct, transit_delay_index.
"""
from pathlib import Path
import pandas as pd

from .config import get_data_path

# Will be set by load_all()
cd_lookup: pd.DataFrame = pd.DataFrame()
heat_df: pd.DataFrame = pd.DataFrame()
hospital_df: pd.DataFrame = pd.DataFrame()
transit_df: pd.DataFrame = pd.DataFrame()
# WoW deltas: same index as merged (cd_id, date), columns like heat_index_risk_wow, etc.
wow_df: pd.DataFrame = pd.DataFrame()


def _load_csv(path: Path, date_cols: list[str] | None = None) -> pd.DataFrame:
    df = pd.read_csv(path)
    if date_cols:
        for c in date_cols:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def load_all() -> None:
    """Load and validate all CSVs; compute WoW deltas. Sets module-level dataframes."""
    global cd_lookup, heat_df, hospital_df, transit_df, wow_df

    cd_lookup = _load_csv(get_data_path("community_districts.csv"))
    heat_df = _load_csv(get_data_path("heat_index.csv"), ["date"])
    hospital_df = _load_csv(get_data_path("hospital_capacity.csv"), ["date"])
    transit_df = _load_csv(get_data_path("transit_delays.csv"), ["date"])

    # Validate
    for df, name, req in [
        (cd_lookup, "cd_lookup", ["cd_id", "borough", "community_district", "neighborhood"]),
        (heat_df, "heat", ["cd_id", "date", "temperature_f", "humidity_pct", "heat_index_f", "heat_index_risk"]),
        (hospital_df, "hospital", ["cd_id", "date", "total_capacity_pct", "icu_capacity_pct", "ed_wait_hours"]),
        (transit_df, "transit", ["cd_id", "date", "transit_delay_index"]),
    ]:
        missing = [c for c in req if c not in df.columns]
        if missing:
            raise ValueError(f"{name}: missing columns {missing}")
    if heat_df["date"].isna().any() or hospital_df["date"].isna().any() or transit_df["date"].isna().any():
        raise ValueError("Some date values are invalid")

    # Week-over-week deltas: for each (cd_id, date), subtract value from 7 days ago
    wow_df = _compute_wow_deltas()


def _compute_wow_deltas() -> pd.DataFrame:
    """Build a dataframe with (cd_id, date) and WoW change for heat_index_risk, total_capacity_pct, transit_delay_index."""
    # Merge to one row per (cd_id, date)
    merged = heat_df[["cd_id", "date", "heat_index_risk"]].merge(
        hospital_df[["cd_id", "date", "total_capacity_pct"]],
        on=["cd_id", "date"],
        how="inner",
    ).merge(
        transit_df[["cd_id", "date", "transit_delay_index"]],
        on=["cd_id", "date"],
        how="inner",
    )
    merged = merged.sort_values(["cd_id", "date"]).reset_index(drop=True)

    out = merged[["cd_id", "date"]].copy()
    for col, new_col in [
        ("heat_index_risk", "heat_index_risk_wow"),
        ("total_capacity_pct", "total_capacity_pct_wow"),
        ("transit_delay_index", "transit_delay_index_wow"),
    ]:
        prev = merged.groupby("cd_id")[col].shift(7)
        out[new_col] = merged[col] - prev

    return out


def ensure_loaded() -> None:
    """Call from tools: load data if not already loaded."""
    if heat_df.empty:
        load_all()
