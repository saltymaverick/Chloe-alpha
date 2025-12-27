"""
Regime Lab Configuration
Curated windows for regime-specific backtesting labs.
These are presets for analysis, not behavior changes.
"""

from typing import Dict, Any

REGIME_LAB_WINDOWS: Dict[str, Dict[str, Any]] = {
    "trend_up_mvp": {
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "start": "2021-01-01T00:00:00Z",
        "end": "2021-03-15T00:00:00Z",
        "notes": "ETH early 2021 bull run",
    },
    "trend_down_mvp": {
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "start": "2022-04-01T00:00:00Z",
        "end": "2022-06-30T00:00:00Z",
        "notes": "2022 drawdown period",
    },
    "chop_sample": {
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "start": "2021-05-01T00:00:00Z",
        "end": "2021-06-15T00:00:00Z",
        "notes": "Sample chop period for analysis",
    },
}


