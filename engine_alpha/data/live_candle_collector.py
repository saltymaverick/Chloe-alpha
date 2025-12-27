"""
Live candle collector - Hybrid Self-Learning Mode

Persists every OHLCV bar seen by run_step_live into rolling CSV files for research.
"""

import csv
import os
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data" / "ohlcv"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _build_path(symbol: str, timeframe: str) -> Path:
    filename = f"{symbol.lower()}_{timeframe.lower()}_live.csv"
    return DATA_DIR / filename


def _normalize_candle(
    candle: Mapping,
    symbol: str,
    timeframe: str,
    source: str = "run_step_live",
) -> dict:
    """
    Normalize a candle dict into a flat row.

    Expected keys (flexible):
      - either 'ts' (ISO str) or 'open_time' (ms) or 'timestamp'
      - 'open', 'high', 'low', 'close', 'volume'
    """
    ts = candle.get("ts") or candle.get("timestamp") or candle.get("open_time")

    if isinstance(ts, (int, float)):
        # assume ms
        ts = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()
    elif isinstance(ts, datetime):
        ts = ts.astimezone(timezone.utc).isoformat()
    elif not isinstance(ts, str):
        ts = datetime.now(tz=timezone.utc).isoformat()

    return {
        "ts": ts,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "open": float(candle["open"]),
        "high": float(candle["high"]),
        "low": float(candle["low"]),
        "close": float(candle["close"]),
        "volume": float(candle.get("volume", 0.0)),
        "source": source,
    }


def record_live_candles(
    symbol: str,
    timeframe: str,
    candles: Iterable[Mapping],
    source: str = "run_step_live",
    dedupe: bool = True,
) -> Path:
    """
    Append live candles to the rolling CSV for (symbol, timeframe).

    This should be called from run_step_live right after OHLCV is fetched.

    candles: iterable of dicts with OHLCV data.
    """
    path = _build_path(symbol, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = [_normalize_candle(c, symbol, timeframe, source) for c in candles]

    # Optional dedupe by timestamp (in-file dedupe, cheap)
    existing_ts = set()
    if dedupe and path.exists():
        try:
            with path.open("r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing_ts.add(row["ts"])
        except Exception:
            # If reading fails, skip dedupe
            pass

    write_header = not path.exists()
    try:
        with path.open("a", newline="") as f:
            fieldnames = ["ts", "symbol", "timeframe", "open", "high", "low", "close", "volume", "source"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            if write_header:
                writer.writeheader()

            for row in rows:
                if (not dedupe) or (row["ts"] not in existing_ts):
                    writer.writerow(row)
    except Exception:
        # Fail silently - don't break live loop if history logging fails
        pass

    return path


