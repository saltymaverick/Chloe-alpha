"""
Dry-Run Logger - Logs decisions and trades to separate files during dry-run mode.

Ensures dry-run mode doesn't pollute real trade logs or PF reports.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS


DRY_RUN_TRADES_PATH = REPORTS / "dry_run_trades.jsonl"
DRY_RUN_DECISIONS_PATH = REPORTS / "dry_run_decisions.jsonl"


def log_dry_run_trade(event: Dict[str, Any]) -> None:
    """
    Log a trade event to dry_run_trades.jsonl (doesn't affect real trades.jsonl).
    
    Args:
        event: Trade event dict (same format as real trades)
    """
    DRY_RUN_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DRY_RUN_TRADES_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")


def log_dry_run_decision(
    tick: int,
    regime_state: Dict[str, Any],
    drift_state: Dict[str, Any],
    confidence_state: Any,
    size_multiplier: float,
    entry_decision: Dict[str, Any],
    exit_decision: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log a decision summary to dry_run_decisions.jsonl.
    
    Args:
        tick: Step/tick number
        regime_state: Regime state dict
        drift_state: Drift state dict
        confidence_state: ConfidenceState object
        size_multiplier: Position size multiplier
        entry_decision: Entry decision dict from should_enter_trade
        exit_decision: Optional exit decision dict from should_exit_trade
    """
    DRY_RUN_DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Extract confidence components if available
    components = {}
    penalties = {}
    if hasattr(confidence_state, 'components'):
        components = confidence_state.components
    if hasattr(confidence_state, 'penalties'):
        penalties = confidence_state.penalties
    
    decision_record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tick": tick,
        "regime": regime_state.get("primary", "unknown") if isinstance(regime_state, dict) else getattr(regime_state, "primary", "unknown"),
        "drift": {
            "drift_score": drift_state.get("drift_score", 0.0) if isinstance(drift_state, dict) else getattr(drift_state, "drift_score", 0.0),
            "pf_local": drift_state.get("pf_local", 0.0) if isinstance(drift_state, dict) else getattr(drift_state, "pf_local", 0.0),
        },
        "confidence": {
            "final": confidence_state.confidence if hasattr(confidence_state, 'confidence') else 0.0,
            "components": components,
            "penalties": penalties,
        },
        "size_multiplier": size_multiplier,
        "entry": entry_decision,
        "exit": exit_decision,
    }
    
    with open(DRY_RUN_DECISIONS_PATH, "a") as f:
        f.write(json.dumps(decision_record) + "\n")


def print_dry_run_summary(
    tick: int,
    regime_state: Dict[str, Any],
    drift_state: Dict[str, Any],
    confidence_state: Any,
    size_multiplier: float,
    entry_decision: Dict[str, Any],
    exit_decision: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Print a compact summary of the decision for this tick.
    
    Args:
        tick: Step/tick number
        regime_state: Regime state dict
        drift_state: Drift state dict
        confidence_state: ConfidenceState object
        size_multiplier: Position size multiplier
        entry_decision: Entry decision dict
        exit_decision: Optional exit decision dict
    """
    regime = regime_state.get("primary", "unknown") if isinstance(regime_state, dict) else getattr(regime_state, "primary", "unknown")
    drift_score = drift_state.get("drift_score", 0.0) if isinstance(drift_state, dict) else getattr(drift_state, "drift_score", 0.0)
    pf_local = drift_state.get("pf_local", 0.0) if isinstance(drift_state, dict) else getattr(drift_state, "pf_local", 0.0)
    
    conf = confidence_state.confidence if hasattr(confidence_state, 'confidence') else 0.0
    components = confidence_state.components if hasattr(confidence_state, 'components') else {}
    penalties = confidence_state.penalties if hasattr(confidence_state, 'penalties') else {}
    
    print(f"\n[Tick {tick}]")
    print(f"  Regime: {regime}")
    print(f"  Drift: score={drift_score:.2f}, pf_local={pf_local:.3f}")
    print(f"  Confidence: {conf:.3f}")
    if components:
        print(f"    Components: flow={components.get('flow', 0.0):.2f}, vol={components.get('volatility', 0.0):.2f}, micro={components.get('microstructure', 0.0):.2f}, cross={components.get('cross_asset', 0.0):.2f}")
    if penalties:
        print(f"    Penalties: regime={penalties.get('regime', 1.0):.2f}, drift={penalties.get('drift', 1.0):.2f}")
    print(f"  Size: {size_multiplier:.2f}x")
    
    if entry_decision.get("enter", False):
        print(f"  ✅ ENTER: {entry_decision.get('direction', 'unknown')} - {entry_decision.get('reason', '')}")
    else:
        print(f"  ⏸ SKIP: {entry_decision.get('reason', 'unknown')}")
    
    if exit_decision and exit_decision.get("exit", False):
        print(f"  🚪 EXIT: {exit_decision.get('reason', 'unknown')}")
    elif exit_decision:
        print(f"  📌 HOLD: {exit_decision.get('reason', 'unknown')}")
