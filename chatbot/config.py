"""Paths and config for the chatbot. Load from env or default to hackathon/data."""
import os
from pathlib import Path

# Default: assume we run from 5381 or hackathon; data lives in hackathon/data
_THIS_DIR = Path(__file__).resolve().parent
HACKATHON_ROOT = _THIS_DIR.parent
DATA_DIR = Path(os.environ.get("NYC_RISK_DATA_DIR", str(HACKATHON_ROOT / "data")))

def get_data_path(name: str) -> Path:
    return DATA_DIR / name
