"""
Trade Statistics - Per-symbol trade count tracking.

Tracks exploration vs normal trade counts per symbol for sample-size gating.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any

from engine_alpha.core.paths import REPORTS

TRADES_PATH = REPORTS / "trades.jsonl"


def load_trade_counts() -> Dict[str, Dict[str, int]]:
    """
    Load per-symbol trade counts from trades.jsonl.
    
    Returns:
        Dict mapping symbol -> {
            "exploration_closes": int,
            "normal_closes": int,
            "total_closes": int,
        }
    """
    counts: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"exploration_closes": 0, "normal_closes": 0, "total_closes": 0}
    )
    
    if not TRADES_PATH.exists():
        return counts
    
    try:
        with TRADES_PATH.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    t = json.loads(line)
                except Exception:
                    continue
                
                # Only count closes
                if t.get("type") != "close" and t.get("event") != "close":
                    continue
                
                sym = t.get("symbol")
                if not sym:
                    continue
                
                kind = t.get("trade_kind", "normal")
                
                counts[sym]["total_closes"] += 1
                
                if kind == "exploration":
                    counts[sym]["exploration_closes"] += 1
                else:
                    counts[sym]["normal_closes"] += 1
    
    except Exception:
        pass
    
    return dict(counts)

