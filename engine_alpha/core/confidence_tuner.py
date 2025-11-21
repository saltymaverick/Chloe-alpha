"""
Confidence tuner - Phase 15
Derives adjusted entry gates from reflection signals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml

from engine_alpha.core.paths import REPORTS, CONFIG

MIN_GATE = 0.40
MAX_GATE = 0.80
MAX_DELTA = 0.10
BIAS_COEFF = 0.2


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    data: List[Dict[str, Any]] = []
    if not path.exists():
        return data
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except Exception:
                continue
    return data


def _load_gates() -> Dict[str, float]:
    cfg_path = CONFIG / "gates.yaml"
    try:
        data = yaml.safe_load(cfg_path.read_text()) or {}
        entry = data.get("entry_exit", {}).get("entry_min_conf", {})
        return {
            "trend": float(entry.get("trend", 0.70)),
            "chop": float(entry.get("chop", 0.72)),
            "high_vol": float(entry.get("high_vol", 0.71)),
        }
    except Exception:
        return {"trend": 0.70, "chop": 0.72, "high_vol": 0.71}


def _load_biases() -> Dict[str, List[float]]:
    dream_log = _read_jsonl(REPORTS / "dream_log.jsonl")
    bias_map: Dict[str, List[float]] = {"trend": [], "chop": [], "high_vol": []}
    for entry in dream_log:
        regime = entry.get("regime")
        reason = entry.get("reason_score") or entry.get("reason", {})
        confidence = entry.get("final_conf") or entry.get("confidence")
        if regime not in bias_map:
            continue
        try:
            bias = float(reason) - float(confidence)
            bias_map[regime].append(bias)
        except Exception:
            continue
    return bias_map


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def run_once() -> List[Dict[str, Any]]:
    baseline = _load_gates()
    bias_map = _load_biases()
    reason_scores = _read_json(REPORTS / "reason_score.json")
    for regime, val in reason_scores.items():
        if regime in bias_map:
            try:
                bias_map[regime].append(float(val) - baseline.get(regime, 0.6))
            except Exception:
                continue

    entries: List[Dict[str, Any]] = []
    calibrated = {"entry_exit": {"entry_min_conf": {}}}

    for regime, base in baseline.items():
        bias = _mean(bias_map.get(regime, []))
        delta = max(-MAX_DELTA, min(MAX_DELTA, bias * BIAS_COEFF))
        new_gate = max(MIN_GATE, min(MAX_GATE, base + delta))
        entry = {
            "ts": _iso_now(),
            "regime": regime,
            "baseline": base,
            "delta": delta,
            "new_gate": new_gate,
        }
        entries.append(entry)
        calibrated["entry_exit"]["entry_min_conf"][regime] = new_gate

    log_path = REPORTS / "confidence_tune.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    tuned_cfg = CONFIG / "gates_calibrated.yaml"
    with tuned_cfg.open("w") as f:
        yaml.safe_dump(calibrated, f)

    return entries
