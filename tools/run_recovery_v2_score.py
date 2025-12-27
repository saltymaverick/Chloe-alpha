"""
Recovery V2 Performance Score (Phase 5H.3)
-------------------------------------------

Read-only performance summary tool for Recovery Lane V2.
Computes metrics from recovery_lane_v2_trades.jsonl without changing any gates.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from engine_alpha.core.paths import REPORTS
from engine_alpha.loop.recovery_lane_v2_trades import RECOVERY_TRADES_PATH

SCORE_OUTPUT_PATH = REPORTS / "loop" / "recovery_v2_score.json"


def _load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if missing."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}
    except Exception:
        return {}


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    """Save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_trades_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read all trades from JSONL file."""
    trades = []
    if not path.exists():
        return trades
    
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    trades.append(trade)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    
    return trades


def _filter_trades_by_window(trades: List[Dict[str, Any]], window_hours: int) -> List[Dict[str, Any]]:
    """Filter trades to only those within the last N hours."""
    if not trades:
        return []
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    
    filtered = []
    for trade in trades:
        ts_str = trade.get("ts", "")
        if not ts_str:
            continue
        
        try:
            # Parse ISO timestamp
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            
            if ts >= cutoff:
                filtered.append(trade)
        except Exception:
            continue
    
    return filtered


def _compute_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute performance metrics from close events.
    
    Returns:
        Dictionary with trades, win_rate, gross_profit_usd, gross_loss_usd,
        pf, max_drawdown_pct, expectancy_pct, top_symbols_by_trades, top_symbols_by_expectancy
    """
    # Filter to close events only
    close_trades = [t for t in trades if t.get("action") == "close"]
    
    if not close_trades:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "gross_profit_usd": 0.0,
            "gross_loss_usd": 0.0,
            "pf": 0.0,
            "max_drawdown_pct": 0.0,
            "expectancy_pct": 0.0,
            "top_symbols_by_trades": [],
            "top_symbols_by_expectancy": [],
        }
    
    # Compute gross profit/loss
    gross_profit_usd = sum(t.get("pnl_usd", 0.0) for t in close_trades if t.get("pnl_usd", 0.0) > 0)
    gross_loss_usd = abs(sum(t.get("pnl_usd", 0.0) for t in close_trades if t.get("pnl_usd", 0.0) < 0))
    
    # Compute PF (handle zero-loss case)
    if gross_loss_usd <= 0:
        pf = float("inf") if gross_profit_usd > 0 else 0.0
    else:
        pf = gross_profit_usd / gross_loss_usd
    
    # Compute win rate
    wins = sum(1 for t in close_trades if t.get("pnl_usd", 0.0) > 0)
    win_rate = wins / len(close_trades) if close_trades else 0.0
    
    # Compute expectancy (mean pnl_pct)
    pnl_pcts = [t.get("pnl_pct", 0.0) for t in close_trades]
    expectancy_pct = sum(pnl_pcts) / len(pnl_pcts) if pnl_pcts else 0.0
    
    # Compute max drawdown (cumulative equity curve)
    cumulative = 0.0
    peak = 0.0
    max_dd_pct = 0.0
    
    for trade in close_trades:
        pnl_pct = trade.get("pnl_pct", 0.0)
        cumulative += pnl_pct
        if cumulative > peak:
            peak = cumulative
        drawdown_pct = peak - cumulative
        if drawdown_pct > max_dd_pct:
            max_dd_pct = drawdown_pct
    
    # Top symbols by trade count
    symbol_counts: Dict[str, int] = {}
    for trade in close_trades:
        symbol = trade.get("symbol", "UNKNOWN")
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
    
    top_symbols_by_trades = sorted(
        symbol_counts.items(),
        key=lambda x: (-x[1], x[0])
    )[:5]  # Top 5
    
    # Top symbols by expectancy (mean pnl_pct per symbol)
    symbol_pnls: Dict[str, List[float]] = {}
    for trade in close_trades:
        symbol = trade.get("symbol", "UNKNOWN")
        pnl_pct = trade.get("pnl_pct", 0.0)
        if symbol not in symbol_pnls:
            symbol_pnls[symbol] = []
        symbol_pnls[symbol].append(pnl_pct)
    
    symbol_expectancies = {
        symbol: sum(pnls) / len(pnls)
        for symbol, pnls in symbol_pnls.items()
    }
    
    top_symbols_by_expectancy = sorted(
        symbol_expectancies.items(),
        key=lambda x: (-x[1], x[0])
    )[:5]  # Top 5
    
    return {
        "trades": len(close_trades),
        "win_rate": win_rate,
        "gross_profit_usd": gross_profit_usd,
        "gross_loss_usd": gross_loss_usd,
        "pf": pf,
        "max_drawdown_pct": max_dd_pct,
        "expectancy_pct": expectancy_pct,
        "top_symbols_by_trades": [{"symbol": s, "count": c} for s, c in top_symbols_by_trades],
        "top_symbols_by_expectancy": [{"symbol": s, "expectancy_pct": e} for s, e in top_symbols_by_expectancy],
    }


