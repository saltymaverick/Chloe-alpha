# engine_alpha/data/historical_prices.py

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from engine_alpha.core.paths import DATA

DATA_ROOT = DATA / "ohlcv"


@dataclass
class Candle:
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def _parse_ts(ts: str) -> datetime:
    # Accept "YYYY-MM-DDTHH:MM:SSZ" or "YYYY-MM-DD HH:MM:SS"
    t = ts.strip()
    if t.endswith("Z"):
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    # Fallback: naive → UTC
    return datetime.fromisoformat(t).replace(tzinfo=timezone.utc)


def load_ohlcv_csv(
    symbol: str,
    timeframe: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    csv_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Load OHLCV candles for backtesting from a CSV file.

    symbol: "ETHUSDT"
    timeframe: "1h" (not enforced here, but used for filename)
    start/end: ISO timestamps (inclusive start, exclusive end), or None
    csv_path: override to use a specific CSV; if None, infer from DATA_ROOT.
    """
    if csv_path:
        path = Path(csv_path)
    else:
        fname = f"{symbol}_{timeframe}_2019_2025.csv"
        path = DATA_ROOT / fname

    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    start_dt = _parse_ts(start) if start else None
    end_dt = _parse_ts(end) if end else None

    candles: List[Dict[str, Any]] = []

    with path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts_raw = row["ts"]
                dt = _parse_ts(ts_raw)
            except Exception:
                continue

            if start_dt and dt < start_dt:
                continue
            if end_dt and dt >= end_dt:
                continue

            try:
                candles.append(
                    {
                        "ts": dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row.get("volume", 0.0)),
                    }
                )
            except Exception:
                # skip malformed rows
                continue

    # Make sure sorted; just in case CSV not perfect
    candles.sort(key=lambda c: c["ts"])
    return candles





