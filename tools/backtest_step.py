#!/usr/bin/env python3
"""
Backtest Step Diagnostic Tool
Runs a single step of run_step_live() on a specific timestamp with full diagnostics.
Uses EXACTLY the same logic as LIVE/PAPER (no analysis mode, no overrides).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.historical_prices import load_ohlcv_csv
from engine_alpha.data import live_prices
from engine_alpha.signals import signal_processor
from engine_alpha.core.regime import classify_regime
from engine_alpha.core.confidence_engine import decide
from engine_alpha.loop.autonomous_trader import run_step_live, MIN_CONF_LIVE, compute_entry_min_conf
from engine_alpha.loop.position_manager import get_live_position


def parse_iso8601(ts_str: str) -> datetime:
    """Parse ISO8601 string to timezone-aware datetime."""
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)


def find_candle_index(candles: List[Dict[str, Any]], target_ts: str) -> Optional[int]:
    """Find the index of the candle with the given timestamp."""
    for i, candle in enumerate(candles):
        if candle.get("ts") == target_ts:
            return i
    return None


def setup_mock_ohlcv(candles: List[Dict[str, Any]], current_idx: int, window: int = 200):
    """Set up mock get_live_ohlcv to return the window ending at current_idx."""
    def mock_get_live_ohlcv(symbol: str, timeframe: str, limit: int = 200, no_cache: bool = True):
        """Mock get_live_ohlcv to return candles from our CSV window."""
        # Return window ending at current_idx
        start_idx = max(0, current_idx - limit + 1)
        return candles[start_idx:current_idx + 1]
    
    # Store originals
    original_live_prices = live_prices.get_live_ohlcv
    original_signal_processor = None
    try:
        from engine_alpha.signals import signal_processor
        if hasattr(signal_processor, 'get_live_ohlcv'):
            original_signal_processor = signal_processor.get_live_ohlcv
            signal_processor.get_live_ohlcv = mock_get_live_ohlcv
    except ImportError:
        pass
    
    live_prices.get_live_ohlcv = mock_get_live_ohlcv
    
    return original_live_prices, original_signal_processor


def restore_mock_ohlcv(original_live_prices, original_signal_processor):
    """Restore original get_live_ohlcv functions."""
    live_prices.get_live_ohlcv = original_live_prices
    if original_signal_processor is not None:
        try:
            from engine_alpha.signals import signal_processor
            signal_processor.get_live_ohlcv = original_signal_processor
        except ImportError:
            pass


def print_regime_diagnostics(window: List[Dict[str, Any]], regime_result: Dict[str, Any]):
    """Print regime engine diagnostics."""
    print("\n" + "="*80)
    print("1. REGIME ENGINE")
    print("="*80)
    
    regime = regime_result.get("regime", "unknown")
    metrics = regime_result.get("metrics", {})
    
    print(f"\n📊 Final Regime: {regime}")
    print(f"\n📈 Regime Metrics:")
    for key, value in metrics.items():
        if isinstance(value, float):
            print(f"   {key:20s} = {value:.6f}")
        else:
            print(f"   {key:20s} = {value}")
    
    # Show price context
    if window:
        closes = [float(c.get("close", 0)) for c in window if c.get("close")]
        if closes:
            print(f"\n💰 Price Context:")
            print(f"   First close:  ${closes[0]:.2f}")
            print(f"   Last close:   ${closes[-1]:.2f}")
            print(f"   Change:       {((closes[-1] - closes[0]) / closes[0] * 100):.2f}%")
            print(f"   Window size:  {len(window)} candles")


def print_signal_diagnostics(decision: Dict[str, Any], final_score: float, effective_final_dir: int, effective_final_conf: float):
    """Print signal engine diagnostics."""
    print("\n" + "="*80)
    print("2. SIGNAL ENGINE")
    print("="*80)
    
    buckets = decision.get("buckets", {})
    final = decision.get("final", {})
    
    print(f"\n🪣 Bucket Details:")
    bucket_names = ["momentum", "meanrev", "flow", "positioning", "timing"]
    for bucket_name in bucket_names:
        bucket = buckets.get(bucket_name, {})
        dir_val = bucket.get("dir", 0)
        conf_val = bucket.get("conf", 0.0)
        weight_val = bucket.get("weight", 0.0)
        print(f"   {bucket_name:12s} | dir={dir_val:2d} | conf={conf_val:.4f} | weight={weight_val:.4f}")
    
    print(f"\n📊 Final Aggregation:")
    print(f"   final_score:        {final_score:.6f}")
    print(f"   final_dir (raw):    {final.get('dir', 0)}")
    print(f"   final_conf (raw):   {final.get('conf', 0.0):.4f}")
    print(f"   effective_dir:      {effective_final_dir}")
    print(f"   effective_conf:     {effective_final_conf:.2f}")


def print_entry_diagnostics(
    regime: str,
    regime_stats: Dict[str, Any],
    adapter_band: str,
    effective_min_conf_live: float,
    effective_final_dir: int,
    effective_final_conf: float,
    allow_opens: bool
):
    """Print entry logic diagnostics."""
    print("\n" + "="*80)
    print("3. ENTRY LOGIC")
    print("="*80)
    
    print(f"\n🎯 Entry Thresholds:")
    print(f"   MIN_CONF_LIVE (base):     {MIN_CONF_LIVE:.2f}")
    print(f"   effective_min_conf_live:  {effective_min_conf_live:.2f}")
    print(f"   risk_band:                {adapter_band}")
    
    print(f"\n🚪 Regime Gate:")
    regime_blocked = regime in ("chop", "trend_up")
    if regime_blocked:
        print(f"   ❌ BLOCKED: regime '{regime}' is not allowed for entries (LIVE/PAPER)")
    else:
        print(f"   ✅ ALLOWED: regime '{regime}' is allowed for entries")
    
    print(f"\n📊 Entry Decision:")
    print(f"   allow_opens:              {allow_opens}")
    print(f"   effective_final_dir:     {effective_final_dir}")
    print(f"   effective_final_conf:    {effective_final_conf:.2f}")
    
    if not allow_opens:
        print(f"   ❌ Entry blocked: allow_opens=False")
    elif effective_final_dir == 0:
        print(f"   ❌ Entry blocked: neutral signal (dir=0)")
    elif effective_final_conf < effective_min_conf_live:
        print(f"   ❌ Entry blocked: conf {effective_final_conf:.2f} < threshold {effective_min_conf_live:.2f}")
    elif regime_blocked:
        print(f"   ❌ Entry blocked: regime '{regime}' not allowed")
    else:
        print(f"   ✅ Entry ALLOWED: conf {effective_final_conf:.2f} >= threshold {effective_min_conf_live:.2f}")


def print_exit_diagnostics(
    live_pos: Optional[Dict[str, Any]],
    final: Dict[str, Any],
    gates: Dict[str, Any],
    regime: str,
    bars_open: int,
    decay_bars: int
):
    """Print exit logic diagnostics."""
    print("\n" + "="*80)
    print("4. EXIT LOGIC")
    print("="*80)
    
    if not live_pos or not live_pos.get("dir"):
        print("\n   ℹ️  No open position - exit logic not applicable")
        return
    
    pos_dir = live_pos.get("dir")
    final_dir = final.get("dir", 0)
    final_conf = final.get("conf", 0.0)
    
    take_profit_conf = gates.get("take_profit_conf", 0.60)
    stop_loss_conf = gates.get("stop_loss_conf", 0.50)
    exit_min_conf = gates.get("exit_min_conf", 0.30)
    reverse_min_conf = gates.get("reverse_min_conf", 0.60)
    
    print(f"\n📊 Position State:")
    print(f"   pos_dir:        {pos_dir}")
    print(f"   bars_open:      {bars_open}")
    print(f"   entry_px:       {live_pos.get('entry_px', 'N/A')}")
    
    print(f"\n🎯 Exit Thresholds:")
    print(f"   take_profit_conf:  {take_profit_conf:.2f}")
    print(f"   stop_loss_conf:    {stop_loss_conf:.2f}")
    print(f"   exit_min_conf:     {exit_min_conf:.2f}")
    print(f"   reverse_min_conf:  {reverse_min_conf:.2f}")
    print(f"   decay_bars:        {decay_bars}")
    
    print(f"\n📈 Current Signal:")
    print(f"   final_dir:      {final_dir}")
    print(f"   final_conf:     {final_conf:.4f}")
    
    # Evaluate exit conditions
    same_dir = final_dir != 0 and final_dir == pos_dir
    opposite_dir = final_dir != 0 and final_dir != pos_dir
    
    take_profit = same_dir and final_conf >= take_profit_conf
    stop_loss = opposite_dir and final_conf >= stop_loss_conf
    drop = final_conf < exit_min_conf
    flip = opposite_dir and final_conf >= reverse_min_conf
    decay = bars_open >= decay_bars
    
    print(f"\n🔍 Exit Conditions:")
    print(f"   same_dir:       {same_dir}")
    print(f"   opposite_dir:   {opposite_dir}")
    print(f"   take_profit:    {take_profit} (same_dir AND conf >= {take_profit_conf:.2f})")
    print(f"   stop_loss:      {stop_loss} (opposite_dir AND conf >= {stop_loss_conf:.2f})")
    print(f"   drop:            {drop} (conf < {exit_min_conf:.2f})")
    print(f"   flip:            {flip} (opposite_dir AND conf >= {reverse_min_conf:.2f})")
    print(f"   decay:           {decay} (bars_open >= {decay_bars})")
    
    # Determine which exit would fire
    exit_reason = None
    if stop_loss:
        exit_reason = "sl"
    elif decay:
        exit_reason = "decay"
    elif take_profit:
        exit_reason = "tp"
    elif flip:
        exit_reason = "reverse"
    elif drop:
        exit_reason = "drop"
    
    if exit_reason:
        print(f"\n   ✅ Exit would fire: {exit_reason}")
    else:
        print(f"\n   ❌ No exit condition met")


def main():
    parser = argparse.ArgumentParser(description="Run a single diagnostic backtest step")
    parser.add_argument("--symbol", required=True, help="Symbol (e.g., ETHUSDT)")
    parser.add_argument("--timeframe", required=True, help="Timeframe (e.g., 1h)")
    parser.add_argument("--timestamp", required=True, help="Target timestamp (ISO8601, e.g., 2021-05-12T14:00:00Z)")
    parser.add_argument("--csv", required=True, help="Path to CSV file")
    parser.add_argument("--window", type=int, default=200, help="Window size for signals (default: 200)")
    
    args = parser.parse_args()
    
    # Ensure we're in PAPER mode (same as LIVE/PAPER logic)
    os.environ.setdefault("MODE", "PAPER")
    # Explicitly disable analysis mode
    os.environ.pop("ANALYSIS_MODE", None)
    
    print("="*80)
    print("BACKTEST STEP DIAGNOSTIC TOOL")
    print("="*80)
    print(f"\n📋 Configuration:")
    print(f"   Symbol:      {args.symbol}")
    print(f"   Timeframe:   {args.timeframe}")
    print(f"   Timestamp:  {args.timestamp}")
    print(f"   CSV:        {args.csv}")
    print(f"   Window:     {args.window}")
    print(f"   MODE:       {os.getenv('MODE', 'PAPER')}")
    print(f"   ANALYSIS_MODE: {os.getenv('ANALYSIS_MODE', 'not set')}")
    
    # Load candles from CSV
    print(f"\n📂 Loading candles from CSV...")
    candles = load_ohlcv_csv(
        symbol=args.symbol,
        timeframe=args.timeframe,
        csv_path=args.csv
    )
    
    if len(candles) < args.window:
        print(f"❌ Error: Not enough candles ({len(candles)}) for window={args.window}")
        return 1
    
    # Find the target timestamp
    target_idx = find_candle_index(candles, args.timestamp)
    if target_idx is None:
        print(f"❌ Error: Timestamp '{args.timestamp}' not found in CSV")
        print(f"   Available timestamps: {candles[0].get('ts')} to {candles[-1].get('ts')}")
        return 1
    
    if target_idx < args.window - 1:
        print(f"⚠️  Warning: Need at least {args.window} candles before target timestamp")
        print(f"   Found {target_idx + 1} candles before target")
        print(f"   Using available candles: {target_idx + 1}")
    
    # Get the window ending at target_idx
    start_idx = max(0, target_idx - args.window + 1)
    window = candles[start_idx:target_idx + 1]
    current_bar = candles[target_idx]
    
    print(f"\n✅ Loaded {len(candles)} candles")
    print(f"   Target candle index: {target_idx}")
    print(f"   Window: [{start_idx}:{target_idx + 1}] ({len(window)} candles)")
    print(f"   Current bar: {current_bar.get('ts')}")
    
    # Set up mock get_live_ohlcv
    original_live_prices, original_signal_processor = setup_mock_ohlcv(candles, target_idx, args.window)
    
    try:
        # Parse timestamp for run_step_live
        bar_dt = parse_iso8601(args.timestamp)
        
        # Get regime classification (before calling run_step_live to show diagnostics)
        regime_result = classify_regime(window)
        regime = regime_result.get("regime", "unknown")
        regime_metrics = regime_result.get("metrics", {})
        
        # Get signal vector and decision (to show diagnostics)
        # Import after setting up mock
        from engine_alpha.loop.autonomous_trader import get_signal_vector_live
        out = get_signal_vector_live(symbol=args.symbol, timeframe=args.timeframe, limit=args.window)
        decision = decide(out["signal_vector"], out["raw_registry"])
        final = decision.get("final", {})
        # Compute final_score from final dict
        final_dir_raw = final.get("dir", 0)
        final_conf_raw = final.get("conf", 0.0)
        final_score = final_conf_raw * (1 if final_dir_raw > 0 else -1 if final_dir_raw < 0 else 0)
        
        # Apply neutral zone logic (same as run_step_live)
        from engine_alpha.loop.autonomous_trader import NEUTRAL_THRESHOLD
        score_abs = abs(final_score)
        if score_abs < NEUTRAL_THRESHOLD:
            effective_final_dir = 0
            effective_final_conf = score_abs
        else:
            effective_final_dir = 1 if final_score > 0 else -1
            effective_final_conf = min(score_abs, 1.0)
        
        # Round confidence (same as confidence_engine)
        from engine_alpha.core.confidence_engine import CONFIDENCE_DECIMALS
        effective_final_conf = round(effective_final_conf, CONFIDENCE_DECIMALS)
        
        # Get risk adapter info
        from engine_alpha.core.risk_adapter import evaluate as risk_eval
        adapter = risk_eval() or {}
        adapter_band = adapter.get("band") or "A"
        
        # Compute entry threshold
        atr_pct = regime_metrics.get("atr_pct", 0.0) or 0.0
        vol_expansion = regime_metrics.get("vol_expansion", 1.0) or 1.0
        regime_stats = {
            "atr_pct": atr_pct,
            "vol_expansion": vol_expansion,
        }
        effective_min_conf_live = compute_entry_min_conf(
            regime,
            adapter_band
        )
        
        # Get policy (read from policy.json or use defaults)
        policy_path = REPORTS / "policy.json"
        policy = {"allow_opens": True, "allow_pa": True}
        if policy_path.exists():
            try:
                with open(policy_path, "r") as f:
                    policy = json.load(f)
            except Exception:
                pass
        allow_opens = policy.get("allow_opens", True)
        
        # Get current position
        live_pos = get_live_position()
        
        # Get exit thresholds
        gates = decision.get("gates", {})
        from engine_alpha.loop.autonomous_trader import MIN_HOLD_BARS_LIVE
        decay_bars = int(os.getenv("DECAY_BARS", "12"))
        bars_open = live_pos.get("bars_open", 0) if live_pos else 0
        
        # Print diagnostics
        print_regime_diagnostics(window, regime_result)
        print_signal_diagnostics(decision, final_score, effective_final_dir, effective_final_conf)
        print_entry_diagnostics(
            regime, regime_stats, adapter_band, effective_min_conf_live,
            effective_final_dir, effective_final_conf, allow_opens
        )
        print_exit_diagnostics(live_pos, final, gates, regime, bars_open, decay_bars)
        
        # Now run the actual step
        print("\n" + "="*80)
        print("5. RUNNING run_step_live()")
        print("="*80)
        
        result = run_step_live(
            symbol=args.symbol,
            timeframe=args.timeframe,
            limit=args.window,
            bar_ts=args.timestamp,
            now=bar_dt
        )
        
        print("\n" + "="*80)
        print("6. RESULT JSON")
        print("="*80)
        print(json.dumps(result, indent=2, default=str))
        
        print("\n" + "="*80)
        print("✅ Diagnostic complete")
        print("="*80)
        
    finally:
        restore_mock_ohlcv(original_live_prices, original_signal_processor)
    
    return 0


if __name__ == "__main__":
    exit(main())

