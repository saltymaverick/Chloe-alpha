#!/usr/bin/env python3
"""
Reflection Packet Writer
------------------------

Builds and writes reports/reflection_packet.json from current state.
This ensures check-in scripts always read a fresh packet with fallback data.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.reflection_packet import build_reflection_packet
from engine_alpha.core.self_trust import compute_self_trust_from_trade_log
from engine_alpha.core.opportunity_density import load_state as load_opportunity_state
from engine_alpha.core.primitive_state import load_state as load_primitive_state
from engine_alpha.core.velocity import compute_velocities
from engine_alpha.core.decay import compute_decays


def build_minimal_snapshot() -> dict[str, any]:
    """
    Build a minimal snapshot from current state files.
    
    This allows building a reflection packet even when the trading loop isn't running.
    """
    now = datetime.now(timezone.utc)
    
    # Load self-trust metrics
    self_trust_metrics = compute_self_trust_from_trade_log(now.isoformat())
    
    # Load opportunity state
    opportunity_state = load_opportunity_state()

    # Load primitive state
    primitive_state = load_primitive_state()

    # Load opportunity snapshot (with instrumentation)
    opportunity_snapshot = {}
    opp_snapshot_path = REPORTS / "opportunity_snapshot.json"
    if opp_snapshot_path.exists():
        try:
            with opp_snapshot_path.open("r", encoding="utf-8") as f:
                opportunity_snapshot = json.load(f)
        except Exception as e:
            # Debug: print error if loading fails
            print(f"WARNING: Failed to load opportunity_snapshot: {e}", file=sys.stderr)
            pass
    
    # Load confidence snapshot
    confidence_data = {}
    conf_path = REPORTS / "confidence_snapshot.json"
    if conf_path.exists():
        try:
            with conf_path.open("r", encoding="utf-8") as f:
                confidence_data = json.load(f)
        except Exception:
            pass
    
    # Load regime snapshot
    regime_data = {}
    regime_path = REPORTS / "regime_snapshot.json"
    if regime_path.exists():
        try:
            with regime_path.open("r", encoding="utf-8") as f:
                regime_data = json.load(f)
        except Exception:
            pass
    
    # Load compression snapshot
    compression_data = {}
    compression_path = REPORTS / "compression_snapshot.json"
    if compression_path.exists():
        try:
            with compression_path.open("r", encoding="utf-8") as f:
                compression_data = json.load(f)
        except Exception:
            pass
    
    # Build minimal snapshot
    snapshot = {
        "ts": now.isoformat(),
        "symbol": "ETHUSDT",  # Default symbol
        "timeframe": "15m",
        "mode": "PAPER",
        "meta": {
            "tick_id": f"{now.isoformat()}_ETHUSDT_15m",
        },
        "decision": {
            "action": None,
            "confidence": None,  # Will be populated by fallback
            "reason": None,
        },
        "market": {
            "price": None,
            "ohlcv_source": "unknown",
            "ohlcv_age_s": None,
            "ohlcv_is_stale": False,  # Will be checked by PriceFeedHealth
        },
        "execution": {
            "position": {
                "is_open": False,
                "side": None,
                "entry_price": None,
            },
        },
        "primitives": {
            "velocity": {
                "pci_per_s": None,
                "confidence_per_s": None,
            },
            "decay": {
                "confidence_decayed": None,
                "confidence_refreshed": False,
                "pci_decayed": None,
                "pci_refreshed": False,
            },
            "compression": {
                "compression_score": compression_data.get("compression_score"),
                "is_compressed": compression_data.get("is_compressed", False),
                "time_in_compression_s": None,
                "atr_ratio": compression_data.get("atr_ratio"),
                "bb_ratio": compression_data.get("bb_ratio"),
            },
            "invalidation": {
                "thesis_health_score": None,
                "soft_invalidation_score": None,
                "invalidation_flags": [],
            },
            "opportunity": {
                "regime": regime_data.get("regime") or opportunity_snapshot.get("regime") or opportunity_state.get("regime", "unknown"),
                "eligible": opportunity_snapshot.get("eligible") if "eligible" in opportunity_snapshot else opportunity_state.get("eligible", False),
                "eligible_now": opportunity_snapshot.get("eligible_now"),
                "eligible_now_reason": opportunity_snapshot.get("eligible_now_reason"),
                "density_ewma": opportunity_snapshot.get("density_ewma") if "density_ewma" in opportunity_snapshot else opportunity_state.get("density_ewma", 0.0),
                "density_current": opportunity_snapshot.get("density_current"),
                "density_floor": opportunity_snapshot.get("density_floor"),
                "density_global": opportunity_snapshot.get("density_ewma"),  # Global density
                "density_by_regime": opportunity_snapshot.get("density_by_regime", {}),  # Per-regime densities
                "global_density_ewma": opportunity_snapshot.get("global_density_ewma") if "global_density_ewma" in opportunity_snapshot else opportunity_state.get("global_density_ewma", 0.0),
                "last_update_ts": opportunity_snapshot.get("last_update_ts"),
                "events_seen_24h": opportunity_snapshot.get("events_seen_24h"),
                "candidates_seen_24h": opportunity_snapshot.get("candidates_seen_24h"),
                "eligible_seen_24h": opportunity_snapshot.get("eligible_seen_24h"),
                "reasons_top": opportunity_snapshot.get("reasons_top", []),
                # Derived metrics
                "eligible_rate": opportunity_snapshot.get("eligible_rate"),
                "hostile_rate": opportunity_snapshot.get("hostile_rate"),
                "score_low_rate": opportunity_snapshot.get("score_low_rate"),
                # Capital mode context
                "capital_mode": opportunity_snapshot.get("capital_mode"),
                # ExecQL details
                "execql_hostile_count": opportunity_snapshot.get("execql_hostile_count"),
                "execql_hostile_top_component": opportunity_snapshot.get("execql_hostile_top_component"),
                # Score details
                "score_too_low_count": opportunity_snapshot.get("score_too_low_count"),
                "avg_score_gap": opportunity_snapshot.get("avg_score_gap"),
                # Champion override details
                "champion_override_count": opportunity_snapshot.get("champion_override_count"),
                "champion_override_rate": opportunity_snapshot.get("champion_override_rate"),
                "champion_override_mode": opportunity_snapshot.get("champion_override_mode"),
                "champion_override_examples": opportunity_snapshot.get("champion_override_examples", []),
            },
            "self_trust": {
                "self_trust_score": self_trust_metrics.get("self_trust_score"),
                "n_samples": self_trust_metrics.get("n_samples", 0),
                "samples_processed": self_trust_metrics.get("samples_processed", 0),
            },
        },
    }

    # Compute velocities and decays from current state
    ts_iso = now.isoformat()
    current_values = {}
    for key in ["pci", "confidence"]:
        entry = primitive_state.get(key)
        if entry and isinstance(entry, dict):
            current_values[key] = entry.get("value")

    velocities, _ = compute_velocities(ts_iso, current_values, primitive_state, list(current_values.keys()))
    decay_spec = {
        "pci": {"half_life_s": 15 * 60},
        "confidence": {"half_life_s": 30 * 60},
    }
    decays, _ = compute_decays(ts_iso, current_values, primitive_state, decay_spec)

    # Update primitives with computed values
    snapshot["primitives"]["velocity"]["pci_per_s"] = velocities.get("pci_per_s")
    snapshot["primitives"]["velocity"]["confidence_per_s"] = velocities.get("confidence_per_s")
    snapshot["primitives"]["decay"]["confidence_decayed"] = decays.get("confidence_decayed")
    snapshot["primitives"]["decay"]["confidence_refreshed"] = decays.get("confidence_refreshed", False)
    snapshot["primitives"]["decay"]["pci_decayed"] = decays.get("pci_decayed")
    snapshot["primitives"]["decay"]["pci_refreshed"] = decays.get("pci_refreshed", False)

    # Compute velocities and decays from current state
    ts_iso = now.isoformat()
    current_values = {}
    for key in ["pci", "confidence"]:
        entry = primitive_state.get(key)
        if entry and isinstance(entry, dict):
            current_values[key] = entry.get("value")

    velocities, _ = compute_velocities(ts_iso, current_values, primitive_state, list(current_values.keys()))
    decay_spec = {
        "pci": {"half_life_s": 15 * 60},
        "confidence": {"half_life_s": 30 * 60},
    }
    decays, _ = compute_decays(ts_iso, current_values, primitive_state, decay_spec)

    # Update primitives with computed values
    snapshot["primitives"]["velocity"]["pci_per_s"] = velocities.get("pci_per_s")
    snapshot["primitives"]["velocity"]["confidence_per_s"] = velocities.get("confidence_per_s")
    snapshot["primitives"]["decay"]["confidence_decayed"] = decays.get("confidence_decayed")
    snapshot["primitives"]["decay"]["confidence_refreshed"] = decays.get("confidence_refreshed", False)
    snapshot["primitives"]["decay"]["pci_decayed"] = decays.get("pci_decayed")
    snapshot["primitives"]["decay"]["pci_refreshed"] = decays.get("pci_refreshed", False)

    # Try to get live price and feed health
    try:
        from engine_alpha.data.price_feed_health import is_price_feed_ok
        feed_ok, feed_meta = is_price_feed_ok("ETHUSDT", max_age_seconds=900, require_price=True)
        if feed_ok:
            snapshot["market"]["ohlcv_source"] = feed_meta.get("source_used", "unknown")
            snapshot["market"]["ohlcv_age_s"] = feed_meta.get("age_seconds")
            snapshot["market"]["ohlcv_is_stale"] = False
            snapshot["market"]["price"] = feed_meta.get("latest_price")
        else:
            snapshot["market"]["ohlcv_is_stale"] = True
    except Exception:
        pass
    
    return snapshot


def main() -> int:
    """Main entry point."""
    snapshot = build_minimal_snapshot()
    packet = build_reflection_packet(snapshot)
    
    # Write to reports/reflection_packet.json
    output_path = REPORTS / "reflection_packet.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(packet, f, indent=2, sort_keys=True)
    
    conf_str = f"{packet.get('decision', {}).get('confidence'):.3f}" if packet.get('decision', {}).get('confidence') is not None else "None"
    issues = packet.get("meta", {}).get("issues", [])
    print(f"Reflection packet: confidence={conf_str}, issues={issues}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

