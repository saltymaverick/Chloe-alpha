#!/usr/bin/env python3
"""
PF Local Writer
---------------

Computes PF for last 1d/7d/30d windows from reports/trades.jsonl close events
and writes reports/pf_local.json.

This ensures the check-in script always has fresh PF data.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.trade_sanity import filter_corrupted, is_close_like_event
from engine_alpha.research.pf_timeseries import _extract_return, _compute_pf_for_window

EPS = 1e-12


def _safe_parse_ts(ts: any) -> datetime | None:
    """Parse timestamp from various formats."""
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(ts, fmt).astimezone(timezone.utc)
            except Exception:
                continue
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None
    return None


def compute_pf_local() -> dict[str, any]:
    """
    Compute PF for 1d/7d/30d windows from trades.jsonl.
    
    Returns:
        Dict with pf_24h, pf_7d, pf_30d, and counts
    """
    trades_path = REPORTS / "trades.jsonl"
    if not trades_path.exists():
        return {
            "pf_24h": None,
            "pf_7d": None,
            "pf_30d": None,
            "count_24h": 0,
            "count_7d": 0,
            "count_30d": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    
    # Load and filter corrupted events
    trades = []
    try:
        with trades_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    trades.append(trade)
                except Exception:
                    continue
    except Exception:
        pass
    
    # Filter corrupted events (analytics-only)
    trades = filter_corrupted(trades)
    
    # Filter to close-like events only
    close_trades = []
    now = datetime.now(timezone.utc)
    
    for trade in trades:
        if not is_close_like_event(trade):
            continue
        
        ts = _safe_parse_ts(trade.get("ts") or trade.get("timestamp"))
        if ts is None:
            continue
        
        trade["_ts_dt"] = ts
        close_trades.append(trade)
    
    # Sort by timestamp
    close_trades.sort(key=lambda x: x["_ts_dt"])
    
    # Compute PF for each window
    windows = {
        "24h": timedelta(days=1),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    
    result = {
        "generated_at": now.isoformat(),
    }
    
    for window_name, window_delta in windows.items():
        cutoff = now - window_delta
        window_trades = [t for t in close_trades if t["_ts_dt"] >= cutoff]
        
        # Extract returns
        returns = []
        for trade in window_trades:
            rets = _extract_return(trade)
            if rets is not None:
                returns.append(rets)
        
        # Compute PF
        if returns:
            stats = _compute_pf_for_window(returns)
            # Compute weighted gross profit/loss to detect scratch-only windows
            gross_profit = sum(r * w for r, w in returns if r > 0.0)
            gross_loss = sum(-r * w for r, w in returns if r < 0.0)  # positive number
            
            scratch_only = False
            lossless = False
            pf_value = stats.pf
            
            # Scratch-only: all pct == 0
            if stats.trades > 0 and abs(gross_profit) <= EPS and abs(gross_loss) <= EPS:
                pf_value = 1.0
                scratch_only = True
            
            # Lossless: wins>0, losses==0
            elif stats.trades > 0 and gross_profit > EPS and abs(gross_loss) <= EPS:
                pf_value = "inf"  # operator-friendly infinite PF
                lossless = True

            # Losing-only: wins==0, losses>0
            elif stats.trades > 0 and abs(gross_profit) <= EPS and gross_loss > EPS:
                pf_value = 0.0
            
            result[f"pf_{window_name}"] = pf_value
            result[f"count_{window_name}"] = stats.trades
            result[f"scratch_only_{window_name}"] = scratch_only
            result[f"scratch_count_{window_name}"] = stats.trades if scratch_only else 0
            result[f"lossless_{window_name}"] = lossless
            result[f"gross_profit_{window_name}"] = gross_profit
            result[f"gross_loss_{window_name}"] = gross_loss

            # --- Per-Regime PF Tracking ---
            # Group trades by regime for regime-specific performance analysis
            regime_groups = {}
            for trade in window_trades:
                regime = trade.get("regime", "unknown")
                # Skip unknown regime trades to avoid PF contamination
                if regime == "unknown":
                    continue
                if regime not in regime_groups:
                    regime_groups[regime] = []
                regime_groups[regime].append(trade)

            for regime, regime_trades in regime_groups.items():
                regime_returns = []
                for trade in regime_trades:
                    rets = _extract_return(trade)
                    if rets is not None:
                        regime_returns.append(rets)

                if regime_returns:
                    regime_stats = _compute_pf_for_window(regime_returns)
                    regime_gross_profit = sum(r * w for r, w in regime_returns if r > 0.0)
                    regime_gross_loss = sum(-r * w for r, w in regime_returns if r < 0.0)

                    regime_pf_value = regime_stats.pf
                    # Apply same scratch/lossless logic
                    if regime_stats.trades > 0 and abs(regime_gross_profit) <= EPS and abs(regime_gross_loss) <= EPS:
                        regime_pf_value = 1.0
                    elif regime_stats.trades > 0 and regime_gross_profit > EPS and abs(regime_gross_loss) <= EPS:
                        regime_pf_value = "inf"

                    result[f"pf_{window_name}_regime_{regime}"] = regime_pf_value
                    result[f"count_{window_name}_regime_{regime}"] = regime_stats.trades
                    result[f"gross_profit_{window_name}_regime_{regime}"] = regime_gross_profit
                    result[f"gross_loss_{window_name}_regime_{regime}"] = regime_gross_loss

            # --- Regime Accuracy Tracking ---
            # Track regime classification accuracy based on trade outcomes
            try:
                from engine_alpha.core.config_loader import load_engine_config
                cfg = load_engine_config()
                regime_tracking = cfg.get("slot_limits", {}).get("regime_edge_tracking", {})
                if regime_tracking.get("enabled", True):
                    min_samples = regime_tracking.get("min_regime_samples", 20)
                    accuracy_window_days = regime_tracking.get("regime_accuracy_window_days", 7)

                    # Use 7d window for regime accuracy
                    accuracy_cutoff = now - timedelta(days=accuracy_window_days)
                    accuracy_trades = [t for t in close_trades if t["_ts_dt"] >= accuracy_cutoff]

                    if len(accuracy_trades) >= min_samples:
                        regime_accuracy = {}
                        total_trades = 0

                        for trade in accuracy_trades:
                            regime = trade.get("regime", "unknown")
                            pct = trade.get("pct", 0)

                            if regime not in regime_accuracy:
                                regime_accuracy[regime] = {"correct": 0, "incorrect": 0, "total": 0}

                            # Simple heuristic: chop regime should have more small moves, trend should have larger directional moves
                            if regime == "chop":
                                # In chop, small moves (0.1-0.5%) are "correct", large moves (>1%) might indicate misclassification
                                if abs(pct) < 0.005:  # < 0.5%
                                    regime_accuracy[regime]["correct"] += 1
                                else:
                                    regime_accuracy[regime]["incorrect"] += 1
                            elif regime in ["trend_up", "trend_down"]:
                                # In trend, larger directional moves are "correct"
                                if abs(pct) > 0.005:  # > 0.5%
                                    regime_accuracy[regime]["correct"] += 1
                                else:
                                    regime_accuracy[regime]["incorrect"] += 1
                            else:
                                # For other regimes, count as neutral
                                regime_accuracy[regime]["correct"] += 1

                            regime_accuracy[regime]["total"] += 1
                            total_trades += 1

                        # Calculate accuracy percentages
                        for regime, stats in regime_accuracy.items():
                            if stats["total"] > 0:
                                accuracy = stats["correct"] / stats["total"]
                                result[f"regime_accuracy_{regime}"] = round(accuracy, 3)
                                result[f"regime_samples_{regime}"] = stats["total"]

                        result["regime_accuracy_total_samples"] = total_trades

            except Exception as e:
                # Don't fail PF calculation on regime tracking errors
                print(f"Regime accuracy tracking error: {e}")
                pass

            # --- Alternate PF: exclude review_bootstrap timeout closes (analytics-only) ---
            # Keep canonical pf_* unchanged (SAFE MODE / gates may depend on it).
            def _is_bootstrap_timeout_close(evt: dict) -> bool:
                try:
                    if (evt.get("trade_kind") or "").lower() != "exploration":
                        return False
                    r = (evt.get("exit_reason") or evt.get("reason") or "").strip()
                    return r in ("review_bootstrap_timeout", "review_bootstrap_timeout_manual")
                except Exception:
                    return False

            window_trades_ex = [t for t in window_trades if not _is_bootstrap_timeout_close(t)]
            returns_ex = []
            for trade in window_trades_ex:
                rets = _extract_return(trade)
                if rets is not None:
                    returns_ex.append(rets)

            if returns_ex:
                stats_ex = _compute_pf_for_window(returns_ex)
                gp_ex = sum(r * w for r, w in returns_ex if r > 0.0)
                gl_ex = sum(-r * w for r, w in returns_ex if r < 0.0)
                pf_ex = stats_ex.pf
                scratch_ex = False
                lossless_ex = False
                if stats_ex.trades > 0 and abs(gp_ex) <= EPS and abs(gl_ex) <= EPS:
                    pf_ex = 1.0
                    scratch_ex = True
                elif stats_ex.trades > 0 and gp_ex > EPS and abs(gl_ex) <= EPS:
                    pf_ex = "inf"
                    lossless_ex = True
                elif stats_ex.trades > 0 and abs(gp_ex) <= EPS and gl_ex > EPS:
                    pf_ex = 0.0

                result[f"pf_{window_name}_ex_bootstrap_timeouts"] = pf_ex
                result[f"count_{window_name}_ex_bootstrap_timeouts"] = stats_ex.trades
                result[f"scratch_only_{window_name}_ex_bootstrap_timeouts"] = scratch_ex
                result[f"gross_profit_{window_name}_ex_bootstrap_timeouts"] = gp_ex
                result[f"gross_loss_{window_name}_ex_bootstrap_timeouts"] = gl_ex
                result[f"lossless_{window_name}_ex_bootstrap_timeouts"] = lossless_ex

                # Audit-friendly aliases (same values, different keys)
                result[f"pf_{window_name}_ex_bootstrap"] = pf_ex
                result[f"count_{window_name}_ex_bootstrap"] = stats_ex.trades
            else:
                result[f"pf_{window_name}_ex_bootstrap_timeouts"] = None
                result[f"count_{window_name}_ex_bootstrap_timeouts"] = 0
                result[f"scratch_only_{window_name}_ex_bootstrap_timeouts"] = False
                result[f"gross_profit_{window_name}_ex_bootstrap_timeouts"] = 0.0
                result[f"gross_loss_{window_name}_ex_bootstrap_timeouts"] = 0.0
                result[f"lossless_{window_name}_ex_bootstrap_timeouts"] = False

                # Audit-friendly aliases
                result[f"pf_{window_name}_ex_bootstrap"] = None
                result[f"count_{window_name}_ex_bootstrap"] = 0
        else:
            result[f"pf_{window_name}"] = None
            result[f"count_{window_name}"] = 0
            result[f"scratch_only_{window_name}"] = False
            result[f"scratch_count_{window_name}"] = 0
            result[f"lossless_{window_name}"] = False
            result[f"gross_profit_{window_name}"] = 0.0
            result[f"gross_loss_{window_name}"] = 0.0

            result[f"pf_{window_name}_ex_bootstrap_timeouts"] = None
            result[f"count_{window_name}_ex_bootstrap_timeouts"] = 0
            result[f"scratch_only_{window_name}_ex_bootstrap_timeouts"] = False
            result[f"gross_profit_{window_name}_ex_bootstrap_timeouts"] = 0.0
            result[f"gross_loss_{window_name}_ex_bootstrap_timeouts"] = 0.0
            result[f"lossless_{window_name}_ex_bootstrap_timeouts"] = False

            # Audit-friendly aliases
            result[f"pf_{window_name}_ex_bootstrap"] = None
            result[f"count_{window_name}_ex_bootstrap"] = 0

    # Phase 5J: Promotion Readiness Analysis
    # Identify exploration symbols ready for core promotion based on 7d performance
    promotion_candidates = []

    # Get 7d exploration trades by symbol
    cutoff_7d = now - timedelta(days=7)
    exploration_trades_7d = []
    for trade in close_trades:
        if (trade.get("trade_kind") or "").lower() == "exploration":
            if trade["_ts_dt"] >= cutoff_7d:
                # Exclude forced exits (timeouts, trims, etc.)
                exit_reason = trade.get("exit_reason", "")
                if exit_reason not in ("review_bootstrap_timeout", "timeout_max_hold",
                                     "max_hold_timeout", "trim_to_core_limit",
                                     "manual_reset_stuck_position", "review_bootstrap_timeout_manual"):
                    exploration_trades_7d.append(trade)

    # Group by symbol
    from collections import defaultdict
    symbol_trades = defaultdict(list)
    for trade in exploration_trades_7d:
        symbol = trade.get("symbol", "unknown")
        symbol_trades[symbol].append(trade)

    # Check each symbol for promotion criteria
    for symbol, trades in symbol_trades.items():
        if len(trades) < 20:  # Min sample size
            continue

        # Calculate metrics
        returns = []
        for trade in trades:
            rets = _extract_return(trade)
            if rets is not None:
                returns.append(rets)

        if len(returns) < 20:
            continue

        stats = _compute_pf_for_window(returns)
        gross_profit = sum(r * w for r, w in returns if r > 0.0)
        gross_loss = sum(-r * w for r, w in returns if r < 0.0)

        win_count = sum(1 for r, w in returns if r > 0.0)
        win_rate = win_count / len(returns)

        # Calculate drawdown metrics
        if returns:
            cumulative = 0
            max_drawdown = 0
            peak = 0
            wins = [(r*w) for r, w in returns if r > 0.0]
            avg_win = sum(wins) / len(wins) if wins else 0

            for r, w in returns:
                cumulative += r * w
                peak = max(peak, cumulative)
                drawdown = peak - cumulative
                max_drawdown = max(max_drawdown, drawdown)

            # Check promotion criteria
            meets_criteria = (
                stats.pf >= 1.10 and  # PF > 1.10 for edge buffer
                win_rate >= 0.55 and  # Win rate >= 55%
                (max_drawdown <= 1.5 * avg_win if avg_win > 0 else True) and  # Drawdown control
                len(returns) >= 20  # Sample size confirmed
            )

            if meets_criteria:
                # Get regime consistency
                regimes = list(set(t.get("regime", "unknown") for t in trades))
                regime_consistent = len([r for r in regimes if r != "unknown"]) == 1

                promotion_candidates.append({
                    "symbol": symbol,
                    "sample_size": len(returns),
                    "pf": round(stats.pf, 3),
                    "win_rate": round(win_rate, 3),
                    "gross_profit": round(gross_profit, 6),
                    "gross_loss": round(gross_loss, 6),
                    "max_drawdown": round(max_drawdown, 6),
                    "avg_win": round(avg_win, 6),
                    "regime_consistent": regime_consistent,
                    "regimes": regimes,
                    "ready_for_promotion": True
                })

    result["phase5j_promotion_candidates"] = promotion_candidates

    return result


def main() -> int:
    """Main entry point."""
    result = compute_pf_local()
    
    # Write to reports/pf_local.json
    output_path = REPORTS / "pf_local.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    print(f"PF Local computed: 24h={result.get('pf_24h')}, 7d={result.get('pf_7d')}, 30d={result.get('pf_30d')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

