"""
Tuning Self-Evaluation Engine - Let Chloe evaluate her own tuning decisions.

This module analyzes tuning proposals from tuning_reason_log.jsonl and compares
actual trade performance before vs after each tuning event to determine if the
tuning helped, hurt, or was inconclusive.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from engine_alpha.core.paths import REPORTS

TUNING_LOG_PATH = REPORTS / "gpt" / "tuning_reason_log.jsonl"
TRADES_PATH = REPORTS / "trades.jsonl"
SELF_EVAL_PATH = REPORTS / "research" / "tuning_self_eval.json"


def _load_tuning_events() -> List[Dict[str, Any]]:
    """Load all tuning events from the reason log."""
    events = []
    if not TUNING_LOG_PATH.exists():
        return events
    
    with TUNING_LOG_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    
    return events


def _load_trades() -> List[Dict[str, Any]]:
    """Load all trades from trades.jsonl."""
    trades = []
    if not TRADES_PATH.exists():
        return trades
    
    with TRADES_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                trades.append(obj)
            except Exception:
                continue
    
    return trades


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """
    Parse ISO timestamp string to datetime.
    
    Handles formats like:
    - "2025-12-05T20:25:34.712611+00:00"
    - "2025-12-05T20:25:34Z"
    """
    if not ts_str:
        return None
    
    try:
        # Handle Z suffix
        if ts_str.endswith("Z"):
            ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def _calculate_pf(pcts: List[float]) -> float:
    """
    Calculate profit factor from a list of P&L percentages.
    
    PF = sum(wins) / abs(sum(losses))
    Returns inf if no losses, or 0 if no wins.
    """
    if not pcts:
        return 0.0
    
    wins = [p for p in pcts if p > 0]
    losses = [p for p in pcts if p < 0]
    
    if not losses:
        return float("inf") if wins else 0.0
    
    total_wins = sum(wins)
    total_losses = abs(sum(losses))
    
    if total_losses == 0:
        return float("inf") if total_wins > 0 else 0.0
    
    return total_wins / total_losses


def _eval_symbol_for_event(
    symbol: str,
    event_ts: datetime,
    trades: List[Dict[str, Any]],
    window_size: int = 5
) -> Dict[str, Any]:
    """
    Evaluate a single symbol around one tuning event.
    
    Args:
        symbol: Symbol to evaluate
        event_ts: Timestamp of the tuning event
        trades: List of all trade dicts
        window_size: Number of trades to include in before/after windows
    
    Returns:
        Dict with status, detail, before stats, after stats
    """
    # Filter trades for this symbol, only closes (we want completed trades)
    sym_trades = [
        t for t in trades
        if t.get("symbol") == symbol and t.get("type") == "close"
    ]
    
    # Parse timestamps and extract P&L
    sym_trades_ts: List[Tuple[datetime, float]] = []
    for t in sym_trades:
        ts = _parse_ts(t.get("ts"))
        if ts is None:
            continue
        
        pct = t.get("pct")
        try:
            pct_val = float(pct)
        except (ValueError, TypeError):
            continue
        
        sym_trades_ts.append((ts, pct_val))
    
    # Sort by timestamp
    sym_trades_ts.sort(key=lambda x: x[0])
    
    # Split before/after windows by event_ts
    before_pcts = [p for (ts, p) in sym_trades_ts if ts < event_ts]
    after_pcts = [p for (ts, p) in sym_trades_ts if ts >= event_ts]
    
    # Need enough trades in both windows
    if len(before_pcts) < window_size or len(after_pcts) < window_size:
        return {
            "status": "inconclusive",
            "reason": "insufficient_sample",
            "before_count": len(before_pcts),
            "after_count": len(after_pcts),
        }
    
    # Take last N before, first N after
    before_pcts = before_pcts[-window_size:]
    after_pcts = after_pcts[:window_size]
    
    # Calculate stats
    def stats(pcts: List[float]) -> Dict[str, Any]:
        total = sum(pcts)
        pos = sum(1 for x in pcts if x > 0)
        neg = sum(1 for x in pcts if x < 0)
        pf = _calculate_pf(pcts)
        
        return {
            "pf": pf,
            "avg": total / len(pcts) if pcts else 0.0,
            "win_rate": pos / len(pcts) if pcts else 0.0,
            "wins": pos,
            "losses": neg,
            "count": len(pcts),
        }
    
    s_before = stats(before_pcts)
    s_after = stats(after_pcts)
    
    pf_before = s_before["pf"]
    pf_after = s_after["pf"]
    
    status = "inconclusive"
    detail = ""
    
    try:
        # Handle infinite PF cases
        if pf_before == float("inf") and pf_after == float("inf"):
            # Both perfect - check if after is better (more wins, fewer losses)
            if s_after["wins"] > s_before["wins"] or s_after["losses"] < s_before["losses"]:
                status = "improved"
                detail = f"Perfect PF maintained, improved win/loss ratio"
            elif s_after["wins"] < s_before["wins"] or s_after["losses"] > s_before["losses"]:
                status = "degraded"
                detail = f"Perfect PF maintained but win/loss ratio worsened"
            else:
                status = "inconclusive"
                detail = f"Perfect PF maintained, similar performance"
        elif pf_before == float("inf"):
            # Before was perfect, after is not - degraded
            status = "degraded"
            detail = f"PF degraded from perfect to {pf_after:.2f}"
        elif pf_after == float("inf"):
            # After is perfect, before was not - improved
            status = "improved"
            detail = f"PF improved from {pf_before:.2f} to perfect"
        else:
            # Both finite - compare ratios
            pf_ratio = pf_after / pf_before if pf_before > 0 else 0.0
            
            if pf_ratio > 1.1:
                status = "improved"
                detail = f"PF improved from {pf_before:.2f} to {pf_after:.2f} (ratio: {pf_ratio:.2f})"
            elif pf_ratio < 0.9:
                status = "degraded"
                detail = f"PF degraded from {pf_before:.2f} to {pf_after:.2f} (ratio: {pf_ratio:.2f})"
            else:
                status = "inconclusive"
                detail = f"PF changed little ({pf_before:.2f} → {pf_after:.2f}, ratio: {pf_ratio:.2f})"
    except Exception as exc:
        status = "inconclusive"
        detail = f"PF calculation error: {exc}"
    
    return {
        "status": status,
        "detail": detail,
        "before": s_before,
        "after": s_after,
    }


def run_tuning_self_eval(window_size: int = 5) -> Dict[str, Any]:
    """
    Run tuning self-evaluation across all tuning events.
    
    Args:
        window_size: Number of trades to include in before/after windows
    
    Returns:
        Dict with events and summary
    """
    events = _load_tuning_events()
    trades = _load_trades()
    
    if not events:
        return {
            "events": [],
            "summary": {},
            "note": "No tuning events found",
        }
    
    if not trades:
        return {
            "events": [],
            "summary": {},
            "note": "No trades found",
        }
    
    eval_results = []
    
    for evt in events:
        ts_str = evt.get("ts")
        event_ts = _parse_ts(ts_str) if ts_str else None
        if event_ts is None:
            continue
        
        sym_info = evt.get("symbols", {})
        sym_evals = {}
        
        for sym in sym_info.keys():
            sym_evals[sym] = _eval_symbol_for_event(sym, event_ts, trades, window_size=window_size)
        
        eval_results.append({
            "ts": ts_str,
            "symbols": sym_evals,
        })
    
    # Aggregate per-symbol summary: how many improved/degraded/inconclusive
    summary: Dict[str, Dict[str, int]] = {}
    
    for evt_eval in eval_results:
        for sym, res in evt_eval["symbols"].items():
            sym_sum = summary.setdefault(sym, {"improved": 0, "degraded": 0, "inconclusive": 0})
            status = res.get("status", "inconclusive")
            sym_sum[status] += 1
    
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_size": window_size,
        "events": eval_results,
        "summary": summary,
    }
    
    # Save results
    SELF_EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SELF_EVAL_PATH.write_text(json.dumps(out, indent=2))
    
    return out

