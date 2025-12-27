"""
Live candle history collector - Hybrid Self-Learning Mode

Captures every OHLCV bar seen by the live loop for inclusion in research datasets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

from engine_alpha.core.paths import DATA

LIVE_DIR = DATA / "live"
LIVE_DIR.mkdir(parents=True, exist_ok=True)


def append_live_bar(symbol: str, timeframe: str, candle: Dict[str, Any]) -> None:
    """
    Append a single OHLCV candle to data/live/{symbol}_{timeframe}.jsonl.

    Candle must include: ts, open, high, low, close, volume.
    Idempotent for duplicate ts: if last line has same ts, skip or overwrite.

    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        timeframe: Timeframe (e.g., "1h")
        candle: Dict with ts, open, high, low, close, volume, optionally source
    """
    try:
        file_path = LIVE_DIR / f"{symbol}_{timeframe}.jsonl"
        
        # Ensure candle has required fields
        ts = candle.get("ts")
        if not ts:
            return  # Skip if no timestamp
        
        # Build the record
        record = {
            "ts": ts,
            "symbol": symbol,
            "timeframe": timeframe,
            "open": float(candle.get("open", 0.0)),
            "high": float(candle.get("high", 0.0)),
            "low": float(candle.get("low", 0.0)),
            "close": float(candle.get("close", 0.0)),
            "volume": float(candle.get("volume", 0.0)),
            "source": candle.get("source", "live_loop"),
        }
        
        # Check if file exists and read last line to check for duplicates
        if file_path.exists():
            try:
                with file_path.open("r") as f:
                    lines = f.readlines()
                    if lines:
                        last_line = lines[-1].strip()
                        if last_line:
                            last_record = json.loads(last_line)
                            if last_record.get("ts") == ts:
                                # Duplicate timestamp - skip or overwrite
                                # We'll overwrite by removing the last line
                                lines = lines[:-1]
                                with file_path.open("w") as fw:
                                    fw.writelines(lines)
            except Exception:
                # If reading fails, just append
                pass
        
        # Append the new record
        with file_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
            
    except Exception:
        # Fail silently - don't break live loop if history logging fails
        pass