def compute_recovery_v2_score() -> Dict[str, Any]:
    """
    Compute Recovery V2 performance score for 24h and 7d windows.
    
    Returns:
        Dictionary with 24h and 7d metrics, plus metadata.
    """
    # Read all trades
    all_trades = _read_trades_jsonl(RECOVERY_TRADES_PATH)
    
    # Filter to windows
    trades_24h = _filter_trades_by_window(all_trades, 24)
    trades_7d = _filter_trades_by_window(all_trades, 7 * 24)
    
    # Compute metrics
    metrics_24h = _compute_metrics(trades_24h)
    metrics_7d = _compute_metrics(trades_7d)
    
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "24h": metrics_24h,
        "7d": metrics_7d,
    }
    
    return result


def main() -> int:
    """Main entry point."""
    print("Recovery V2 Performance Score (Phase 5H.3)")
    print("=" * 70)
    print()
    
    score = compute_recovery_v2_score()
    
    # Print human-readable output
    metrics_24h = score.get("24h", {})
    metrics_7d = score.get("7d", {})
    
    print("24-HOUR METRICS")
    print("-" * 70)
    print(f"Trades              : {metrics_24h.get('trades', 0)}")
    print(f"Win Rate            : {metrics_24h.get('win_rate', 0.0):.1%}")
    print(f"Gross Profit (USD)  : ${metrics_24h.get('gross_profit_usd', 0.0):.4f}")
    print(f"Gross Loss (USD)    : ${metrics_24h.get('gross_loss_usd', 0.0):.4f}")
    
    pf_24h = metrics_24h.get('pf', 0.0)
    if pf_24h == float("inf"):
        print(f"Profit Factor       : inf (no losses)")
    else:
        print(f"Profit Factor       : {pf_24h:.3f}")
    
    print(f"Max Drawdown (%)    : {metrics_24h.get('max_drawdown_pct', 0.0):.3f}%")
    print(f"Expectancy (%)      : {metrics_24h.get('expectancy_pct', 0.0):.4f}%")
    
    top_trades = metrics_24h.get('top_symbols_by_trades', [])
    if top_trades:
        trades_str = ', '.join(f"{s['symbol']}({s['count']})" for s in top_trades[:3])
        print(f"Top Symbols (Trades): {trades_str}")
    
    top_expectancy = metrics_24h.get('top_symbols_by_expectancy', [])
    if top_expectancy:
        exp_str = ', '.join(f"{s['symbol']}({s['expectancy_pct']:+.2f}%)" for s in top_expectancy[:3])
        print(f"Top Symbols (Exp.)  : {exp_str}")
    
    print()
    print("7-DAY METRICS")
    print("-" * 70)
    print(f"Trades              : {metrics_7d.get('trades', 0)}")
    print(f"Win Rate            : {metrics_7d.get('win_rate', 0.0):.1%}")
    print(f"Gross Profit (USD)  : ${metrics_7d.get('gross_profit_usd', 0.0):.4f}")
    print(f"Gross Loss (USD)    : ${metrics_7d.get('gross_loss_usd', 0.0):.4f}")
    
    pf_7d = metrics_7d.get('pf', 0.0)
    if pf_7d == float("inf"):
        print(f"Profit Factor       : inf (no losses)")
    else:
        print(f"Profit Factor       : {pf_7d:.3f}")
    
    print(f"Max Drawdown (%)    : {metrics_7d.get('max_drawdown_pct', 0.0):.3f}%")
    print(f"Expectancy (%)      : {metrics_7d.get('expectancy_pct', 0.0):.4f}%")
    
    top_trades_7d = metrics_7d.get('top_symbols_by_trades', [])
    if top_trades_7d:
        trades_str_7d = ', '.join(f"{s['symbol']}({s['count']})" for s in top_trades_7d[:3])
        print(f"Top Symbols (Trades): {trades_str_7d}")
    
    top_expectancy_7d = metrics_7d.get('top_symbols_by_expectancy', [])
    if top_expectancy_7d:
        exp_str_7d = ', '.join(f"{s['symbol']}({s['expectancy_pct']:+.2f}%)" for s in top_expectancy_7d[:3])
        print(f"Top Symbols (Exp.)  : {exp_str_7d}")
    
    print()
    print("=" * 70)
    print(f"Score saved to: {SCORE_OUTPUT_PATH}")
    print()
    
    # Save JSON
    _save_json(SCORE_OUTPUT_PATH, score)
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

