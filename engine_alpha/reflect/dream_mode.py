"""
Dream Mode - Phase 6 (Paper only)
Nightly counterfactual replay exploring gate variations.
"""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

import yaml

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.regime import RegimeClassifier


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _load_gates() -> Dict[str, Any]:
    gates_path = CONFIG / "gates.yaml"
    if gates_path.exists():
        try:
            with open(gates_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


def _baseline_entry(gates: Dict[str, Any]) -> float:
    entry_conf = gates.get("entry_exit", {}).get("entry_min_conf", {})
    if isinstance(entry_conf, dict) and entry_conf:
        return sum(entry_conf.values()) / len(entry_conf)
    return 0.6


def _baseline_exit(gates: Dict[str, Any]) -> float:
    return float(gates.get("entry_exit", {}).get("exit_min_conf", 0.42))


def _baseline_flip(gates: Dict[str, Any]) -> float:
    return float(gates.get("entry_exit", {}).get("reverse_min_conf", 0.55))


def _simulate_pf(
    steps: List[Dict[str, float]],
    entry_min: float,
    exit_min: float,
    flip_min: float,
) -> float:
    position = 0  # -1, 0, +1
    wins = 0.0
    losses = 0.0

    for step in steps:
        direction = step["dir"]
        conf = step["conf"]
        ret = step["ret"]

        if position == 0:
            if direction != 0 and conf >= entry_min:
                position = direction
        else:
            pnl = position * ret
            if pnl > 0:
                wins += pnl
            elif pnl < 0:
                losses += -pnl

            if conf < exit_min:
                position = 0
            elif direction != 0 and direction != position and conf >= flip_min:
                position = direction

    if losses <= 0:
        return wins if wins > 0 else 1.0
    return wins / losses


def _collect_steps(window_steps: int) -> List[Dict[str, float]]:
    classifier = RegimeClassifier()
    steps: List[Dict[str, float]] = []
    for _ in range(window_steps):
        signal_result = get_signal_vector()
        decision = decide(signal_result["signal_vector"], signal_result["raw_registry"], classifier)
        steps.append(
            {
                "dir": decision["final"]["dir"],
                "conf": float(decision["final"]["conf"]),
                "ret": float(
                    signal_result["raw_registry"].get("Ret_G5", {}).get("value", 0.0)
                ),
            }
        )
    return steps


def _build_combos(entry: float, exit_: float, flip: float) -> List[Tuple[float, float, float]]:
    offsets = [-0.02, 0.0, 0.02]
    def clamp(val: float) -> float:
        return max(0.01, min(0.99, val))
    entry_opts = sorted({clamp(entry + d) for d in offsets})
    exit_opts = sorted({clamp(exit_ + d) for d in offsets})
    flip_opts = sorted({clamp(flip + d) for d in offsets})
    combos: List[Tuple[float, float, float]] = []
    for e, x, f in product(entry_opts, exit_opts, flip_opts):
        combos.append((e, x, f))
    return combos


def run_dream(window_steps: int = 200) -> Dict[str, Any]:
    """
    Replay recent signal vectors, test gate variations, and log proposals.
    """
    gates = _load_gates()
    entry_base = _baseline_entry(gates)
    exit_base = _baseline_exit(gates)
    flip_base = _baseline_flip(gates)

    steps = _collect_steps(window_steps)
    combos = _build_combos(entry_base, exit_base, flip_base)

    pf_results: List[Dict[str, Any]] = []
    for entry_min, exit_min, flip_min in combos:
        pf = _simulate_pf(steps, entry_min, exit_min, flip_min)
        pf_results.append(
            {
                "entry_min": entry_min,
                "exit_min": exit_min,
                "flip_min": flip_min,
                "pf_cf": pf,
            }
        )

    # Baseline combo closest to base values
    baseline_pf = _simulate_pf(steps, entry_base, exit_base, flip_base)

    # Current PF from reports (if available)
    pf_local_data = _read_json(REPORTS / "pf_local.json") or {"pf": baseline_pf}
    pf_local = float(pf_local_data.get("pf", baseline_pf))

    best = max(pf_results, key=lambda x: x["pf_cf"], default=None)
    if best is None:
        best = {
            "entry_min": entry_base,
            "exit_min": exit_base,
            "flip_min": flip_base,
            "pf_cf": baseline_pf,
        }

    delta = best["pf_cf"] - pf_local
    improvement_threshold = 0.05  # requires at least +0.05 PF improvement
    proposal_kind = "update_gates" if delta > improvement_threshold else "hold"

    log_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "window_steps": window_steps,
        "entry_base": entry_base,
        "exit_base": exit_base,
        "flip_base": flip_base,
        "pf_local": pf_local,
        "baseline_pf_cf": baseline_pf,
        "best_combo": best,
        "best_delta": delta,
        "proposal_kind": proposal_kind,
    }

    dream_log = REPORTS / "dream_log.jsonl"
    dream_log.parent.mkdir(parents=True, exist_ok=True)
    with open(dream_log, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    proposal = {
        "ts": log_entry["ts"],
        "proposal_kind": proposal_kind,
        "best_combo": best,
        "pf_local": pf_local,
        "pf_cf": best["pf_cf"],
        "delta": delta,
    }

    proposals_path = REPORTS / "dream_proposals.json"
    with open(proposals_path, "w") as f:
        json.dump(proposal, f, indent=2)

    return {"log": log_entry, "proposal": proposal, "combos_tested": len(combos)}
