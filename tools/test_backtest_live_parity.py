#!/usr/bin/env python3
"""
Test harness to verify backtest and live behavior match for the same candle sequence.

Feeds a known candle sequence into run_step_live twice:
1. Once in "live-like" mode (real get_live_ohlcv, but with historical data)
2. Once via backtest_harness mock

Asserts that decisions (open/close, dir, conf, pct) match.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.data.historical_prices import load_ohlcv_csv
from engine_alpha.data import live_prices
from engine_alpha.signals import signal_processor
from engine_alpha.loop.autonomous_trader import run_step_live
from engine_alpha.loop.execute_trade import set_trade_writer, TradeWriter
from engine_alpha.loop.position_manager import clear_live_position, clear_position


class CaptureTradeWriter(TradeWriter):
    """Trade writer that captures events for comparison."""
    def __init__(self):
        self.opens = []
        self.closes = []
    
    def write_open(self, event: dict) -> None:
        self.opens.append(event)
    
    def write_close(self, event: dict) -> None:
        self.closes.append(event)


def parse_iso8601(ts_str: str) -> datetime:
    """Parse ISO8601 string to timezone-aware datetime."""
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise ValueError(f"Invalid timestamp format: {ts_str}")


def run_live_like_mode(candles: list, target_idx: int, symbol: str, timeframe: str, window: int) -> dict:
    """Run in 'live-like' mode: patch get_live_ohlcv to return historical candles."""
    # Set up environment
    os.environ.setdefault("MODE", "PAPER")
    
    # Create mock that returns candles ending at target_idx
    def mock_get_live_ohlcv(symbol: str, timeframe: str, limit: int = 200, no_cache: bool = True):
        start_idx = max(0, target_idx - limit + 1)
        return candles[start_idx:target_idx + 1]
    
    # Patch functions
    original_get_live_ohlcv = live_prices.get_live_ohlcv
    live_prices.get_live_ohlcv = mock_get_live_ohlcv
    
    if hasattr(signal_processor, 'get_live_ohlcv'):
        original_signal_get_live_ohlcv = signal_processor.get_live_ohlcv
        signal_processor.get_live_ohlcv = mock_get_live_ohlcv
    else:
        original_signal_get_live_ohlcv = None
    
    # Set up trade writer
    writer = CaptureTradeWriter()
    set_trade_writer(writer)
    
    # Clear positions
    clear_live_position()
    clear_position()
    
    try:
        current_bar = candles[target_idx]
        bar_ts = current_bar["ts"]
        bar_dt = parse_iso8601(bar_ts)
        
        result = run_step_live(
            symbol=symbol,
            timeframe=timeframe,
            limit=window,
            bar_ts=bar_ts,
            now=bar_dt,
        )
        
        return {
            "result": result,
            "opens": writer.opens.copy(),
            "closes": writer.closes.copy(),
        }
    finally:
        # Restore
        live_prices.get_live_ohlcv = original_get_live_ohlcv
        if original_signal_get_live_ohlcv is not None:
            signal_processor.get_live_ohlcv = original_signal_get_live_ohlcv
        set_trade_writer(None)
        clear_live_position()
        clear_position()


def run_backtest_mode(candles: list, target_idx: int, symbol: str, timeframe: str, window: int) -> dict:
    """Run in backtest mode: use backtest_harness mock pattern."""
    # Set up environment (same as backtest_harness)
    os.environ.setdefault("MODE", "PAPER")
    os.environ["CHLOE_TRADES_PATH"] = str(Path("/tmp/test_backtest_trades.jsonl"))
    
    # Create mock with _current_bar_ts pattern (same as backtest_harness)
    _current_bar_ts = [candles[target_idx]["ts"]]
    
    def mock_get_live_ohlcv(symbol: str, timeframe: str, limit: int = 200, no_cache: bool = True):
        current_bar_ts = _current_bar_ts[0]
        current_idx = None
        for i, c in enumerate(candles):
            if c["ts"] == current_bar_ts:
                current_idx = i
                break
        if current_idx is None:
            return candles[-limit:] if len(candles) >= limit else candles
        start_idx = max(0, current_idx - limit + 1)
        return candles[start_idx:current_idx + 1]
    
    # Patch functions
    original_get_live_ohlcv = live_prices.get_live_ohlcv
    live_prices.get_live_ohlcv = mock_get_live_ohlcv
    
    if hasattr(signal_processor, 'get_live_ohlcv'):
        original_signal_get_live_ohlcv = signal_processor.get_live_ohlcv
        signal_processor.get_live_ohlcv = mock_get_live_ohlcv
    else:
        original_signal_get_live_ohlcv = None
    
    # Set up trade writer
    writer = CaptureTradeWriter()
    set_trade_writer(writer)
    
    # Clear positions
    clear_live_position()
    clear_position()
    
    try:
        current_bar = candles[target_idx]
        bar_ts = current_bar["ts"]
        bar_dt = parse_iso8601(bar_ts)
        
        result = run_step_live(
            symbol=symbol,
            timeframe=timeframe,
            limit=window,
            bar_ts=bar_ts,
            now=bar_dt,
        )
        
        return {
            "result": result,
            "opens": writer.opens.copy(),
            "closes": writer.closes.copy(),
        }
    finally:
        # Restore
        live_prices.get_live_ohlcv = original_get_live_ohlcv
        if original_signal_get_live_ohlcv is not None:
            signal_processor.get_live_ohlcv = original_signal_get_live_ohlcv
        set_trade_writer(None)
        os.environ.pop("CHLOE_TRADES_PATH", None)
        clear_live_position()
        clear_position()


def compare_results(live_result: dict, backtest_result: dict) -> bool:
    """Compare results from live-like and backtest modes."""
    print("\n" + "=" * 80)
    print("COMPARISON")
    print("=" * 80)
    
    live_r = live_result["result"]
    backtest_r = backtest_result["result"]
    
    # Compare regime
    live_regime = live_r.get("regime", "unknown")
    backtest_regime = backtest_r.get("regime", "unknown")
    regime_match = live_regime == backtest_regime
    print(f"\n📊 Regime:")
    print(f"   Live-like:    {live_regime}")
    print(f"   Backtest:     {backtest_regime}")
    print(f"   Match:        {'✅' if regime_match else '❌'}")
    
    # Compare final dir/conf
    live_final = live_r.get("final", {})
    backtest_final = backtest_r.get("final", {})
    live_dir = live_final.get("dir", 0)
    backtest_dir = backtest_final.get("dir", 0)
    live_conf = live_final.get("conf", 0.0)
    backtest_conf = backtest_final.get("conf", 0.0)
    
    dir_match = live_dir == backtest_dir
    conf_match = abs(live_conf - backtest_conf) < 0.01  # Allow small floating point differences
    
    print(f"\n📊 Final Decision:")
    print(f"   Live-like:    dir={live_dir} conf={live_conf:.4f}")
    print(f"   Backtest:     dir={backtest_dir} conf={backtest_conf:.4f}")
    print(f"   Dir match:    {'✅' if dir_match else '❌'}")
    print(f"   Conf match:   {'✅' if conf_match else '❌'}")
    
    # Compare opens
    live_opens = live_result["opens"]
    backtest_opens = backtest_result["opens"]
    opens_match = len(live_opens) == len(backtest_opens)
    
    print(f"\n📊 Opens:")
    print(f"   Live-like:    {len(live_opens)}")
    print(f"   Backtest:     {len(backtest_opens)}")
    print(f"   Match:        {'✅' if opens_match else '❌'}")
    
    # Compare closes
    live_closes = live_result["closes"]
    backtest_closes = backtest_result["closes"]
    closes_match = len(live_closes) == len(backtest_closes)
    
    print(f"\n📊 Closes:")
    print(f"   Live-like:    {len(live_closes)}")
    print(f"   Backtest:     {len(backtest_closes)}")
    print(f"   Match:        {'✅' if closes_match else '❌'}")
    
    # Compare PnL
    live_pnl = live_r.get("pnl", 0.0)
    backtest_pnl = backtest_r.get("pnl", 0.0)
    pnl_match = abs(live_pnl - backtest_pnl) < 0.0001
    
    print(f"\n💰 PnL:")
    print(f"   Live-like:    {live_pnl:.6f}")
    print(f"   Backtest:     {backtest_pnl:.6f}")
    print(f"   Match:        {'✅' if pnl_match else '❌'}")
    
    all_match = regime_match and dir_match and conf_match and opens_match and closes_match and pnl_match
    
    print("\n" + "=" * 80)
    if all_match:
        print("✅ ALL CHECKS PASSED - Live and backtest behavior match!")
    else:
        print("❌ MISMATCH DETECTED - Behavior differs between live and backtest")
    print("=" * 80)
    
    return all_match


def main():
    parser = argparse.ArgumentParser(description="Test parity between live and backtest modes")
    parser.add_argument("--symbol", default="ETHUSDT", help="Trading symbol")
    parser.add_argument("--timeframe", default="1h", help="Timeframe")
    parser.add_argument("--timestamp", required=True, help="Target timestamp (ISO8601)")
    parser.add_argument("--csv", required=True, help="Path to CSV file")
    parser.add_argument("--window", type=int, default=200, help="Window size")
    
    args = parser.parse_args()
    
    # Load candles
    candles = load_ohlcv_csv(args.symbol, args.timeframe, csv_path=args.csv)
    if len(candles) < args.window:
        print(f"❌ Error: Not enough candles ({len(candles)}) for window={args.window}")
        return 1
    
    # Find target candle
    target_idx = None
    for i, c in enumerate(candles):
        if c.get("ts") == args.timestamp:
            target_idx = i
            break
    
    if target_idx is None:
        print(f"❌ Error: Timestamp '{args.timestamp}' not found in CSV")
        return 1
    
    if target_idx < args.window - 1:
        print(f"⚠️  Warning: Not enough candles before target. Using {target_idx + 1} candles.")
    
    print("=" * 80)
    print("BACKTEST/LIVE PARITY TEST")
    print("=" * 80)
    print(f"\n📋 Configuration:")
    print(f"   Symbol:      {args.symbol}")
    print(f"   Timeframe:   {args.timeframe}")
    print(f"   Timestamp:   {args.timestamp}")
    print(f"   Window:      {args.window}")
    print(f"   Target idx:  {target_idx}")
    
    # Run in live-like mode
    print("\n" + "=" * 80)
    print("RUNNING IN LIVE-LIKE MODE")
    print("=" * 80)
    live_result = run_live_like_mode(candles, target_idx, args.symbol, args.timeframe, args.window)
    
    # Run in backtest mode
    print("\n" + "=" * 80)
    print("RUNNING IN BACKTEST MODE")
    print("=" * 80)
    backtest_result = run_backtest_mode(candles, target_idx, args.symbol, args.timeframe, args.window)
    
    # Compare
    all_match = compare_results(live_result, backtest_result)
    
    return 0 if all_match else 1


if __name__ == "__main__":
    sys.exit(main())


