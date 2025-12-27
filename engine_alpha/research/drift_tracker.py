"""
Drift Tracker - Phase 5
Tracks signal degradation by comparing early vs recent trade performance.

For each symbol, splits exploration trades into early and recent windows
and computes performance delta to detect improving/degrading/stable patterns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS

TRADES_PATH = REPORTS / "trades.jsonl"
RESEARCH_DIR = REPORTS / "research"
DRIFT_REPORT_PATH = RESEARCH_DIR / "drift_report.json"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read JSONL file, return empty list if missing or invalid."""
    if not path.exists():
        return []
    entries = []
    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return entries


def _compute_pf(trades: List[float]) -> Optional[float]:
    """Compute profit factor from list of pct returns."""
    if not trades:
        return None
    
    wins = [t for t in trades if t > 0]
    losses = [abs(t) for t in trades if t < 0]
    
    total_wins = sum(wins) if wins else 0.0
    total_losses = sum(losses) if losses else 0.0
    
    if total_losses == 0:
        return float("inf") if total_wins > 0 else None
    
    return total_wins / total_losses


def _compute_avg_pct(trades: List[float]) -> Optional[float]:
    """Compute average pct return."""
    if not trades:
        return None
    return sum(trades) / len(trades)


def analyze_drift(symbol: str, trades: List[Dict[str, Any]], window_size: int = 5) -> Dict[str, Any]:
    """
    Analyze drift for a single symbol.
    
    Args:
        symbol: Symbol ID
        trades: List of trade dicts for this symbol
        window_size: Number of trades to use for early/recent windows
    
    Returns:
        Dict with early_avg_pct, recent_avg_pct, delta_pf, status
    """
    # Filter to exploration closes only
    exploration_closes = [
        t for t in trades
        if t.get("type") == "close"
        and t.get("trade_kind") == "exploration"
        and t.get("symbol") == symbol
    ]
    
    if len(exploration_closes) < window_size * 2:
        return {
            "early_avg_pct": None,
            "recent_avg_pct": None,
            "delta_pf": None,
            "status": "insufficient_data",
            "total_trades": len(exploration_closes),
        }
    
    # Extract pct returns
    pcts = []
    for trade in exploration_closes:
        try:
            pct = float(trade.get("pct", 0.0))
            pcts.append(pct)
        except (ValueError, TypeError):
            continue
    
    if len(pcts) < window_size * 2:
        return {
            "early_avg_pct": None,
            "recent_avg_pct": None,
            "delta_pf": None,
            "status": "insufficient_data",
            "total_trades": len(exploration_closes),
        }
    
    # Split into early and recent
    early_trades = pcts[:window_size]
    recent_trades = pcts[-window_size:]
    
    early_avg = _compute_avg_pct(early_trades)
    recent_avg = _compute_avg_pct(recent_trades)
    
    early_pf = _compute_pf(early_trades)
    recent_pf = _compute_pf(recent_trades)
    
    # Compute delta PF
    delta_pf = None
    if early_pf is not None and recent_pf is not None:
        if early_pf == float("inf"):
            early_pf = 10.0  # Cap for comparison
        if recent_pf == float("inf"):
            recent_pf = 10.0  # Cap for comparison
        delta_pf = recent_pf - early_pf
    
    # Determine status
    status = "stable"
    if delta_pf is not None:
        if delta_pf > 0.2:
            status = "improving"
        elif delta_pf < -0.2:
            status = "degrading"
    
    return {
        "early_avg_pct": early_avg,
        "recent_avg_pct": recent_avg,
        "early_pf": early_pf if early_pf != float("inf") else "inf",
        "recent_pf": recent_pf if recent_pf != float("inf") else "inf",
        "delta_pf": delta_pf,
        "status": status,
        "total_trades": len(exploration_closes),
        "early_window_size": len(early_trades),
        "recent_window_size": len(recent_trades),
    }


def compute_drift_report() -> Dict[str, Any]:
    """
    Compute drift report for all symbols.
    
    Returns:
        Dict with per-symbol drift analysis
    """
    trades = _read_jsonl(TRADES_PATH)
    
    # Get unique symbols from exploration closes
    symbols = set()
    for trade in trades:
        if trade.get("type") == "close" and trade.get("trade_kind") == "exploration":
            symbol = trade.get("symbol")
            if symbol:
                symbols.add(symbol)
    
    symbols = sorted(symbols)
    
    drift_data: Dict[str, Dict[str, Any]] = {}
    
    for symbol in symbols:
        drift_data[symbol] = analyze_drift(symbol, trades, window_size=5)
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": drift_data,
    }
    
    # Write report
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    DRIFT_REPORT_PATH.write_text(json.dumps(report, indent=2))
    
    return report

