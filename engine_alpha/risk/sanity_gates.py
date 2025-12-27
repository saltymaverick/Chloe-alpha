"""
Sanity Gates - Quant Safety Layer

This is the "are we EVEN allowed to trade?" layer that sits right before a trade is placed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any
import json

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"

PF_LOCAL_PATH = REPORTS_DIR / "pf_local.json"
STRENGTH_PATH = RESEARCH_DIR / "strategy_strength.json"
BLIND_SPOT_LOG = RESEARCH_DIR / "blind_spots.jsonl"


@dataclass
class SanityDecision:
    allow_trade: bool
    severity: str  # "ok", "warn", "hard_block"
    reason: str


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


def _latest_blind_spot_flag() -> bool:
    """
    True if recent blind spots exist; kept simple:
    if file exists and non-empty, we treat as soft warning.
    """
    if not BLIND_SPOT_LOG.exists():
        return False
    try:
        with BLIND_SPOT_LOG.open("r") as f:
            for _ in f:
                return True
    except Exception:
        return False
    return False


def check_sanity(
    regime: str,
    confidence: float,
    min_pf_ok: float = 0.95,
    hard_block_pf: float = 0.85,
    min_regime_strength: float = -0.001,
    require_strength_weight: float = 20.0,
) -> SanityDecision:
    """
    Global sanity gate for a potential trade.

    - PF_local too low → scale down or block.
    - Regime strength very negative → block.
    - Blind-spot flags + low confidence → block.
    """
    pf_local = _load_json(PF_LOCAL_PATH)
    strengths = _load_json(STRENGTH_PATH)

    pf = pf_local.get("pf", 1.0)
    dd = pf_local.get("drawdown", 0.0)  # optional

    reg_info = strengths.get(regime, {})
    reg_strength = reg_info.get("strength", 0.0)
    reg_wN = reg_info.get("weighted_count", 0.0)

    blind_flag = _latest_blind_spot_flag()

    # 1) Hard PF guard
    if pf < hard_block_pf:
        return SanityDecision(
            allow_trade=False,
            severity="hard_block",
            reason=f"PF_local={pf:.2f} below hard block {hard_block_pf:.2f}",
        )

    # 2) Regime strength guard (only if we have enough data)
    if reg_wN >= require_strength_weight and reg_strength < min_regime_strength:
        return SanityDecision(
            allow_trade=False,
            severity="hard_block",
            reason=(
                f"Regime {regime} has strong negative strength={reg_strength:.5f}, "
                f"wN={reg_wN:.1f}"
            ),
        )

    # 3) Blind-spot + low confidence → soft block
    if blind_flag and confidence < 0.5:
        return SanityDecision(
            allow_trade=False,
            severity="warn",
            reason="Blind spot flagged and confidence < 0.5",
        )

    # 4) PF local slightly impaired → allow but as 'warn'
    if pf < min_pf_ok:
        return SanityDecision(
            allow_trade=True,
            severity="warn",
            reason=f"PF_local={pf:.2f} below comfort {min_pf_ok:.2f}",
        )

    return SanityDecision(
        allow_trade=True,
        severity="ok",
        reason="Sanity checks passed",
    )


