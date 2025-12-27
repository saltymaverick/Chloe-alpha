"""
Reflection packet builder.

Aggregates B1-B6 primitives and key context into a compact reflection packet
for GPT analysis and parameter tuning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from engine_alpha.core.paths import REPORTS


def _read_json(path: Path) -> Dict[str, Any] | None:
    """Safely read JSON file."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _get_confidence_fallback() -> tuple[float | None, str | None]:
    """
    Get confidence and regime from confidence_snapshot.json as fallback.
    
    Returns:
        Tuple of (confidence_overall, regime)
    """
    snap = _read_json(REPORTS / "confidence_snapshot.json")
    if not snap:
        return None, None
    
    # Support both shapes
    overall = snap.get("confidence_overall") or snap.get("overall")
    regime = snap.get("regime")
    
    try:
        overall_float = float(overall) if overall is not None else None
    except (ValueError, TypeError):
        overall_float = None
    
    return overall_float, regime


def _get_regime_fallback() -> str | None:
    """
    Get regime from regime_snapshot.json (canonical) as fallback.
    """
    snap = _read_json(REPORTS / "regime_snapshot.json")
    if not snap:
        return None
    regime = snap.get("regime")
    return regime if isinstance(regime, str) and regime else None


def _get_opportunity_fallback() -> Dict[str, Any] | None:
    """
    Load opportunity_snapshot.json (instrumentation) as fallback.

    This is used to hydrate reflection packets built from snapshots that do not
    include the observer-only opportunity instrumentation fields.
    """
    snap = _read_json(REPORTS / "opportunity_snapshot.json")
    return snap if isinstance(snap, dict) else None


def _hydrate_from_fallback(dst: Dict[str, Any], src: Dict[str, Any], keys: List[str]) -> None:
    """
    Copy selected keys from src -> dst only when dst is missing/None.
    """
    for k in keys:
        if k in src and (k not in dst or dst.get(k) is None):
            dst[k] = src.get(k)


