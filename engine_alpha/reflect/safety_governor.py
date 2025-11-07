"""
Safety Governor - Phase 4
Safety evaluation and incident tracking.
"""

import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS


def _read_trades(trades_path: Path) -> List[Dict[str, Any]]:
    """Read trades from trades.jsonl."""
    trades = []
    if not trades_path.exists():
        return trades
    
    with open(trades_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    
    return trades


def _read_pf_local() -> float:
    """Read PF_local from pf_local.json."""
    pf_local_path = REPORTS / "pf_local.json"
    if not pf_local_path.exists():
        return 1.0
    
    try:
        with open(pf_local_path, "r") as f:
            data = json.load(f)
            return float(data.get("pf", 1.0))
    except Exception:
        return 1.0


def _check_loss_streak(trades: List[Dict[str, Any]], streak_n: int = 7) -> bool:
    """
    Check if last N trades are all losses.
    
    Args:
        trades: List of trade dictionaries
        streak_n: Number of consecutive losses to trigger (default: 7)
    
    Returns:
        True if loss streak detected
    """
    # Filter CLOSE events
    close_trades = [t for t in trades if t.get("event") == "CLOSE"]
    
    if len(close_trades) < streak_n:
        return False
    
    # Check last N trades
    last_n = close_trades[-streak_n:]
    return all(t.get("pnl_pct", 0.0) < 0 for t in last_n)


def evaluate_safety() -> bool:
    """
    Evaluate safety conditions and trigger safe mode if needed.
    
    Returns:
        safe_mode state (bool)
    """
    incidents_path = REPORTS / "incidents.jsonl"
    trades_path = REPORTS / "trades.jsonl"
    
    # Read PF_local
    pf_local = _read_pf_local()
    
    # Read trades
    trades = _read_trades(trades_path)
    
    # Check conditions
    safe_mode = False
    reason = None
    
    # Condition 1: PF below threshold
    if pf_local < 0.95:
        safe_mode = True
        reason = "PF below threshold"
    
    # Condition 2: Loss streak
    if _check_loss_streak(trades, streak_n=7):
        safe_mode = True
        reason = "7-loss streak"
    
    # Write incident if safe mode triggered
    if safe_mode:
        incident = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "safe_mode": True,
            "pf_local": pf_local,
        }
        
        incidents_path.parent.mkdir(parents=True, exist_ok=True)
        with open(incidents_path, "a") as f:
            f.write(json.dumps(incident) + "\n")
    
    return safe_mode
