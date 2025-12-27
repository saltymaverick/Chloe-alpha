from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS
from engine_alpha.overseer.staleness_analyst import STALENESS_REPORT_PATH
SCORECARD_PATH = REPORTS / "scorecards" / "asset_scorecards.json"
RAW_PROPOSALS_PATH = REPORTS / "research" / "tuning_proposals_raw.json"
GUARDED_PROPOSALS_PATH = REPORTS / "research" / "tuning_proposals_guarded.json"

def _safe_load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        return json.loads(data) if data else {}
    except Exception:
        return {}

def _get_pf(symbol: str, scorecards: Dict[str, Dict[str, Any]]) -> Optional[float]:
    card = scorecards.get(symbol)
    if not card:
        return None
    return card.get("pf")

def _get_total_trades(symbol: str, scorecards: Dict[str, Dict[str, Any]]) -> int:
    card = scorecards.get(symbol)
    if not card:
        return 0
    return int(card.get("total_trades") or 0)

def _guard_symbol(symbol: str, proposal: Dict[str, Any], staleness: Dict[str, Dict[str, Any]], scorecards: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    info = staleness.get(symbol, {})
    pf = _get_pf(symbol, scorecards)
    trades = _get_total_trades(symbol, scorecards)
    feed_state = info.get("feed_state", "unknown")
    classification = info.get("classification", "unknown")
    trading_enabled = info.get("trading_enabled", False)

    allowed: Dict[str, Any] = {}
    blocked: Dict[str, Any] = {}
    reasons: List[str] = []

    changes = proposal.get("changes", {})
    if not changes:
        return {"allowed_changes": {}, "blocked_changes": {}, "reason": ["no_changes"]}

    if feed_state in ("stale", "unavailable"):
        reasons.append("feed_issue")
        blocked = changes
        return {"allowed_changes": {}, "blocked_changes": blocked, "reason": reasons}

    if not trading_enabled:
        reasons.append("trading_disabled")
        blocked = changes
        return {"allowed_changes": {}, "blocked_changes": blocked, "reason": reasons}

    if trades < 10:
        reasons.append("low_trade_history")

    relax_ok = (
        pf is not None
        and pf >= 1.05
        and trades >= 20
        and classification == "maybe_too_strict"
    )

    for key, delta in changes.items():
        if not isinstance(delta, dict):
            blocked[key] = delta
            reasons.append("unknown_change_format")
            continue
        old_val = delta.get("old")
        new_val = delta.get("new")
        if not all(isinstance(v, (int, float)) for v in (old_val, new_val)):
            blocked[key] = delta
            reasons.append("non_numeric_change")
            continue
        diff = new_val - old_val
        # Negative diff typically relaxes thresholds (e.g., lower conf)
        if diff < 0 and not relax_ok:
            blocked[key] = delta
            reasons.append("relaxation_blocked")
            continue
        if abs(diff) > 0.05 and trades < 50:
            blocked[key] = delta
            reasons.append("delta_too_large")
            continue
        allowed[key] = delta

    return {
        "allowed_changes": allowed,
        "blocked_changes": blocked,
        "reason": reasons or ["ok"],
    }

def apply_guardrails_to_file(raw_path: Path = RAW_PROPOSALS_PATH, output_path: Path = GUARDED_PROPOSALS_PATH) -> Dict[str, Any]:
    raw = _safe_load(raw_path)
    proposals = raw.get("proposals", {})
    staleness = _safe_load(STALENESS_REPORT_PATH).get("assets", {})
    scorecards_raw = _safe_load(SCORECARD_PATH).get("assets", [])
    scorecards = {row.get("symbol", "").upper(): row for row in scorecards_raw if row.get("symbol")}

    guarded: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "proposals": {},
        "notes": [],
    }

    if not proposals:
        guarded["notes"].append("No raw tuning proposals available.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(guarded, indent=2))
        return guarded

    for symbol, proposal in proposals.items():
        upper = symbol.upper()
        guard = _guard_symbol(upper, proposal, staleness, scorecards)
        guarded["proposals"][upper] = guard

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(guarded, indent=2))
    return guarded

__all__ = ["apply_guardrails_to_file"]

