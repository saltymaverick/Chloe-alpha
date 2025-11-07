"""
Council trainer - Phase 19 (analysis only)
Produces proposed council weight adjustments based on recent performance.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from engine_alpha.core.paths import REPORTS, CONFIG

BASELINE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "trend": {"momentum": 0.45, "meanrev": 0.10, "flow": 0.25, "positioning": 0.15, "timing": 0.05},
    "chop": {"momentum": 0.15, "meanrev": 0.45, "flow": 0.20, "positioning": 0.15, "timing": 0.05},
    "high_vol": {"momentum": 0.30, "meanrev": 0.10, "flow": 0.35, "positioning": 0.20, "timing": 0.05},
}
BUCKETS = ["momentum", "meanrev", "flow", "positioning", "timing"]
MAX_DELTA = 0.10

PF_LOCAL_ADJ = REPORTS / "pf_local_adj.json"
CONF_TUNE = REPORTS / "confidence_tune.jsonl"
TRADES_PATH = REPORTS / "trades.jsonl"
WEIGHTS_OUT = REPORTS / "council_weights.json"
LOG_PATH = REPORTS / "council_train_log.jsonl"
SNAPSHOT_PATH = REPORTS / "council_train_snapshot.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _read_jsonl_tail(path: Path, lines: int = 3) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = path.read_text().splitlines()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for line in raw[-lines:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _last_trade_dir() -> int:
    tail = _read_jsonl_tail(TRADES_PATH, lines=5)
    for entry in reversed(tail):
        if entry.get("type") == "close":
            dir_val = entry.get("dir")
            if isinstance(dir_val, (int, float)):
                return int(dir_val)
    return 0


def _load_accounting_bias() -> float:
    pf_adj = _read_json(PF_LOCAL_ADJ).get("pf")
    if isinstance(pf_adj, (int, float)):
        return float(pf_adj)
    return 1.0


def _confidence_bias() -> Dict[str, float]:
    entries = _read_jsonl_tail(CONF_TUNE, lines=3)
    bias: Dict[str, float] = {}
    for entry in entries:
        regime = entry.get("regime")
        delta = entry.get("delta")
        if regime and isinstance(delta, (int, float)):
            bias[regime] = float(delta)
    return bias


def _baseline_snapshot() -> Dict[str, Dict[str, float]]:
    return {regime: weights.copy() for regime, weights in BASELINE_WEIGHTS.items()}


def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(max(val, 0.0) for val in weights.values())
    if total <= 0:
        return weights
    return {k: max(v, 0.0) / total for k, v in weights.items()}


def _apply_constraints(delta: Dict[str, float]) -> Dict[str, float]:
    mean_delta = sum(delta.values()) / len(delta)
    adjusted = {k: max(-MAX_DELTA, min(MAX_DELTA, v - mean_delta)) for k, v in delta.items()}
    return adjusted


def run_once(window_steps: int = 200) -> Dict[str, Any]:  # window_steps reserved for future use
    baseline = _baseline_snapshot()
    pf_adj = _load_accounting_bias()
    conf_bias = _confidence_bias()
    last_dir = _last_trade_dir()

    deltas: Dict[str, Dict[str, float]] = {regime: {bucket: 0.0 for bucket in BUCKETS} for regime in baseline}

    for regime in baseline:
        primary_bucket = "flow"
        if last_dir > 0:
            primary_bucket = "momentum"
        elif last_dir < 0:
            primary_bucket = "meanrev"

        if pf_adj >= 1.05:
            deltas[regime][primary_bucket] += 0.01
        elif pf_adj < 1.00:
            deltas[regime][primary_bucket] -= 0.01
            opposite = "meanrev" if primary_bucket == "momentum" else "momentum"
            deltas[regime][opposite] += 0.01

        conf_delta = conf_bias.get(regime, 0.0)
        if conf_delta:
            deltas[regime]["momentum"] += 0.5 * conf_delta
            deltas[regime]["meanrev"] -= 0.5 * conf_delta

        deltas[regime] = _apply_constraints(deltas[regime])

    proposed: Dict[str, Dict[str, float]] = {}
    for regime, base_weights in baseline.items():
        weights = {bucket: base_weights[bucket] + deltas[regime][bucket] for bucket in BUCKETS}
        weights = _normalize(weights)
        proposed[regime] = weights

    payload = {
        "ts": _now(),
        "baseline": baseline,
        "delta": deltas,
        "proposed": proposed,
    }

    WEIGHTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    WEIGHTS_OUT.write_text(json.dumps(payload, indent=2))
    with (LOG_PATH).open("a") as f:
        f.write(json.dumps(payload) + "\n")
    SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2))

    return payload
