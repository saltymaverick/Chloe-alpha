"""
Strategy Evolver - Phase 7 (Sandbox)
Explores parameter variants via counterfactual replay.
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
from engine_alpha.reflect.trade_analysis import pf_from_trades
from engine_alpha.evolve.strategy_namer import name_from_params


DEFAULT_GRID = {
    "entry_min": [0.54, 0.58, 0.62],
    "exit_min": [0.38, 0.42, 0.46],
    "flip_min": [0.50, 0.55, 0.60],
}


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


def _collect_steps(window_steps: int) -> List[Dict[str, float]]:
    classifier = RegimeClassifier()
    steps: List[Dict[str, float]] = []
    for _ in range(window_steps):
        result = get_signal_vector()
        decision = decide(result["signal_vector"], result["raw_registry"], classifier)
        steps.append(
            {
                "dir": decision["final"]["dir"],
                "conf": float(decision["final"]["conf"]),
            }
        )
    return steps


def _simulate_trades(
    steps: List[Dict[str, float]],
    entry_min: float,
    exit_min: float,
    flip_min: float,
) -> List[Dict[str, float]]:
    trades: List[Dict[str, float]] = []
    position = 0  # -1, 0, +1

    for step in steps:
        direction = step["dir"]
        conf = step["conf"]

        if position == 0:
            if direction != 0 and conf >= entry_min:
                position = direction
        else:
            if (direction == 0 or conf < exit_min):
                trades.append({"pct": conf})
                position = 0
            elif direction != position and direction != 0 and conf >= flip_min:
                trades.append({"pct": -conf})
                position = direction
            else:
                # hold
                pass

    return trades


def _build_grid(grid: Optional[Dict[str, List[float]]]) -> List[Dict[str, float]]:
    g = grid or DEFAULT_GRID
    entry_vals = g.get("entry_min", DEFAULT_GRID["entry_min"])
    exit_vals = g.get("exit_min", DEFAULT_GRID["exit_min"])
    flip_vals = g.get("flip_min", DEFAULT_GRID["flip_min"])
    combos: List[Dict[str, float]] = []
    for entry_min, exit_min, flip_min in product(entry_vals, exit_vals, flip_vals):
        combos.append({
            "entry_min": entry_min,
            "exit_min": exit_min,
            "flip_min": flip_min,
        })
    return combos


def run_evolver(
    window_steps: int = 200,
    base_params: Optional[Dict[str, float]] = None,
    grid: Optional[Dict[str, List[float]]] = None,
) -> Dict[str, Any]:
    base_params = base_params or {"entry_min": 0.58, "exit_min": 0.42, "flip_min": 0.55}

    pf_local_data = _read_json(REPORTS / "pf_local.json") or {"pf": 0.0}
    baseline_pf_local = float(pf_local_data.get("pf", 0.0))

    steps = _collect_steps(window_steps)
    combos = _build_grid(grid)

    results: List[Dict[str, Any]] = []
    for params in combos:
        trades = _simulate_trades(
            steps,
            params["entry_min"],
            params["exit_min"],
            params["flip_min"],
        )
        pf_cf = pf_from_trades(trades)
        results.append(
            {
                "params": params,
                "pf_cf": pf_cf,
                "trades": len(trades),
            }
        )

    if not results:
        return {
            "best": None,
            "baseline_pf_local": baseline_pf_local,
            "tested": 0,
        }

    results.sort(key=lambda x: x["pf_cf"], reverse=True)
    best = results[0]
    uplift = best["pf_cf"] - baseline_pf_local

    child_name = name_from_params(best["params"])
    ts = datetime.now(timezone.utc).isoformat()

    lineage_entry = {
        "ts": ts,
        "parent": "baseline",
        "child_name": child_name,
        "params": best["params"],
        "pf_cf": best["pf_cf"],
        "uplift": uplift,
    }
    lineage_path = REPORTS / "strategy_lineage.jsonl"
    lineage_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lineage_path, "a") as f:
        f.write(json.dumps(lineage_entry) + "\n")

    top_k = results[: min(5, len(results))]
    run_entry = {
        "ts": ts,
        "window_steps": window_steps,
        "grid_size": len(results),
        "top_results": top_k,
    }
    runs_path = REPORTS / "evolver_runs.jsonl"
    with open(runs_path, "a") as f:
        f.write(json.dumps(run_entry) + "\n")

    return {
        "best": {
            "params": best["params"],
            "pf_cf": best["pf_cf"],
            "uplift": uplift,
            "child_name": child_name,
        },
        "baseline_pf_local": baseline_pf_local,
        "tested": len(results),
    }
