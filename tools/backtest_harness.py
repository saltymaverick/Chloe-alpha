#!/usr/bin/env python3
"""
Backtest Harness - Upgraded for CSV-based historical backtesting
Replays historical candles from CSV through run_step_live for behavioral analysis.
Writes results to reports/backtest/* (separate from live reports).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.historical_prices import load_ohlcv_csv
from engine_alpha.loop.execute_trade import set_trade_writer, TradeWriter
# Note: run_step_live is imported later, after env vars may be set

# Confidence distribution logger for backtests
CONF_LOG_PATH = None
_CONF_LOG_WRITER = None
_CONF_LOG_FILE = None


def _init_conf_log(run_dir: Path):
    """Initialize confidence distribution CSV logger."""
    global CONF_LOG_PATH, _CONF_LOG_WRITER, _CONF_LOG_FILE
    CONF_LOG_PATH = run_dir / "conf_distribution.csv"
    _CONF_LOG_FILE = CONF_LOG_PATH.open("w", newline="")
    _CONF_LOG_WRITER = csv.writer(_CONF_LOG_FILE)
    _CONF_LOG_WRITER.writerow(["ts", "regime", "final_dir", "final_conf"])


def _log_conf_distribution(ts: str, regime: str, final_dir: int, final_conf: float):
    """Log confidence distribution data to CSV."""
    global _CONF_LOG_WRITER
    if _CONF_LOG_WRITER is not None:
        _CONF_LOG_WRITER.writerow([ts, regime, final_dir, final_conf])


def parse_iso8601(ts_str: str) -> datetime:
    """Parse ISO8601 string to timezone-aware datetime."""
    # Handle various formats
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        # Try parsing as timestamp
        try:
            ts = float(ts_str)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except ValueError:
            raise ValueError(f"Invalid timestamp format: {ts_str}")


def _summarize_trades(trades_path: Path, final_equity: float, start_equity: float) -> Dict[str, Any]:
    """Compute summary statistics from trades.jsonl, including regime breakdown."""
    import math
    from collections import defaultdict

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

    wins = [c["pct"] for c in closes if c["pct"] > 0]
    losses = [c["pct"] for c in closes if c["pct"] < 0]
    pos_sum = sum(wins)
    neg_sum = abs(sum(losses))

    pf = math.inf if neg_sum == 0 and pos_sum > 0 else (pos_sum / neg_sum if neg_sum > 0 else 0.0)

    # Compute regime breakdown
    regime_closes = defaultdict(list)
    for c in closes:
        regime = c.get("regime", "unknown")
        regime_closes[regime].append(c)
    
    regimes = {}
    for regime, regime_close_list in regime_closes.items():
        regime_wins = [c["pct"] for c in regime_close_list if c["pct"] > 0]
        regime_losses = [c["pct"] for c in regime_close_list if c["pct"] < 0]
        regime_pos_sum = sum(regime_wins)
        regime_neg_sum = abs(sum(regime_losses))
        regime_pf = (
            math.inf if regime_neg_sum == 0 and regime_pos_sum > 0
            else (regime_pos_sum / regime_neg_sum if regime_neg_sum > 0 else 0.0)
        )
        
        regimes[regime] = {
            "closes": len(regime_close_list),
            "wins": len(regime_wins),
            "losses": len(regime_losses),
            "pos_sum": regime_pos_sum,
            "neg_sum": -regime_neg_sum,
            "pf": regime_pf,
        }

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
        "pf_by_regime": regimes,  # Key renamed to match threshold_tuner spec
    }


def run_backtest(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    csv_path: Optional[str] = None,
    window: int = 200,
    explore: bool = False,
    weights_file: Optional[str] = None,
    allowed_regimes: Optional[List[str]] = None,
) -> Path:
    """
    Run a historical backtest over [start, end) using OHLCV from CSV,
    feeding windows of candles into run_step_live (backtest mode).
    Writes results into reports/backtest/<run_id>.
    """
    # 1. Load candles from CSV
    print(f"Loading OHLCV from CSV...")
    candles = load_ohlcv_csv(symbol, timeframe, start=start, end=end, csv_path=csv_path)
    if len(candles) < window:
        raise RuntimeError(f"Not enough candles ({len(candles)}) for window={window}")

    print(f"   ✅ Loaded {len(candles)} candles")

    # 2. Set up environment for backtest mode
    # Ensure backtest uses PAPER behavior (e.g., Phase 54 softening),
    # but without affecting LIVE mode.
    os.environ.setdefault("MODE", "PAPER")
    
    if weights_file:
        weights_path = Path(weights_file)
        if weights_path.exists():
            os.environ["COUNCIL_WEIGHTS_FILE"] = str(weights_path.absolute())
        else:
            print(f"⚠️  Warning: weights file not found: {weights_path}")

    if explore:
        os.environ.setdefault("MIN_CONF_LIVE", "0.40")
        os.environ.setdefault("COUNCIL_NEUTRAL_THRESHOLD", "0.15")
        print("Exploration mode: softer thresholds enabled for backtest only.")

    # 3. Import run_step_live AFTER setting env vars
    from engine_alpha.loop.autonomous_trader import run_step_live, regime_allows_entry
    from engine_alpha.data import live_prices
    
    # If allowed_regimes is specified, temporarily override regime_allows_entry for this backtest
    # This allows testing specific regimes (e.g., trend_up) without affecting live behavior
    original_regime_allows_entry = None
    if allowed_regimes is not None:
        original_regime_allows_entry = regime_allows_entry
        # Create a wrapper that checks allowed_regimes first
        def backtest_regime_allows_entry(regime: str) -> bool:
            return regime in allowed_regimes
        # Temporarily patch the function in the module
        import engine_alpha.loop.autonomous_trader as at_module
        at_module.regime_allows_entry = backtest_regime_allows_entry
        print(f"   🔬 Backtest mode: allowing entries only in regimes: {allowed_regimes}")
        print(f"      (This override applies only to this backtest run, not live trading)")

    # 4. Create run directory
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_dir = REPORTS / "backtest" / f"{symbol}_{timeframe}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # 5. Set CHLOE_TRADES_PATH to route trades to this backtest run's directory
    trades_path = run_dir / "trades.jsonl"
    equity_curve_path = run_dir / "equity_curve.jsonl"
    
    # Clean up any existing files from previous runs
    if trades_path.exists():
        trades_path.unlink()
    if equity_curve_path.exists():
        equity_curve_path.unlink()
    
    os.environ["CHLOE_TRADES_PATH"] = str(trades_path)
    
    # Phase: Stabilization - Backtests use the same code path as live
    # No special modes or overrides - backtests differ only in data source

    # 6. Write meta.json
    meta = {
        "symbol": symbol,
        "timeframe": timeframe,
        "start": start,
        "end": end,
        "window": window,
        "ts": datetime.utcnow().isoformat() + "Z",
        "run_id": run_id,
        "explore": explore,
        "allowed_regimes": allowed_regimes,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # 7. Initialize confidence distribution logger
    _init_conf_log(run_dir)

    # 7. Create backtest-specific trade writer
    class BacktestTradeWriter(TradeWriter):
        """Trade writer for backtest runs - writes to backtest directory."""
        def __init__(self, path: Path):
            self.path = path
            self.fh = open(path, "w", encoding="utf-8")
            self.closes = 0

        def write_open(self, event: dict) -> None:
            """Write an open event to backtest trades.jsonl."""
            self.fh.write(json.dumps(event) + "\n")
            self.fh.flush()

        def write_close(self, event: dict) -> None:
            """Write a close event to backtest trades.jsonl."""
            self.fh.write(json.dumps(event) + "\n")
            self.fh.flush()
            self.closes += 1

        def close(self) -> None:
            """Close the file handle."""
            try:
                self.fh.close()
            except Exception:
                pass

    # 8. Set up backtest trade writer
    backtest_writer = BacktestTradeWriter(trades_path)
    set_trade_writer(backtest_writer)

    # 9. Store original functions
    original_get_live_ohlcv = live_prices.get_live_ohlcv
    
    # Also patch the signal_processor import if it exists
    from engine_alpha.signals import signal_processor
    original_signal_processor_get_live_ohlcv = getattr(signal_processor, 'get_live_ohlcv', None)

    # 10. Create a mock function that returns the appropriate window
    def mock_get_live_ohlcv(symbol: str, timeframe: str, limit: int = 200, no_cache: bool = True):
        """Mock get_live_ohlcv to return candles from our CSV window."""
        # Find the current bar index
        current_bar_ts = _current_bar_ts[0] if _current_bar_ts else None
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

    # Thread-local storage for current bar timestamp
    _current_bar_ts = [None]

    # 11. Patch get_live_ohlcv function in both places
    live_prices.get_live_ohlcv = mock_get_live_ohlcv
    # Also patch in signal_processor module if it has a direct reference
    if hasattr(signal_processor, 'get_live_ohlcv'):
        signal_processor.get_live_ohlcv = mock_get_live_ohlcv

    try:
        # 12. Backtest loop
        equity = 10000.0
        initial_equity = equity
        
        with equity_curve_path.open("w") as eq_file:
            # Write initial equity point
            eq_file.write(json.dumps({"ts": candles[0]["ts"], "equity": equity}) + "\n")
            
            # Process bars starting from window index
            bar_count = 0
            for i in range(window - 1, len(candles)):
                current_bar = candles[i]
                bar_ts = current_bar["ts"]
                _current_bar_ts[0] = bar_ts

                try:
                    # Parse bar timestamp to datetime for cooldown/guardrails
                    bar_dt = parse_iso8601(bar_ts)
                    
                    # Call run_step_live with the historical bar timestamp and datetime
                    result = run_step_live(
                        symbol=symbol,
                        timeframe=timeframe,
                        limit=window,
                        bar_ts=bar_ts,
                        now=bar_dt,  # Pass simulated time for cooldown/guardrails
                    )

                    # Extract PnL from result (only non-zero when a close happens)
                    pnl = 0.0
                    if isinstance(result, dict):
                        # PnL should only be set when a close event fires
                        pnl = result.get("pnl", 0.0) or 0.0
                        
                        # Log confidence distribution for this bar
                        regime = result.get("regime", "unknown")
                        final = result.get("final", {})
                        final_dir = final.get("dir", 0)
                        final_conf = float(final.get("conf", 0.0))
                        _log_conf_distribution(bar_ts, regime, final_dir, final_conf)

                    # Only update equity when a close happens (pnl != 0)
                    if pnl != 0.0:
                        equity *= (1.0 + pnl)

                    # Record equity point
                    eq_file.write(json.dumps({"ts": bar_ts, "equity": equity}) + "\n")

                    bar_count += 1

                    # Progress indicator
                    if (i + 1) % max(1, (len(candles) - window + 1) // 10) == 0:
                        progress = ((i + 1 - window + 1) / (len(candles) - window + 1)) * 100
                        print(f"   Progress: {progress:.0f}% ({i + 1 - window + 1}/{len(candles) - window + 1})")

                except Exception as e:
                    print(f"   ⚠️  Error processing candle {i + 1} (ts={bar_ts}): {e}")
                    continue

        print(f"   ✅ Processed {bar_count} bars")

        # 13. Close backtest writer
        backtest_writer.close()

        # 14. Compute summary
        summary = _summarize_trades(trades_path, equity, initial_equity)
        summary.update({
            "symbol": symbol,
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "bars_processed": bar_count,
        })
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    finally:
        # Restore original regime_allows_entry if we overrode it (always restore, even on error)
        if original_regime_allows_entry is not None:
            import engine_alpha.loop.autonomous_trader as at_module
            at_module.regime_allows_entry = original_regime_allows_entry
        
        # Restore original get_live_ohlcv functions
        live_prices.get_live_ohlcv = original_get_live_ohlcv
        if original_signal_processor_get_live_ohlcv is not None:
            signal_processor.get_live_ohlcv = original_signal_processor_get_live_ohlcv
        
        # Unset CHLOE_TRADES_PATH to restore default behavior
        os.environ.pop("CHLOE_TRADES_PATH", None)
        
        # Close confidence log file
        global _CONF_LOG_FILE
        if _CONF_LOG_FILE is not None:
            _CONF_LOG_FILE.close()
            _CONF_LOG_FILE = None

    return run_dir


def main() -> None:
    """Main backtest harness entry point."""
    parser = argparse.ArgumentParser(
        description="Chloe Backtest Harness - CSV-based historical backtesting"
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
        "--start",
        type=str,
        required=True,
        help="Start timestamp (ISO8601, e.g., 2019-01-01T00:00:00Z)",
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
    parser.add_argument(
        "--explore",
        action="store_true",
        help="Enable exploration mode (softer thresholds) for backtest only",
    )
    parser.add_argument(
        "--weights-file",
        type=str,
        help="Path to council_weights.yaml file to use (for learning experiments)",
    )
    parser.add_argument(
        "--regimes",
        type=str,
        nargs="+",
        help="Allow entries only in specified regimes for this backtest (e.g., --regimes trend_up). "
             "This does NOT affect live trading. Use to test unproven regimes safely.",
    )

    args = parser.parse_args()

    try:
        run_dir = run_backtest(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            csv_path=args.csv_path,
            window=args.window,
            explore=args.explore,
            weights_file=args.weights_file,
            allowed_regimes=args.regimes,
        )
        print(f"\n✅ Backtest complete!")
        print(f"   Results: {run_dir}")
        print(f"\n📊 View summary:")
        print(f"   cat {run_dir / 'summary.json'}")
        print(f"\n📈 View regime PF breakdown:")
        print(f"   python3 -m tools.backtest_report --run-dir {run_dir}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
