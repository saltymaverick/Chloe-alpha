#!/usr/bin/env python3
"""
Regime Lab Backtest Tool
Tests each regime in isolation using the same entry/exit logic as live.
Only trades when the bar's regime matches the selected regime.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS
from engine_alpha.core.regime import classify_regime
from engine_alpha.data.historical_prices import load_ohlcv_csv
from engine_alpha.data import live_prices
from tools.backtest_common import (
    setup_backtest_environment,
    create_mock_get_live_ohlcv,
    summarize_trades,
    run_backtest_loop,
    parse_iso8601,
)


def run_regime_lab(
    symbol: str,
    timeframe: str,
    regime: str,
    start: str,
    end: str,
    csv_path: Optional[str] = None,
    window: int = 200,
) -> Path:
    """
    Run a regime-specific backtest.
    
    Only trades when the bar's regime matches the selected regime.
    Uses the same entry/exit logic as live (no LAB simplifications).
    """
    # Validate regime
    valid_regimes = {"trend_down", "trend_up", "chop", "high_vol", "panic_down"}
    if regime not in valid_regimes:
        raise ValueError(f"Invalid regime: {regime}. Must be one of {valid_regimes}")
    
    # 1. Load candles from CSV
    print(f"Loading OHLCV from CSV...")
    candles = load_ohlcv_csv(symbol, timeframe, start=start, end=end, csv_path=csv_path)
    if len(candles) < window:
        raise RuntimeError(f"Not enough candles ({len(candles)}) for window={window}")
    
    print(f"   ✅ Loaded {len(candles)} candles")
    
    # 2. Import run_step_live AFTER setting env vars
    from engine_alpha.loop.autonomous_trader import run_step_live
    
    # 3. Create run directory
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_dir = REPORTS / "backtest_regime" / f"{symbol}_{regime}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # 4. Set up paths
    trades_path = run_dir / "trades.jsonl"
    equity_curve_path = run_dir / "equity_curve.jsonl"
    
    # Clean up any existing files
    if trades_path.exists():
        trades_path.unlink()
    if equity_curve_path.exists():
        equity_curve_path.unlink()
    
    # 5. Set up backtest environment (PAPER mode, no BACKTEST_ANALYSIS)
    trade_writer, cleanup = setup_backtest_environment(
        run_dir=run_dir,
        trades_path=trades_path,
        mode="PAPER",
        backtest_analysis=False,  # Use real logic, not analysis mode
    )
    
    # 6. Write meta.json
    meta = {
        "symbol": symbol,
        "timeframe": timeframe,
        "regime": regime,
        "start": start,
        "end": end,
        "window": window,
        "ts": datetime.utcnow().isoformat() + "Z",
        "run_id": run_id,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    
    # 7. Set up mock get_live_ohlcv
    current_bar_ts_ref = [None]
    mock_get_live_ohlcv = create_mock_get_live_ohlcv(candles, current_bar_ts_ref)
    original_get_live_ohlcv = live_prices.get_live_ohlcv
    live_prices.get_live_ohlcv = mock_get_live_ohlcv
    
    try:
        # 8. Backtest loop with regime filtering
        equity = 10000.0
        initial_equity = equity
        
        def run_step_for_bar(bar: Dict[str, Any], bar_dt) -> Dict[str, Any]:
            """Run step only if bar's regime matches selected regime."""
            bar_ts = bar["ts"]
            current_bar_ts_ref[0] = bar_ts
            
            # Get window for regime classification
            current_idx = None
            for i, c in enumerate(candles):
                if c["ts"] == bar_ts:
                    current_idx = i
                    break
            
            if current_idx is None:
                return {"pnl": 0.0}
            
            # Get window ending at current bar (need at least window bars)
            if current_idx < window - 1:
                return {"pnl": 0.0}
            
            start_idx = max(0, current_idx - window + 1)
            window_rows = candles[start_idx:current_idx + 1]
            
            # Classify regime for this bar using real regime engine
            regime_result = classify_regime(window_rows)
            bar_regime = regime_result.get("regime", "chop")
            
            # Only trade if regime matches selected regime
            if bar_regime != regime:
                return {"pnl": 0.0}
            
            # Regime matches - run step with live logic
            result = run_step_live(
                symbol=symbol,
                timeframe=timeframe,
                limit=window,
                bar_ts=bar_ts,
                now=bar_dt,  # Pass simulated time for cooldown/guardrails
            )
            
            return result
        
        def progress_callback(processed: int, total: int):
            """Progress indicator."""
            if processed % max(1, total // 10) == 0:
                progress = (processed / total) * 100
                print(f"   Progress: {progress:.0f}% ({processed}/{total})")
        
        equity, bar_count = run_backtest_loop(
            candles=candles,
            window=window,
            run_step_fn=run_step_for_bar,
            equity_curve_path=equity_curve_path,
            start_equity=initial_equity,
            progress_callback=progress_callback,
        )
        
        print(f"   ✅ Processed {bar_count} bars")
        
        # 9. Compute summary
        summary = summarize_trades(trades_path, equity, initial_equity)
        summary.update({
            "symbol": symbol,
            "timeframe": timeframe,
            "regime": regime,
            "start": start,
            "end": end,
            "bars_processed": bar_count,
        })
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        
    finally:
        # 10. Cleanup
        live_prices.get_live_ohlcv = original_get_live_ohlcv
        cleanup()
    
    return run_dir


def main() -> None:
    """Main regime lab entry point."""
    parser = argparse.ArgumentParser(
        description="Chloe Regime Lab - Test each regime in isolation"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="ETHUSDT",
        help="Trading symbol (default: ETHUSDT)",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        help="Timeframe (default: 1h)",
    )
    parser.add_argument(
        "--regime",
        type=str,
        required=True,
        choices=["trend_down", "trend_up", "chop", "high_vol", "panic_down"],
        help="Regime to test in isolation",
    )
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start timestamp (ISO8601, e.g., 2021-01-01T00:00:00Z)",
    )
    parser.add_argument(
        "--end",
        type=str,
        required=True,
        help="End timestamp (ISO8601, e.g., 2023-01-01T00:00:00Z)",
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default=None,
        help="Path to CSV file (optional, defaults to data/ohlcv/{symbol}_{timeframe}_2019_2025.csv)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=200,
        help="Window size for regime/signal calculation (default: 200)",
    )
    
    args = parser.parse_args()
    
    try:
        run_dir = run_regime_lab(
            symbol=args.symbol,
            timeframe=args.timeframe,
            regime=args.regime,
            start=args.start,
            end=args.end,
            csv_path=args.csv_path,
            window=args.window,
        )
        print(f"\n✅ Regime lab backtest complete!")
        print(f"   Results: {run_dir}")
        print(f"\n📊 View summary:")
        print(f"   cat {run_dir / 'summary.json'}")
        print(f"\n📈 View detailed report:")
        print(f"   python3 -m tools.backtest_regime_report --run-dir {run_dir}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

