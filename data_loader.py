"""
Load and validate NYC Urban Risk CSVs; expose shared dataframes for tools and analogs.
Data directory: hackathon/data/ (heat_index, hospital_capacity, transit_delays, community_districts).
"""
from pathlib import Path
import pandas as pd

# Data directory relative to this module
_DATA_DIR = Path(__file__).resolve().parent / "data"

# Shared dataframes (loaded on first access)
_heat_index: pd.DataFrame | None = None
_hospital_capacity: pd.DataFrame | None = None
_transit_delays: pd.DataFrame | None = None
_community_districts: pd.DataFrame | None = None
_combined: pd.DataFrame | None = None  # joined heat + hospital + transit on (cd_id, date)


def _load_csv(name: str, **kwargs) -> pd.DataFrame:
    path = _DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    df = pd.read_csv(path, **kwargs)
    return df


def _ensure_dates(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    if date_col in df.columns and df[date_col].dtype != "datetime64[ns]":
        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    return df


def load_heat_index() -> pd.DataFrame:
    """Load heat_index.csv; validate cd_id, date, heat_index_risk and key columns."""
    global _heat_index
    if _heat_index is not None:
        return _heat_index
    df = _load_csv("heat_index.csv")
    df = _ensure_dates(df)
    required = {"cd_id", "date", "temperature_f", "humidity_pct", "heat_index_f", "heat_index_risk"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"heat_index.csv missing columns: {missing}")
    # Basic validation: no duplicate (cd_id, date)
    dupes = df.duplicated(subset=["cd_id", "date"]).sum()
    if dupes:
        raise ValueError(f"heat_index.csv has {dupes} duplicate (cd_id, date) rows")
    _heat_index = df
    return _heat_index


def load_hospital_capacity() -> pd.DataFrame:
    """Load hospital_capacity.csv; validate cd_id, date, total_capacity_pct and key columns."""
    global _hospital_capacity
    if _hospital_capacity is not None:
        return _hospital_capacity
    df = _load_csv("hospital_capacity.csv")
    df = _ensure_dates(df)
    required = {"cd_id", "date", "total_capacity_pct", "icu_capacity_pct", "ed_wait_hours"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"hospital_capacity.csv missing columns: {missing}")
    dupes = df.duplicated(subset=["cd_id", "date"]).sum()
    if dupes:
        raise ValueError(f"hospital_capacity.csv has {dupes} duplicate (cd_id, date) rows")
    _hospital_capacity = df
    return _hospital_capacity


def load_transit_delays() -> pd.DataFrame:
    """Load transit_delays.csv; validate cd_id, date, transit_delay_index."""
    global _transit_delays
    if _transit_delays is not None:
        return _transit_delays
    df = _load_csv("transit_delays.csv")
    df = _ensure_dates(df)
    required = {"cd_id", "date", "transit_delay_index"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"transit_delays.csv missing columns: {missing}")
    dupes = df.duplicated(subset=["cd_id", "date"]).sum()
    if dupes:
        raise ValueError(f"transit_delays.csv has {dupes} duplicate (cd_id, date) rows")
    _transit_delays = df
    return _transit_delays


def load_community_districts() -> pd.DataFrame:
    """Load community_districts.csv; validate cd_id, borough, neighborhood."""
    global _community_districts
    if _community_districts is not None:
        return _community_districts
    df = _load_csv("community_districts.csv")
    required = {"cd_id", "borough", "community_district", "neighborhood"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"community_districts.csv missing columns: {missing}")
    _community_districts = df
    return _community_districts


def load_all() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load and validate all CSVs; return (heat_index, hospital_capacity, transit_delays, community_districts)."""
    heat = load_heat_index()
    hosp = load_hospital_capacity()
    transit = load_transit_delays()
    cds = load_community_districts()
    return heat, hosp, transit, cds


def get_combined() -> pd.DataFrame:
    """
    Single joined dataframe on (cd_id, date) with heat, hospital, and transit metrics.
    Use for snapshots and tools that need all factors. Includes community district lookup.
    """
    global _combined
    if _combined is not None:
        return _combined
    heat = load_heat_index()
    hosp = load_hospital_capacity()
    transit = load_transit_delays()
    cds = load_community_districts()
    # Join on (cd_id, date)
    combined = heat.merge(hosp, on=["cd_id", "date"], how="inner").merge(
        transit, on=["cd_id", "date"], how="inner"
    )
    combined = combined.merge(cds[["cd_id", "borough", "neighborhood"]], on="cd_id", how="left")
    _combined = combined
    return _combined


def get_data_dir() -> Path:
    """Return the data directory path."""
    return _DATA_DIR
