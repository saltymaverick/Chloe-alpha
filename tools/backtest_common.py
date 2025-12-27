#!/usr/bin/env python3
"""
Backtest Common Utilities
Shared logic for backtest harnesses (full backtest and regime lab).
"""

from __future__ import annotations

import json
import os
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.historical_prices import load_ohlcv_csv
from engine_alpha.loop.execute_trade import set_trade_writer, TradeWriter
from engine_alpha.data import live_prices


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
        try:
            ts = float(ts_str)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except ValueError:
            raise ValueError(f"Invalid timestamp format: {ts_str}")


def setup_backtest_environment(
    run_dir: Path,
    trades_path: Path,
    mode: str = "PAPER",
    backtest_analysis: bool = False,
) -> tuple[TradeWriter, Callable]:
    """
    Set up environment for backtest run.
    
    Returns:
        (trade_writer, cleanup_function)
    """
    # Set mode
    os.environ.setdefault("MODE", mode)
    
    # Set trade path
    os.environ["CHLOE_TRADES_PATH"] = str(trades_path)
    
    # Set BACKTEST_ANALYSIS if requested
    if backtest_analysis:
        os.environ["BACKTEST_ANALYSIS"] = "1"
    else:
        os.environ.pop("BACKTEST_ANALYSIS", None)
    
    # Create trade writer
    class BacktestTradeWriter(TradeWriter):
        """Trade writer for backtest runs."""
        def __init__(self, path: Path):
            self.path = path
            self.fh = open(path, "w", encoding="utf-8")
            self.closes = 0

        def write_open(self, event: dict) -> None:
            self.fh.write(json.dumps(event) + "\n")
            self.fh.flush()

        def write_close(self, event: dict) -> None:
            self.fh.write(json.dumps(event) + "\n")
            self.fh.flush()
            self.closes += 1

        def close(self) -> None:
            try:
                self.fh.close()
            except Exception:
                pass
    
    trade_writer = BacktestTradeWriter(trades_path)
    set_trade_writer(trade_writer)
    
    # Store original get_live_ohlcv
    original_get_live_ohlcv = live_prices.get_live_ohlcv
    
    def cleanup():
        """Restore original functions and clear env vars."""
        live_prices.get_live_ohlcv = original_get_live_ohlcv
        set_trade_writer(None)
        os.environ.pop("CHLOE_TRADES_PATH", None)
        if backtest_analysis:
            os.environ.pop("BACKTEST_ANALYSIS", None)
        trade_writer.close()
    
    return trade_writer, cleanup


def create_mock_get_live_ohlcv(candles: List[Dict[str, Any]], current_bar_ts_ref: List[Optional[str]]):
    """
    Create a mock get_live_ohlcv function for backtesting.
    
    Args:
        candles: List of OHLCV candle dicts
        current_bar_ts_ref: List with single element [current_bar_ts] for state
    
    Returns:
        Mock function that returns appropriate window
    """
    def mock_get_live_ohlcv(symbol: str, timeframe: str, limit: int = 200, no_cache: bool = True):
        """Mock get_live_ohlcv to return candles from CSV window."""
        current_bar_ts = current_bar_ts_ref[0] if current_bar_ts_ref else None
        if not current_bar_ts:
            # Return first window
            return candles[:limit]
        
        # Find index of current bar
        current_idx = None
        for i, c in enumerate(candles):
            if c["ts"] == current_bar_ts:
                current_idx = i
                break
        
        if current_idx is None:
            # Fallback: return last window
            return candles[-limit:] if len(candles) >= limit else candles
        
        # Return window ending at current bar
        start_idx = max(0, current_idx - limit + 1)
        return candles[start_idx:current_idx + 1]
    
    return mock_get_live_ohlcv


def summarize_trades(trades_path: Path, final_equity: float, start_equity: float) -> Dict[str, Any]:
    """Compute summary statistics from trades.jsonl."""
    closes = []
    with trades_path.open("r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                t = json.loads(line)
                if t.get("type") == "close":
                    closes.append(t)
            except Exception:
                continue

    wins = [c["pct"] for c in closes if c.get("pct", 0) > 0]
    losses = [c["pct"] for c in closes if c.get("pct", 0) < 0]
    pos_sum = sum(wins)
    neg_sum = abs(sum(losses))

    pf = math.inf if neg_sum == 0 and pos_sum > 0 else (pos_sum / neg_sum if neg_sum > 0 else 0.0)

    return {
        "closes": len(closes),
        "wins": len(wins),
        "losses": len(losses),
        "pos_sum": pos_sum,
        "neg_sum": -neg_sum,
        "pf": pf,
        "start_equity": start_equity,
        "final_equity": final_equity,
        "change_pct": (final_equity / start_equity - 1) * 100.0,
    }


def run_backtest_loop(
    candles: List[Dict[str, Any]],
    window: int,
    run_step_fn: Callable,
    equity_curve_path: Path,
    start_equity: float = 10000.0,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> tuple[float, int]:
    """
    Run backtest loop over candles.
    
    Args:
        candles: List of OHLCV candle dicts
        window: Lookback window size
        run_step_fn: Function to call for each bar: run_step_fn(bar, bar_dt) -> result_dict
        equity_curve_path: Path to write equity curve JSONL
        start_equity: Starting equity
        progress_callback: Optional callback(processed, total)
    
    Returns:
        (final_equity, bars_processed)
    """
    equity = start_equity
    
    with equity_curve_path.open("w") as eq_file:
        # Write initial equity point
        eq_file.write(json.dumps({"ts": candles[0]["ts"], "equity": equity}) + "\n")
        
        # Process bars starting from window index
        bar_count = 0
        total_bars = len(candles) - window + 1
        
        for i in range(window - 1, len(candles)):
            current_bar = candles[i]
            bar_ts = current_bar["ts"]
            
            try:
                # Parse bar timestamp to datetime
                bar_dt = parse_iso8601(bar_ts)
                
                # Call run_step function
                result = run_step_fn(current_bar, bar_dt)
                
                # Extract PnL from result (only non-zero when a close happens)
                pnl = 0.0
                if isinstance(result, dict):
                    pnl = result.get("pnl", 0.0) or 0.0
                
                # Only update equity when a close happens (pnl != 0)
                if pnl != 0.0:
                    equity *= (1.0 + pnl)
                
                # Record equity point
                eq_file.write(json.dumps({"ts": bar_ts, "equity": equity}) + "\n")
                
                bar_count += 1
                
                # Progress callback
                if progress_callback:
                    progress_callback(bar_count, total_bars)
                
            except Exception as e:
                print(f"   ⚠️  Error processing candle {i + 1} (ts={bar_ts}): {e}")
                continue
    
    return equity, bar_count


