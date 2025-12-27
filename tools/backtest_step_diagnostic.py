#!/usr/bin/env python3
"""
Diagnostic tool to trace a single backtest step and compare with live behavior.
This helps identify where backtest logic diverges from live.
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


class DiagnosticTradeWriter(TradeWriter):
    """Trade writer that just logs to stdout."""
    def write_open(self, event: dict) -> None:
        print(f"\n🔵 TRADE OPEN: {json.dumps(event, indent=2)}")
    
    def write_close(self, event: dict) -> None:
        print(f"\n🔴 TRADE CLOSE: {json.dumps(event, indent=2)}")


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


def main():
    parser = argparse.ArgumentParser(description="Diagnostic tool for single backtest step")
    parser.add_argument("--symbol", default="ETHUSDT", help="Trading symbol")
    parser.add_argument("--timeframe", default="1h", help="Timeframe")
    parser.add_argument("--timestamp", required=True, help="Target timestamp (ISO8601)")
    parser.add_argument("--csv", required=True, help="Path to CSV file")
    parser.add_argument("--window", type=int, default=200, help="Window size")
    
    args = parser.parse_args()
    
    # Set up environment
    os.environ.setdefault("MODE", "PAPER")
    os.environ["DEBUG_SIGNALS"] = "1"
    os.environ["DEBUG_REGIME"] = "1"
    
    # Load candles
    print("=" * 80)
    print("BACKTEST STEP DIAGNOSTIC")
    print("=" * 80)
    print(f"\n📋 Configuration:")
    print(f"   Symbol:      {args.symbol}")
    print(f"   Timeframe:   {args.timeframe}")
    print(f"   Timestamp:   {args.timestamp}")
    print(f"   CSV:         {args.csv}")
    print(f"   Window:      {args.window}")
    print(f"   MODE:        {os.getenv('MODE', 'PAPER')}")
    
    candles = load_ohlcv_csv(args.symbol, args.timeframe, csv_path=args.csv)
    if len(candles) < args.window:
        print(f"\n❌ Error: Not enough candles ({len(candles)}) for window={args.window}")
        return 1
    
    # Find target candle
    target_idx = None
    for i, c in enumerate(candles):
        if c.get("ts") == args.timestamp:
            target_idx = i
            break
    
    if target_idx is None:
        print(f"\n❌ Error: Timestamp '{args.timestamp}' not found in CSV")
        print(f"   Available: {candles[0].get('ts')} to {candles[-1].get('ts')}")
        return 1
    
    if target_idx < args.window - 1:
        print(f"\n⚠️  Warning: Not enough candles before target. Using {target_idx + 1} candles.")
        window_start = 0
    else:
        window_start = target_idx - args.window + 1
    
    window_candles = candles[window_start:target_idx + 1]
    current_bar = candles[target_idx]
    
    print(f"\n✅ Loaded {len(candles)} candles")
    print(f"   Target index: {target_idx}")
    print(f"   Window: [{window_start}:{target_idx+1}] ({len(window_candles)} candles)")
    print(f"   Current bar: {current_bar.get('ts')} close={current_bar.get('close')}")
    
    # Set up mock
    _current_bar_ts = [args.timestamp]
    
    def mock_get_live_ohlcv(symbol: str, timeframe: str, limit: int = 200, no_cache: bool = True):
        """Mock get_live_ohlcv to return candles from our window."""
        current_bar_ts = _current_bar_ts[0]
        if not current_bar_ts:
            return window_candles[-limit:] if len(window_candles) >= limit else window_candles
        
        current_idx = None
        for i, c in enumerate(window_candles):
            if c["ts"] == current_bar_ts:
                current_idx = i
                break
        
        if current_idx is None:
            return window_candles[-limit:] if len(window_candles) >= limit else window_candles
        
        start_idx = max(0, current_idx - limit + 1)
        return window_candles[start_idx:current_idx + 1]
    
    # Patch functions
    original_get_live_ohlcv = live_prices.get_live_ohlcv
    live_prices.get_live_ohlcv = mock_get_live_ohlcv
    
    if hasattr(signal_processor, 'get_live_ohlcv'):
        original_signal_get_live_ohlcv = signal_processor.get_live_ohlcv
        signal_processor.get_live_ohlcv = mock_get_live_ohlcv
    else:
        original_signal_get_live_ohlcv = None
    
    # Set up trade writer
    set_trade_writer(DiagnosticTradeWriter())
    
    # Clear any existing positions
    clear_live_position()
    clear_position()
    
    try:
        # Run step
        print("\n" + "=" * 80)
        print("RUNNING run_step_live()")
        print("=" * 80)
        
        bar_dt = parse_iso8601(args.timestamp)
        result = run_step_live(
            symbol=args.symbol,
            timeframe=args.timeframe,
            limit=args.window,
            bar_ts=args.timestamp,
            now=bar_dt,
        )
        
        print("\n" + "=" * 80)
        print("RESULT")
        print("=" * 80)
        print(json.dumps(result, indent=2, default=str))
        
        # Analyze result
        print("\n" + "=" * 80)
        print("ANALYSIS")
        print("=" * 80)
        
        regime = result.get("regime", "unknown")
        final = result.get("final", {})
        final_dir = final.get("dir", 0)
        final_conf = final.get("conf", 0.0)
        
        print(f"\n📊 Regime: {regime}")
        print(f"📊 Final dir: {final_dir}")
        print(f"📊 Final conf: {final_conf:.4f}")
        
        risk_adapter = result.get("risk_adapter", {})
        risk_band = risk_adapter.get("band", "A")
        print(f"📊 Risk band: {risk_band}")
        
        # Check entry logic
        from engine_alpha.loop.autonomous_trader import compute_entry_min_conf, regime_allows_entry
        
        entry_min_conf = compute_entry_min_conf(regime, risk_band)
        allows_entry = regime_allows_entry(regime)
        
        print(f"\n🔍 Entry Analysis:")
        print(f"   Regime allows entry: {allows_entry}")
        print(f"   Entry min conf: {entry_min_conf:.2f}")
        print(f"   Final conf: {final_conf:.2f}")
        print(f"   Final dir: {final_dir}")
        print(f"   Would open: {allows_entry and final_dir != 0 and final_conf >= entry_min_conf}")
        
        pnl = result.get("pnl", 0.0)
        print(f"\n💰 PnL: {pnl:.6f}")
        
        if pnl != 0.0:
            print(f"   ✅ Trade closed!")
        else:
            print(f"   ⚠️  No trade closed")
        
    finally:
        # Restore
        live_prices.get_live_ohlcv = original_get_live_ohlcv
        if original_signal_get_live_ohlcv is not None:
            signal_processor.get_live_ohlcv = original_signal_get_live_ohlcv
        set_trade_writer(None)
        clear_live_position()
        clear_position()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())