def build_reflection_packet(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a compact reflection packet from snapshot.
    
    Args:
        snapshot: Snapshot dict with primitives and context
        
    Returns:
        Compact reflection packet dict
    """
    packet: Dict[str, Any] = {}
    
    # Header
    packet["ts"] = snapshot.get("ts")
    packet["symbol"] = snapshot.get("symbol")
    packet["timeframe"] = snapshot.get("timeframe")
    packet["mode"] = snapshot.get("mode")
    packet["tick_id"] = snapshot.get("meta", {}).get("tick_id")
    
    # Market (compact)
    market = snapshot.get("market", {})
    packet["market"] = {
        "price": market.get("price"),
        "ohlcv_source": market.get("ohlcv_source"),
        "ohlcv_age_s": market.get("ohlcv_age_s"),
        "ohlcv_is_stale": market.get("ohlcv_is_stale"),
    }
    
    # Decision (if present)
    decision = snapshot.get("decision", {})
    decision_confidence = decision.get("confidence")
    
    # Fallback to confidence_snapshot.json if decision confidence is missing
    if decision_confidence is None:
        confidence_overall, regime = _get_confidence_fallback()
        if confidence_overall is not None:
            try:
                decision_confidence = float(confidence_overall)
            except (ValueError, TypeError):
                decision_confidence = None
        
        # Also update regime in opportunity if missing
        if regime and regime != "unknown":
            primitives = snapshot.get("primitives", {})
            opportunity = primitives.get("opportunity", {})
            if opportunity.get("regime") is None or opportunity.get("regime") == "unknown":
                opportunity["regime"] = regime
    
    packet["decision"] = {
        "action": decision.get("action"),
        "confidence": decision_confidence,
        "reason": decision.get("reason"),
    }
    
    # Add confidence_overall to packet for reference (if we have confidence)
    if decision_confidence is not None:
        packet["confidence_overall"] = float(decision_confidence)
    
    # Position (if present)
    execution = snapshot.get("execution", {})
    position = execution.get("position", {})
    packet["position"] = {
        "is_open": position.get("is_open"),
        "side": position.get("side"),
        "entry_price": position.get("entry_price"),
    }
    
    # Primitives (B1-B6)
    primitives = snapshot.get("primitives", {})
    
    # B1: Velocity
    velocity = primitives.get("velocity", {})
    packet["primitives"] = {
        "velocity": {
            "pci_per_s": velocity.get("pci_per_s"),
            "confidence_per_s": velocity.get("confidence_per_s"),
        },
    }
    
    # B2: Decay
    decay = primitives.get("decay", {})
    packet["primitives"]["decay"] = {
        "confidence_decayed": decay.get("confidence_decayed"),
        "confidence_refreshed": decay.get("confidence_refreshed"),
        "pci_decayed": decay.get("pci_decayed"),
        "pci_refreshed": decay.get("pci_refreshed"),
    }
    
    # B3: Compression
    compression = primitives.get("compression", {})
    packet["primitives"]["compression"] = {
        "compression_score": compression.get("compression_score"),
        "is_compressed": compression.get("is_compressed"),
        "time_in_compression_s": compression.get("time_in_compression_s"),
        "atr_ratio": compression.get("atr_ratio"),
        "bb_ratio": compression.get("bb_ratio"),
    }
    
    # B4: Invalidation
    invalidation = primitives.get("invalidation", {})
    packet["primitives"]["invalidation"] = {
        "thesis_health_score": invalidation.get("thesis_health_score"),
        "soft_invalidation_score": invalidation.get("soft_invalidation_score"),
        "invalidation_flags": invalidation.get("invalidation_flags", []),
    }
    
    # B5: Opportunity
    opportunity = primitives.get("opportunity", {})
    if not isinstance(opportunity, dict):
        opportunity = {}

    # Hydrate opportunity from canonical observer snapshot when fields are missing.
    # This prevents schema drift when different writers (loop vs policy_refresh)
    # build packets with different snapshot shapes.
    opp_fallback = _get_opportunity_fallback()
    if opp_fallback:
        _hydrate_from_fallback(
            opportunity,
            opp_fallback,
            keys=[
                "regime",
                "eligible",
                "eligible_now",
                "eligible_now_reason",
                "density_ewma",
                "density_current",
                "density_floor",
                "density_global",
                "density_by_regime",
                "global_density_ewma",
                "last_update_ts",
                "events_seen_24h",
                "candidates_seen_24h",
                "eligible_seen_24h",
                "reasons_top",
                "eligible_rate",
                "hostile_rate",
                "score_low_rate",
                "capital_mode",
                "execql_hostile_count",
                "execql_hostile_top_component",
                "score_too_low_count",
                "avg_score_gap",
                "champion_override_count",
                "champion_override_rate",
                "champion_override_mode",
                "champion_override_examples",
            ],
        )

    # Canonical regime fallback
    if opportunity.get("regime") in (None, "unknown"):
        regime_fb = _get_regime_fallback()
        if regime_fb:
            opportunity["regime"] = regime_fb

    packet["primitives"]["opportunity"] = {
        "regime": opportunity.get("regime"),
        "global_regime": opportunity.get("global_regime"),
        "symbol_regime": opportunity.get("symbol_regime"),
        "effective_regime": opportunity.get("effective_regime") or opportunity.get("regime"),
        "regime_agree": opportunity.get("regime_agree"),
        "eligible": opportunity.get("eligible"),
        "eligible_now": opportunity.get("eligible_now"),
        "eligible_now_reason": opportunity.get("eligible_now_reason"),
        "density_ewma": opportunity.get("density_ewma"),
        "density_current": opportunity.get("density_current"),
        "density_floor": opportunity.get("density_floor"),
        "density_global": opportunity.get("density_global") or opportunity.get("density_ewma"),
        "density_by_regime": opportunity.get("density_by_regime", {}),
        "global_density_ewma": opportunity.get("global_density_ewma"),
        # Instrumentation fields (if present)
        "last_update_ts": opportunity.get("last_update_ts"),
        "events_seen_24h": opportunity.get("events_seen_24h"),
        "candidates_seen_24h": opportunity.get("candidates_seen_24h"),
        "eligible_seen_24h": opportunity.get("eligible_seen_24h"),
        "reasons_top": opportunity.get("reasons_top", []),
        # Derived metrics
        "eligible_rate": opportunity.get("eligible_rate"),
        "hostile_rate": opportunity.get("hostile_rate"),
        "score_low_rate": opportunity.get("score_low_rate"),
        # Capital mode context
        "capital_mode": opportunity.get("capital_mode"),
        # ExecQL details
        "execql_hostile_count": opportunity.get("execql_hostile_count"),
        "execql_hostile_top_component": opportunity.get("execql_hostile_top_component"),
        # Score details
        "score_too_low_count": opportunity.get("score_too_low_count"),
        "avg_score_gap": opportunity.get("avg_score_gap"),
        # Champion override details
        "champion_override_count": opportunity.get("champion_override_count"),
        "champion_override_rate": opportunity.get("champion_override_rate"),
        "champion_override_mode": opportunity.get("champion_override_mode"),
        "champion_override_examples": opportunity.get("champion_override_examples", []),
    }
    
    # B6: Self-Trust
    self_trust = primitives.get("self_trust", {})
    packet["primitives"]["self_trust"] = {
        "self_trust_score": self_trust.get("self_trust_score"),
        "n_samples": self_trust.get("n_samples"),
        "samples_processed": self_trust.get("samples_processed"),
    }
    
    # Meta: issues
    packet["meta"] = {
        "issues": summarize_issues(packet),
    }
    
    return packet


def summarize_issues(packet: Dict[str, Any]) -> List[str]:
    """
    Summarize issues from packet into issue codes.
    
    Args:
        packet: Reflection packet dict
        
    Returns:
        List of issue code strings
    """
    issues: List[str] = []
    
    # Market issues
    market = packet.get("market", {})
    if market.get("ohlcv_is_stale") is True:
        issues.append("FEED_STALE")
    
    # Decision issues
    decision = packet.get("decision", {})
    decision_conf = decision.get("confidence")
    packet_conf = packet.get("confidence_overall")
    
    # Only flag CONFIDENCE_MISSING if both decision confidence and packet confidence are missing
    if decision_conf is None and packet_conf is None:
        issues.append("CONFIDENCE_MISSING")
    
    # Regime issues
    opportunity = packet.get("primitives", {}).get("opportunity", {})
    regime = opportunity.get("regime")
    # Also check packet-level regime if present
    if not regime or regime == "unknown":
        regime = packet.get("regime")
    if regime is None or regime == "unknown":
        issues.append("REGIME_UNKNOWN")
    
    # Compression issues
    compression = packet.get("primitives", {}).get("compression", {})
    if compression.get("compression_score") is None:
        issues.append("COMPRESSION_NULL")
    
    # Self-trust issues
    self_trust = packet.get("primitives", {}).get("self_trust", {})
    if self_trust.get("self_trust_score") is None and self_trust.get("n_samples", 0) == 0:
        issues.append("SELF_TRUST_UNAVAILABLE")
    
    # Opportunity issues
    if opportunity.get("eligible") is False:
        issues.append("OPPORTUNITY_LOW")
    
    return issues

