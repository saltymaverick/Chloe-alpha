#!/usr/bin/env python3
"""
Backfill OHLCV cache - Phase 23 (paper only).
"""

from __future__ import annotations

import argparse
import yaml

from engine_alpha.core.paths import CONFIG, DATA
from engine_alpha.data.historical_loader import load_ohlcv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=CONFIG / "backtest.yaml")
    args = parser.parse_args()

    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)
    symbols = cfg.get("symbols", [])
    timeframe = cfg.get("timeframe")
    start = cfg.get("start")
    end = cfg.get("end")

    for symbol in symbols:
        rows = load_ohlcv(symbol, timeframe, start, end, cfg)
        cache_path = DATA / "ohlcv" / f"{symbol}_{timeframe}.parquet"
        cache_note = cache_path if cache_path.exists() else "no_parquet_cache"
        print(f"Loaded {len(rows)} bars for {symbol} {timeframe} | cache={cache_note}")


if __name__ == "__main__":
    main()
