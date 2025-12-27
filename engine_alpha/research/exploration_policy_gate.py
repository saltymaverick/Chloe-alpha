"""
Exploration Policy Gate (Phase 3b + 3d)
----------------------------------------

This module implements the runtime gate that applies Exploration Policy V3
to exploration entries in PAPER mode.

Responsibilities:
  * Read reports/research/exploration_policy_v3.json
  * For a given symbol, decide whether exploration is allowed:
      - Phase 3b: If policy.level == "blocked" OR allow_new_entries == False:
            returns False (hard block exploration for this symbol)
      - Phase 3d: If throttle_factor < 1.0 (reduced level):
            probabilistically throttles exploration entries (Bernoulli trial)
      - Otherwise: returns original can_open value.
  * Log any blocks/throttles to reports/research/exploration_policy_gate_log.jsonl

Safety:
  * PAPER-ONLY: Call this gate only for exploration lane in paper mode.
  * RESTRICTIVE ONLY: It never turns a False into True; it only blocks/throttles.
  * NO CONFIG MUTATION: It does not write to configs or change strategy.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


POLICY_PATH = Path("reports/research/exploration_policy_v3.json")
LOG_PATH = Path("reports/research/exploration_policy_gate_log.jsonl")


@dataclass
class ExplorationGateDecision:
    symbol: str
    lane: str
    original_can_open: bool
    final_can_open: bool
    policy_level: Optional[str]
    allow_new_entries: Optional[bool]
    throttle_factor: Optional[float]
    pf_7d: Optional[float]
    pf_30d: Optional[float]
    reason: str
    ts: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_policy() -> Dict[str, Any]:
    if not POLICY_PATH.exists():
        return {}
    try:
        with POLICY_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _get_symbol_policy(policy: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    symbols = policy.get("symbols", {})
    return symbols.get(symbol, {})


def _append_log(decision: ExplorationGateDecision) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(decision.to_dict()) + "\n")
    except Exception:
        # Logging failure must not break trading logic
        return


def apply_exploration_policy_gate(
    symbol: str,
    can_open: bool,
    lane: str,
    mode: str = "PAPER",
) -> Tuple[bool, ExplorationGateDecision]:
    """
    Apply Exploration Policy V3 to a single exploration opportunity.

    Args:
        symbol: Trading symbol, e.g. "ETHUSDT".
        can_open: Result of existing exploration gating logic.
        lane: Lane identifier, e.g. "exploration" or "normal".
        mode: Engine mode, should be "PAPER" here.

    Returns:
        (final_can_open, decision)

    Important:
      * This gate NEVER turns a False into True.
      * For non-exploration lanes or non-PAPER mode, it returns can_open unchanged.
    """
    ts = datetime.now(timezone.utc).isoformat()

    # Only apply in PAPER exploration lane
    if lane.lower() != "exploration" or mode.upper() != "PAPER":
        decision = ExplorationGateDecision(
            symbol=symbol,
            lane=lane,
            original_can_open=can_open,
            final_can_open=can_open,
            policy_level=None,
            allow_new_entries=None,
            throttle_factor=None,
            pf_7d=None,
            pf_30d=None,
            reason="Gate not applied (non-exploration or non-PAPER).",
            ts=ts,
        )
        return can_open, decision

    policy = _load_policy()
    sym_policy = _get_symbol_policy(policy, symbol)

    level = sym_policy.get("level")
    allow_new_entries = sym_policy.get("allow_new_entries")
    pf_7d = sym_policy.get("pf_7d")
    pf_30d = sym_policy.get("pf_30d")
    throttle_factor_raw = sym_policy.get("throttle_factor")
    try:
        throttle_factor = float(throttle_factor_raw) if throttle_factor_raw is not None else None
    except Exception:
        throttle_factor = None

    final_can_open = can_open
    reason = "Policy allows exploration."

    # Phase 5g: Check quarantine (blocks new entries, never blocks exits)
    if can_open:
        try:
            from engine_alpha.core.paths import REPORTS
            quarantine_path = REPORTS / "risk" / "quarantine.json"
            if quarantine_path.exists():
                with quarantine_path.open("r", encoding="utf-8") as f:
                    quarantine = json.load(f)
                if quarantine.get("enabled", False):
                    blocked_symbols = quarantine.get("blocked_symbols", [])
                    if symbol in blocked_symbols:
                        final_can_open = False
                        reason = f"Blocked by quarantine (loss contributor: {symbol})."
        except Exception:
            # Fail-safe: if quarantine check fails, continue with policy check
            pass

    # Only ever *block* additional exploration; never enable
    if can_open and final_can_open:
        # 1) Hard block for level=blocked or allow_new_entries=False (Phase 3b)
        if level == "blocked":
            final_can_open = False
            reason = "Blocked by ExplorationPolicyV3 (level=blocked)."
        elif allow_new_entries is False:
            final_can_open = False
            reason = "Blocked by ExplorationPolicyV3 (allow_new_entries=False)."
        # 2) Throttle for reduced level (Phase 3d) based on throttle_factor
        elif throttle_factor is not None and 0.0 < throttle_factor < 1.0:
            # Bernoulli trial: keep only a fraction of otherwise-allowed exploration entries
            r = random.random()
            if r > throttle_factor:
                final_can_open = False
                reason = (
                    f"Throttled by ExplorationPolicyV3 "
                    f"(throttle_factor={throttle_factor:.2f}, r={r:.3f})."
                )

    decision = ExplorationGateDecision(
        symbol=symbol,
        lane=lane,
        original_can_open=can_open,
        final_can_open=final_can_open,
        policy_level=level,
        allow_new_entries=allow_new_entries,
        throttle_factor=throttle_factor,
        pf_7d=pf_7d,
        pf_30d=pf_30d,
        reason=reason,
        ts=ts,
    )

    # Only log when the gate changed behavior
    if final_can_open != can_open:
        _append_log(decision)

    return final_can_open, decision


__all__ = ["apply_exploration_policy_gate", "ExplorationGateDecision"]

