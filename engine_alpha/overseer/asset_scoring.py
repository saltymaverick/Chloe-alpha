from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from engine_alpha.core.paths import REPORTS

STALENESS_PATH = REPORTS / "research" / "staleness_overseer.json"
SCORECARD_PATH = REPORTS / "scorecards" / "asset_scorecards.json"
OVERSEER_PATH = REPORTS / "research" / "overseer_report.json"
ASSET_SCORES_PATH = REPORTS / "research" / "asset_scores.json"


@dataclass
class AssetScore:
    symbol: str
    tier: int = 3
    trading_enabled: bool = False
    urgency: float = 0.0
    staleness: float = 0.0
    opportunity: float = 0.0
    risk: float = 0.0
    notes: List[str] = field(default_factory=list)


def _safe_load(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def _normalize_hours(hours: Optional[float]) -> float:
    if hours is None:
        return 0.0
    days = hours / 24.0
    return max(0.0, min(1.0, days / 7.0))


def _derive_tier(symbol: str, overseer_assets: Dict[str, Dict]) -> int:
    info = overseer_assets.get(symbol, {})
    tier = info.get("tier")
    if isinstance(tier, int):
        return tier
    return 3


def _get_pf(symbol: str, scorecards: Dict[str, Dict], overseer_assets: Dict[str, Dict]) -> Optional[float]:
    card = scorecards.get(symbol)
    if card and card.get("pf") is not None:
        return card.get("pf")
    ov = overseer_assets.get(symbol, {})
    return ov.get("pf")


def _get_total_trades(symbol: str, scorecards: Dict[str, Dict], overseer_assets: Dict[str, Dict]) -> int:
    card = scorecards.get(symbol)
    if card and card.get("total_trades") is not None:
        return int(card.get("total_trades"))
    ov = overseer_assets.get(symbol, {})
    if ov.get("total_trades") is not None:
        return int(ov.get("total_trades"))
    return 0


def _compute_score(
    symbol: str,
    info: Dict[str, Dict],
    scorecards: Dict[str, Dict],
    overseer_assets: Dict[str, Dict],
) -> AssetScore:
    staleness_info = info.get(symbol, {})
    score = AssetScore(symbol=symbol)
    score.tier = _derive_tier(symbol, overseer_assets)
    score.trading_enabled = staleness_info.get("trading_enabled", False)

    hours = staleness_info.get("hours_since_last_trade")
    score.staleness = _normalize_hours(hours)

    pf = _get_pf(symbol, scorecards, overseer_assets)
    total_trades = _get_total_trades(symbol, scorecards, overseer_assets)
    feed_state = staleness_info.get("feed_state", "unknown")
    classification = staleness_info.get("classification", "unknown")

    # Opportunity heuristic
    opportunity = 0.2
    if staleness_info.get("trading_enabled"):
        opportunity += 0.1
    if classification == "maybe_too_strict":
        opportunity += 0.4
        score.notes.append("stale_but_strict")
    if pf is not None:
        if pf >= 1.05:
            opportunity += 0.2
        elif pf < 0.9:
            opportunity -= 0.2
            score.notes.append("pf_weak")
    if feed_state in ("stale", "unavailable"):
        opportunity -= 0.3
        score.notes.append("feed_issue")
    score.opportunity = max(0.0, min(1.0, opportunity))

    # Urgency mixes staleness + opportunity + enabled state
    urgency = 0.5 * score.staleness + 0.3 * score.opportunity
    if score.trading_enabled:
        urgency += 0.1
    if score.tier == 1:
        urgency += 0.1
    score.urgency = max(0.0, min(1.0, urgency))

    # Risk heuristic
    risk = 0.3
    if pf is not None:
        if pf < 0.9:
            risk += 0.3
        elif pf > 1.1 and total_trades >= 20:
            risk -= 0.1
    if feed_state in ("stale", "unavailable"):
        risk += 0.3
    if total_trades < 5:
        risk += 0.1
    score.risk = max(0.0, min(1.0, risk))

    return score


def build_asset_scores(now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    staleness = _safe_load(STALENESS_PATH)
    scorecards_raw = _safe_load(SCORECARD_PATH)
    overseer = _safe_load(OVERSEER_PATH)

    staleness_assets = staleness.get("assets", {})
    scorecards = {
        row.get("symbol", "").upper(): row
        for row in scorecards_raw.get("assets", [])
        if row.get("symbol")
    }
    overseer_assets = {sym.upper(): data for sym, data in overseer.get("assets", {}).items()}

    scores_payload: Dict[str, Dict[str, Any]] = {}
    for symbol in staleness_assets.keys():
        score_obj = _compute_score(symbol, staleness_assets, scorecards, overseer_assets)
        scores_payload[symbol] = asdict(score_obj)

    report = {
        "generated_at": now.isoformat(),
        "assets": scores_payload,
    }
    ASSET_SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    ASSET_SCORES_PATH.write_text(json.dumps(report, indent=2))
    return report


__all__ = ["AssetScore", "build_asset_scores"]

