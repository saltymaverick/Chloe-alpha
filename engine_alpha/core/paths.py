# engine_alpha/core/paths.py
from pathlib import Path

# Project root two levels up from here (/root/Chloe-alpha)
ROOT = Path(__file__).resolve().parents[2]

REPORTS = ROOT / "reports"
LOGS    = ROOT / "logs"
DATA    = ROOT / "data"
CONFIG  = ROOT / "config"

# Ensure dirs exist
for p in (REPORTS, LOGS, DATA):
    p.mkdir(parents=True, exist_ok=True)
