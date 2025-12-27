"""
Regime drift monitor for Chloe's research outputs.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
HISTORY_DIR = RESEARCH_DIR / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        if not data:
            return {}
        return json.loads(data)
    except Exception:
        return {}


def _aggregate_regime_edges(stats: dict) -> Dict[str, float]:
    result: Dict[str, float] = {}
    ret1h = stats.get("ret_1h", {})
    buckets = ret1h.get("stats", {})
    accum: Dict[str, Tuple[float, float]] = {}
    for key, entry in buckets.items():
        if "|" not in key:
            continue
        regime, _bucket = key.split("|", 1)
        mean = entry.get("mean")
        weight = entry.get("weighted_count") or entry.get("count") or 0.0
        if mean is None or weight is None:
            continue
        try:
            if isinstance(mean, float) and math.isnan(mean):
                continue
            if isinstance(weight, float) and math.isnan(weight):
                continue
        except Exception:
            continue
        if weight <= 0:
            continue
        total_weight, total_value = accum.get(regime, (0.0, 0.0))
        accum[regime] = (total_weight + weight, total_value + weight * mean)
    for regime, (total_weight, total_value) in accum.items():
        if total_weight > 0:
            result[regime] = total_value / total_weight
    return result


def _drift_state(delta: float) -> str:
    if delta is None:
        return "unknown"
    if delta > 0.001:
        return "strengthening"
    if delta < -0.001:
        return "weakening"
    return "stable"


def build_regime_drift_report(
    stats_root: Path = RESEARCH_DIR,
    history_root: Path = HISTORY_DIR,
    output_path: Path = RESEARCH_DIR / "regime_drift_report.json",
) -> Path:
    """
    Build a regime drift report comparing current stats vs previous snapshot.
    """
    symbols_dir = [p for p in stats_root.iterdir() if p.is_dir()]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": {},
    }

    for symbol_dir in symbols_dir:
        symbol = symbol_dir.name.upper()
        current_stats = _load_json(symbol_dir / "multi_horizon_stats.json")
        if not current_stats:
            continue
        current_edges = _aggregate_regime_edges(current_stats)
        history_path = history_root / f"{symbol}_regime_edges.json"
        previous_edges = _load_json(history_path)
        symbol_entry = {}
        for regime, current_edge in current_edges.items():
            prev_edge = previous_edges.get(regime) if isinstance(previous_edges, dict) else None
            delta = current_edge - prev_edge if prev_edge is not None else None
            symbol_entry[regime] = {
                "current_edge": current_edge,
                "previous_edge": prev_edge,
                "delta": delta,
                "state": _drift_state(delta),
            }
        report["symbols"][symbol] = symbol_entry
        # Persist current edges for next comparison
        history_path.write_text(
            json.dumps(
                {
                    regime: value
                    for regime, value in current_edges.items()
                    if isinstance(value, (int, float)) and not math.isnan(value)
                },
                indent=2,
            )
        )

    output_path.write_text(json.dumps(report, indent=2))
    return output_path

