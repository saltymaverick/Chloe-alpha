"""
GPT Analysis Triggers - Phase 44.3
Determines when GPT council analysis should run based on trade/PF conditions.
This is a utility module, NOT called from the trading loop.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

from engine_alpha.core.paths import REPORTS

SUGGESTIONS_PATH = REPORTS / "gpt_suggestions.jsonl"
PF_LOCAL_PATH = REPORTS / "pf_local.json"
TRADES_PATH = REPORTS / "trades.jsonl"


def _read_json(path: Path) -> Dict[str, Any]:
    """Read JSON file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _count_closed_trades() -> int:
    """Count total number of closed trades in trades.jsonl."""
    if not TRADES_PATH.exists():
        return 0
    count = 0
    try:
        with TRADES_PATH.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    event = str(trade.get("type") or trade.get("event") or "").lower()
                    if event == "close":
                        count += 1
                except Exception:
                    continue
    except Exception:
        return 0
    return count


def _get_last_analysis_time() -> Optional[datetime]:
    """Get timestamp of most recent GPT analysis from suggestions file."""
    if not SUGGESTIONS_PATH.exists():
        return None
    
    last_ts = None
    try:
        with SUGGESTIONS_PATH.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    suggestion = json.loads(line)
                    ts_str = suggestion.get("suggestions", {}).get("timestamp")
                    if ts_str:
                        # Parse ISO format timestamp
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if last_ts is None or ts > last_ts:
                            last_ts = ts
                except Exception:
                    continue
    except Exception:
        return None
    
    return last_ts


def should_run_gpt_council_analysis() -> bool:
    """
    Decide whether to run GPT council analysis now based on conditions such as:
    - number of closed trades,
    - PF over last N trades,
    - time since last GPT analysis.
    
    In this phase, implement a simple rule:
    - If there are at least 50 closes AND
    - PF from pf_local.json or last trades.jsonl is between 0.8 and 1.5 AND
    - no recent analysis event in the last 6 hours (check SUGGESTIONS_PATH timestamps),
    then return True, else False.
    """
    # Check minimum trade count
    closed_count = _count_closed_trades()
    if closed_count < 50:
        return False
    
    # Check PF range
    pf_data = _read_json(PF_LOCAL_PATH)
    pf_value = pf_data.get("pf", 0.0)
    try:
        pf_float = float(pf_value)
    except (TypeError, ValueError):
        pf_float = 0.0
    
    # PF should be between 0.8 and 1.5 (reasonable range for analysis)
    if pf_float < 0.8 or pf_float > 1.5:
        return False
    
    # Check time since last analysis
    last_analysis = _get_last_analysis_time()
    if last_analysis is not None:
        time_since = datetime.now(timezone.utc) - last_analysis
        if time_since < timedelta(hours=6):
            return False
    
    return True


if __name__ == "__main__":
    result = should_run_gpt_council_analysis()
    print(f"Should run GPT analysis: {result}")


















