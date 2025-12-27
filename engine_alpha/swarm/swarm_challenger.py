"""
SWARM Challenger - Independent Decision Audit

Re-checks Chloe's decisions using simpler logic and flags disagreements.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any
import json
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
CONFIG_DIR = ROOT_DIR / "config"

CONF_MAP_PATH = CONFIG_DIR / "confidence_map.json"
STRENGTH_PATH = RESEARCH_DIR / "strategy_strength.json"

CHALLENGER_LOG = RESEARCH_DIR / "swarm_challenger_log.jsonl"


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


@dataclass
class ChallengerDecision:
    ts: str
    symbol: str
    regime: str
    confidence: float
    chloe_decision: str   # "long" | "short" | "flat"
    challenger_decision: str
    combined_edge: float
    verdict: str          # "agree" | "disagree" | "warning"


def _lookup_conf_edge(confidence: float, conf_map: Dict[str, Any]) -> float:
    """Look up expected return for confidence bucket."""
    if not conf_map:
        return 0.0
    bucket = int(min(9, max(0, int(confidence * 10))))
    info = conf_map.get(str(bucket), {})
    return float(info.get("expected_return", 0.0))


def _lookup_regime_edge(regime: str, strengths: Dict[str, Any]) -> float:
    """Look up expected return for regime."""
    info = strengths.get(regime, {})
    return float(info.get("edge", 0.0))


def evaluate_decision(
    symbol: str,
    regime: str,
    confidence: float,
    chloe_decision: str,
) -> ChallengerDecision:
    """
    Evaluate Chloe's decision using independent challenger logic.
    
    Challenger's simple rule:
    - If combined_edge > 0: longs are favored
    - If combined_edge < 0: shorts or flat are favored
    - If combined_edge == 0: flat
    
    Args:
        symbol: Trading symbol
        regime: Market regime
        confidence: Chloe's confidence (0.0-1.0)
        chloe_decision: Chloe's decision ("long" | "short" | "flat")
    
    Returns:
        ChallengerDecision with agreement/disagreement verdict
    """
    conf_map = _load_json(CONF_MAP_PATH)
    strengths = _load_json(STRENGTH_PATH)

    conf_edge = _lookup_conf_edge(confidence, conf_map)
    reg_edge = _lookup_regime_edge(regime, strengths)
    combined_edge = (conf_edge + reg_edge) / 2.0

    # Challenger's simple rule:
    # - if combined_edge > 0: longs are favored
    # - if combined_edge < 0: shorts or flat are favored
    if combined_edge > 0:
        challenger_decision = "long"
    elif combined_edge < 0:
        challenger_decision = "short"
    else:
        challenger_decision = "flat"

    # Normalize chloe_decision
    chloe_norm = chloe_decision.lower()
    if chloe_norm not in ("long", "short", "flat"):
        # Try to infer from direction
        if chloe_norm in ("buy", "1", "+1"):
            chloe_norm = "long"
        elif chloe_norm in ("sell", "-1"):
            chloe_norm = "short"
        else:
            chloe_norm = "flat"

    if chloe_norm == challenger_decision:
        verdict = "agree"
    else:
        # If edge is small, treat as softer disagreement
        if abs(combined_edge) < 0.0005:
            verdict = "warning"
        else:
            verdict = "disagree"

    decision = ChallengerDecision(
        ts=datetime.now(timezone.utc).isoformat(),
        symbol=symbol,
        regime=regime,
        confidence=confidence,
        chloe_decision=chloe_norm,
        challenger_decision=challenger_decision,
        combined_edge=combined_edge,
        verdict=verdict,
    )

    CHALLENGER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CHALLENGER_LOG.open("a") as f:
        f.write(json.dumps(asdict(decision)) + "\n")

    return decision


if __name__ == "__main__":
    # Example manual call:
    d = evaluate_decision(
        symbol="ETHUSDT",
        regime="trend_down",
        confidence=0.72,
        chloe_decision="long",
    )
    print(json.dumps(asdict(d), indent=2))


