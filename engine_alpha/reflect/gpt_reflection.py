"""
GPT Reflection - Phase 4
Reflection and confidence calibration.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS
from engine_alpha.core.gpt_client import load_prompt, query_gpt


def _read_trades(trades_path: Path, n: int = 20) -> List[Dict[str, Any]]:
    """
    Read last N trades from trades.jsonl.
    
    Args:
        trades_path: Path to trades.jsonl
        n: Number of trades to read (default: 20)
    
    Returns:
        List of trade dictionaries
    """
    trades = []
    if not trades_path.exists():
        return trades
    
    # Read all lines
    with open(trades_path, "r") as f:
        lines = f.readlines()
    
    # Get last N lines
    for line in lines[-n:]:
        line = line.strip()
        if line:
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    
    return trades


def _read_last_reflection(reflections_path: Path) -> Optional[Dict[str, Any]]:
    """
    Read last reflection from reflections file.
    
    Args:
        reflections_path: Path to gpt_reflection.jsonl
    
    Returns:
        Last reflection dictionary or None
    """
    if not reflections_path.exists():
        return None
    
    # Read last line
    with open(reflections_path, "r") as f:
        lines = f.readlines()
    
    if not lines:
        return None
    
    # Get last non-empty line
    for line in reversed(lines):
        line = line.strip()
        if line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    
    return None


def _calculate_pf_from_trades(trades: List[Dict[str, Any]]) -> float:
    """
    Calculate profit factor from trades.
    
    Args:
        trades: List of trade dictionaries
    
    Returns:
        Profit factor
    """
    if not trades:
        return 1.0
    
    # Filter CLOSE events (these have P&L)
    close_trades = [t for t in trades if t.get("event") == "CLOSE"]
    
    positive_sum = 0.0
    negative_sum = 0.0
    
    for trade in close_trades:
        pnl_pct = trade.get("pnl_pct", 0.0)
        if pnl_pct > 0:
            positive_sum += pnl_pct
        elif pnl_pct < 0:
            negative_sum += abs(pnl_pct)
    
    if negative_sum == 0:
        return 999.0 if positive_sum > 0 else 1.0
    
    return positive_sum / negative_sum


def reflect_on_batch(trades_path: Optional[Path] = None, reflections_path: Optional[Path] = None,
                     n: int = 20) -> Dict[str, Any]:
    """
    Reflect on batch of trades.
    
    Args:
        trades_path: Path to trades.jsonl (default: REPORTS/trades.jsonl)
        reflections_path: Path to gpt_reflection.jsonl (default: REPORTS/gpt_reflection.jsonl)
        n: Number of trades to analyze (default: 20)
    
    Returns:
        Reflection dictionary
    """
    if trades_path is None:
        trades_path = REPORTS / "trades.jsonl"
    if reflections_path is None:
        reflections_path = REPORTS / "gpt_reflection.jsonl"
    
    # Read last N trades
    trades = _read_trades(trades_path, n)
    
    # Calculate current PF
    current_pf = _calculate_pf_from_trades(trades)
    
    # Read previous reflection
    last_reflection = _read_last_reflection(reflections_path)
    previous_pf = last_reflection.get("pf", 1.0) if last_reflection else 1.0
    
    # Calculate PF delta
    pf_delta = current_pf - previous_pf
    
    # Compose reflection (placeholder GPT insight for Phase 4)
    insight = f"PF changed by {pf_delta:.4f}. Trading performance {'improved' if pf_delta > 0 else 'declined'}."
    if not trades:
        insight = "No trades to analyze."
    
    # Confidence adjustment (placeholder)
    confidence_adjust = {
        "mean": 0.0,
        "sd": 0.0
    }
    
    reflection = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pf": current_pf,
        "pf_delta": pf_delta,
        "n_trades": len(trades),
        "insight": insight,
        "confidence_adjust": confidence_adjust,
    }
    
    # Append to reflections file
    reflections_path.parent.mkdir(parents=True, exist_ok=True)
    with open(reflections_path, "a") as f:
        f.write(json.dumps(reflection) + "\n")
    
    return reflection


def calibrate_confidence(current_conf: float, reason_score: float) -> float:
    """
    Calibrate confidence using weighted adjustment.
    
    Args:
        current_conf: Current confidence value
        reason_score: Reason score for adjustment
    
    Returns:
        Adjusted confidence
    """
    # Simple weighted adjustment: new = current_conf + 0.2*(reason_score - current_conf)
    new_conf = current_conf + 0.2 * (reason_score - current_conf)
    
    # Clamp to [0, 1]
    return max(0.0, min(1.0, new_conf))


def _summarize_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    closes = [t for t in trades if t.get("event") == "CLOSE"]
    wins = [t for t in closes if t.get("pnl_pct", 0.0) > 0]
    losses = [t for t in closes if t.get("pnl_pct", 0.0) < 0]
    total_close = len(closes)
    win_rate = len(wins) / total_close if total_close else 0.0
    avg_win = sum(t.get("pnl_pct", 0.0) for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.get("pnl_pct", 0.0) for t in losses) / len(losses) if losses else 0.0
    recent = closes[-5:]
    return {
        "total_trades": len(trades),
        "closed_trades": total_close,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "recent_closes": recent,
    }


def run_gpt_reflection(n: int = 20) -> Dict[str, Any]:
    """
    Generate GPT-based reflection summary for recent trades.
    """
    trades_path = REPORTS / "trades.jsonl"
    trades = _read_trades(trades_path, n=n)
    summary = _summarize_trades(trades)
    prompt_template = load_prompt("reflection")
    if not prompt_template:
        prompt_template = "Provide a concise reflection on the provided trades."

    context = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trade_summary": summary,
    }
    prompt = f"{prompt_template}\n\nContext:\n{json.dumps(context, indent=2)}"
    result = query_gpt(prompt, "reflection")
    ts = datetime.now(timezone.utc).isoformat()

    record = {
        "ts": ts,
        "context": context,
        "summary": result.get("text") if result else None,
        "cost_usd": result.get("cost_usd") if result else 0.0,
        "tokens": result.get("tokens") if result else 0,
    }

    out_path = REPORTS / "gpt_reflection.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a") as f:
        f.write(json.dumps(record) + "\n")

    summary_path = REPORTS / "gpt_summary.json"
    summary_path.write_text(json.dumps(record, indent=2))
    return record
