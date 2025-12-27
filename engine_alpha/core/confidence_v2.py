"""
Confidence Engine V2 – decomposed confidence with per-symbol weights.

PAPER-only, advisory-only.

This module:
  * Reads PF / trade stats from reports/pf_local.json (if present)
  * Reads regime fusion from reports/research/regime_fusion.json
  * Produces decomposed confidence per symbol:

        - pf_quality
        - sample_size
        - regime_alignment
        - stability
  * Computes a weighted overall confidence
  * Adds Hybrid Lane V2 boost/negative boost
  * Writes reports/research/confidence_v2.json

Backwards-compatible: Confidence Engine V1 remains untouched; this is
additional advisory surface.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS

PF_LOCAL_PATH = REPORTS / "pf_local.json"
REGIME_V2_PATH = REPORTS / "research" / "regime_fusion.json"
CONF_V2_PATH = REPORTS / "research" / "confidence_v2.json"


@dataclass
class ConfidenceComponents:
    pf_quality: float
    sample_size: float
    regime_alignment: float
    stability: float


@dataclass
class ConfidenceWeights:
    pf_quality: float = 0.4
    sample_size: float = 0.2
    regime_alignment: float = 0.25
    stability: float = 0.15


@dataclass
class HybridLaneV2:
    lane: str          # "boost", "normal", "brake"
    boost: float       # in [-0.3, 0.3]
    reason: str


@dataclass
class ConfidenceV2Snapshot:
    symbol: str
    timeframe: str
    overall: float
    components: ConfidenceComponents
    weights: ConfidenceWeights
    hybrid_lane: HybridLaneV2
    asof_iso: str
    version: str = "v2.1"
    health: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "overall": self.overall,
            "components": asdict(self.components),
            "weights": asdict(self.weights),
            "hybrid_lane": asdict(self.hybrid_lane),
            "asof_iso": self.asof_iso,
            "version": self.version,
            "health": self.health or {},
        }


def _safe_read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _pf_component_for_symbol(
    pf_local: Optional[Dict[str, Any]], symbol: str
) -> tuple[float, float]:
    """
    Returns (pf_quality, sample_size_score).
    Both in [0, 1].
    """
    if not pf_local:
        return 0.5, 0.0

    # Handle different PF local formats
    entry = None
    if isinstance(pf_local, dict):
        # Try direct symbol key
        entry = pf_local.get(symbol) or pf_local.get(symbol.upper())
        # Try nested structure
        if not entry and "symbols" in pf_local:
            entry = pf_local["symbols"].get(symbol) or pf_local["symbols"].get(symbol.upper())
        # Try pf key directly
        if not entry and "pf" in pf_local:
            pf_val = pf_local.get("pf")
            trades_val = pf_local.get("trades", 0)
            if pf_val is not None:
                entry = {"pf": pf_val, "trades": trades_val}

    if not entry:
        return 0.5, 0.0

    pf = float(entry.get("pf", 1.0))
    trades = int(entry.get("trades", 0))

    # Map PF to [0, 1] (softly)
    if pf <= 0.8:
        pf_quality = 0.1
    elif pf <= 1.0:
        pf_quality = 0.35 + 0.15 * (pf - 0.8) / 0.2
    elif pf <= 1.3:
        pf_quality = 0.5 + 0.4 * (pf - 1.0) / 0.3
    else:
        pf_quality = 0.9

    pf_quality = float(max(0.0, min(1.0, pf_quality)))

    # Sample size: 0 at 0 trades, 0.5 at 20 trades, 1 at 80+
    if trades <= 0:
        sample_score = 0.0
    elif trades >= 80:
        sample_score = 1.0
    elif trades >= 20:
        sample_score = 0.5 + 0.5 * (trades - 20) / 60.0
    else:
        sample_score = 0.5 * trades / 20.0

    return pf_quality, float(max(0.0, min(1.0, sample_score)))


def _regime_alignment_component(
    regime_v2: Optional[Dict[str, Any]],
    symbol: str,
    timeframe: str,
) -> float:
    """
    For now we assume the default Chloe lane bias is long-biased.
    This can be made strategy-aware later.
    """
    if not regime_v2:
        return 0.5

    # Handle versioned format
    symbols_data = regime_v2.get("symbols", {})
    key = f"{symbol}:{timeframe}"
    entry = symbols_data.get(key)
    if not entry:
        return 0.5

    fused_label = entry.get("fused_label", "unknown")
    fused_conf = float(entry.get("fused_confidence", 0.0))

    # Long-bias heuristic:
    if fused_label == "trend_up":
        base = 0.7
    elif fused_label == "trend_down":
        base = 0.3
    elif fused_label == "chop":
        base = 0.45
    elif fused_label == "volatile":
        base = 0.4
    else:
        base = 0.5

    score = base * 0.7 + fused_conf * 0.3
    return float(max(0.0, min(1.0, score)))


def _stability_component(
    regime_v2: Optional[Dict[str, Any]],
    symbol: str,
    timeframe: str,
) -> float:
    """
    Stability here is a proxy for regime inertia: if inertia_applied is high
    and health is ok, we treat that as more stable.
    """
    if not regime_v2:
        return 0.5

    # Handle versioned format
    symbols_data = regime_v2.get("symbols", {})
    key = f"{symbol}:{timeframe}"
    entry = symbols_data.get(key)
    if not entry:
        return 0.5

    inertia_applied = float(entry.get("inertia_applied", 0.0))
    health = entry.get("health", {}) or {}
    status = health.get("status", "ok")

    base = 0.5 + 0.4 * inertia_applied  # up to 0.9
    if status != "ok":
        base *= 0.7
    return float(max(0.0, min(1.0, base)))


def _hybrid_lane_v2(
    pf_quality: float,
    sample_size: float,
    regime_alignment: float,
    stability: float,
) -> HybridLaneV2:
    """
    Hybrid Lane V2 logic with negative boost.

    boost in [-0.3, 0.3]:
      +ve = more aggressive
      -ve = more conservative
    """
    # Risk base: we penalize weak PF or low sample or unstable regime
    avg_core = (pf_quality + regime_alignment) / 2.0
    avg_support = (sample_size + stability) / 2.0
    composite = 0.7 * avg_core + 0.3 * avg_support

    # Map composite [0,1] to [-0.3, 0.3] non-linearly
    centered = composite - 0.5  # [-0.5, 0.5]
    boost = 0.6 * centered      # [-0.3, 0.3]

    if boost > 0.05:
        lane = "boost"
    elif boost < -0.05:
        lane = "brake"
    else:
        lane = "normal"

    if lane == "boost":
        reason = "PF & regime alignment strong – allowing modest positive boost."
    elif lane == "brake":
        reason = "Weak PF or regime alignment instability – applying negative boost."
    else:
        reason = "Mixed signals – staying neutral on hybrid lane boost."

    return HybridLaneV2(
        lane=lane,
        boost=float(round(boost, 3)),
        reason=reason,
    )


def compute_confidence_v2_for_symbol(
    symbol: str,
    timeframe: str,
    pf_local: Optional[Dict[str, Any]],
    regime_v2: Optional[Dict[str, Any]],
) -> ConfidenceV2Snapshot:
    health: Dict[str, Any] = {"status": "ok", "reasons": []}

    pf_quality, sample_score = _pf_component_for_symbol(pf_local, symbol)
    regime_align = _regime_alignment_component(regime_v2, symbol, timeframe)
    stability = _stability_component(regime_v2, symbol, timeframe)

    components = ConfidenceComponents(
        pf_quality=float(round(pf_quality, 3)),
        sample_size=float(round(sample_score, 3)),
        regime_alignment=float(round(regime_align, 3)),
        stability=float(round(stability, 3)),
    )
    weights = ConfidenceWeights()

    # Weighted sum
    overall = (
        components.pf_quality * weights.pf_quality +
        components.sample_size * weights.sample_size +
        components.regime_alignment * weights.regime_alignment +
        components.stability * weights.stability
    )

    # Constrain to [0,1]
    overall = float(max(0.0, min(1.0, overall)))

    # Hybrid lane overlay
    lane = _hybrid_lane_v2(
        pf_quality=components.pf_quality,
        sample_size=components.sample_size,
        regime_alignment=components.regime_alignment,
        stability=components.stability,
    )

    snapshot = ConfidenceV2Snapshot(
        symbol=symbol,
        timeframe=timeframe,
        overall=float(round(overall, 3)),
        components=components,
        weights=weights,
        hybrid_lane=lane,
        asof_iso=datetime.now(timezone.utc).isoformat(),
        health=health,
    )
    return snapshot


def run_confidence_v2_for_universe(
    symbols: List[str],
    timeframe: str = "15m",
) -> Dict[str, Dict[str, Any]]:
    """
    Entrypoint for NIGHTLY research cycle.
    """
    pf_local = _safe_read_json(PF_LOCAL_PATH)
    regime_v2 = _safe_read_json(REGIME_V2_PATH)

    results: Dict[str, Dict[str, Any]] = {}
    issues: List[str] = []

    if pf_local is None:
        issues.append("pf_local.json missing – PF-based components defaulted.")
    if regime_v2 is None:
        issues.append("regime_fusion.json missing – regime components defaulted.")

    for symbol in symbols:
        try:
            snap = compute_confidence_v2_for_symbol(
                symbol=symbol,
                timeframe=timeframe,
                pf_local=pf_local,
                regime_v2=regime_v2,
            )
            results[f"{symbol}:{timeframe}"] = snap.to_dict()
        except Exception as exc:
            issues.append(f"{symbol} compute_failed: {exc}")

    CONF_V2_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "v2.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "health": {
            "status": "ok" if not issues else "degraded",
            "reasons": issues,
        },
        "symbols": results,
    }
    with CONF_V2_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    return results


__all__ = [
    "ConfidenceComponents",
    "ConfidenceWeights",
    "HybridLaneV2",
    "ConfidenceV2Snapshot",
    "run_confidence_v2_for_universe",
    "compute_confidence_v2_for_symbol",
]

