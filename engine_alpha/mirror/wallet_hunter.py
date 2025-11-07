"""
Wallet hunter - Phase 8
Maintains a small registry of candidate wallets to observe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List

from engine_alpha.core.paths import REPORTS


DEFAULT_WALLETS = [
    {"id": "demo_whale_A", "label": "demo", "score": 0.7},
    {"id": "demo_whale_B", "label": "demo", "score": 0.6},
    {"id": "demo_whale_C", "label": "demo", "score": 0.55},
]


def ensure_registry(path: Path = REPORTS / "wallet_registry.json") -> Dict[str, Any]:
    """Create registry file with demo entries if missing and return its content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w") as f:
            json.dump({"wallets": DEFAULT_WALLETS}, f, indent=2)
    try:
        with path.open("r") as f:
            data = json.load(f)
    except Exception:
        data = {"wallets": DEFAULT_WALLETS}
    return data


def score_wallets(registry: Dict[str, Any]) -> List[Dict[str, Any]]:
    wallets = registry.get("wallets", [])
    return sorted(wallets, key=lambda w: w.get("score", 0), reverse=True)
