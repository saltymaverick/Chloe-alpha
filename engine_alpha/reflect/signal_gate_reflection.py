from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from engine_alpha.core.gpt_client import query_gpt
from engine_alpha.core.paths import CONFIG, REPORTS

DEBUG_DIR = REPORTS / "debug"
RESEARCH_DIR = REPORTS / "research"

LATEST_SIGNALS_PATH = DEBUG_DIR / "latest_signals.json"
SIGNAL_HISTORY_PATH = DEBUG_DIR / "signals_history.jsonl"
WHY_BLOCKED_PATH = DEBUG_DIR / "why_blocked.jsonl"
LOOSEN_FLAGS_PATH = CONFIG / "loosen_flags.json"

REFLECTION_LOG_PATH = RESEARCH_DIR / "signal_gate_reflections.jsonl"


@dataclass
class GateStats:
    total: int = 0
    by_stage: Dict[str, int] | None = None

    def add(self, stage: str) -> None:
        if self.by_stage is None:
            self.by_stage = {}
        self.total += 1
        self.by_stage[stage] = self.by_stage.get(stage, 0) + 1


@dataclass
class AssetSignalSummary:
    symbol: str
    regimes: Dict[str, int]
    dir_counts: Dict[int, int]
    avg_conf: float
    max_conf: float
    avg_edge: float
    gate_stats: GateStats
    soft_mode: bool

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        gate_stats_obj = self.gate_stats  # Access the actual GateStats object before asdict
        data["gate_stats"] = {
            "total": gate_stats_obj.total,
            "by_stage": gate_stats_obj.by_stage or {},
        }
        return data


def _safe_load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _load_lines_json(path: Path, max_lines: int = 500) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r") as handle:
            lines = handle.readlines()[-max_lines:]
    except Exception:
        return []
    entries: List[Dict[str, Any]] = []
    for line in lines:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                entries.append(parsed)
        except Exception:
            continue
    return entries


def _compute_asset_summaries(
    signals_history: List[Dict[str, Any]],
    why_blocked: List[Dict[str, Any]],
    loosen_flags: Dict[str, Any],
    enabled_symbols: List[str],
) -> Dict[str, AssetSignalSummary]:
    history_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in signals_history:
        sym = row.get("symbol")
        if sym:
            history_map[sym].append(row)

    gate_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in why_blocked:
        sym = row.get("symbol")
        if sym:
            gate_map[sym].append(row)

    summaries: Dict[str, AssetSignalSummary] = {}
    for sym in enabled_symbols:
        hist = history_map.get(sym, [])
        gates = gate_map.get(sym, [])

        regimes: Dict[str, int] = {}
        dir_counts: Dict[int, int] = {}
        conf_sum = 0.0
        edge_sum = 0.0
        max_conf = 0.0
        sample_count = 0

        for row in hist:
            regime = row.get("regime", "unknown")
            direction = int(row.get("dir", row.get("direction", 0)) or 0)
            confidence = float(row.get("conf", row.get("confidence", 0.0)) or 0.0)
            edge_val = float(row.get("combined_edge", 0.0) or 0.0)

            regimes[regime] = regimes.get(regime, 0) + 1
            dir_counts[direction] = dir_counts.get(direction, 0) + 1
            conf_sum += confidence
            edge_sum += edge_val
            max_conf = max(max_conf, confidence)
            sample_count += 1

        avg_conf = conf_sum / sample_count if sample_count else 0.0
        avg_edge = edge_sum / sample_count if sample_count else 0.0

        gate_stats = GateStats(total=0, by_stage={})
        for entry in gates:
            stage = entry.get("gate_stage", "unknown")
            gate_stats.add(stage or "unknown")

        summaries[sym] = AssetSignalSummary(
            symbol=sym,
            regimes=regimes or {},
            dir_counts=dir_counts or {},
            avg_conf=avg_conf,
            max_conf=max_conf,
            avg_edge=avg_edge,
            gate_stats=gate_stats,
            soft_mode=bool(loosen_flags.get(sym, {}).get("soft_mode")),
        )
    return summaries


def _build_prompt(context: Dict[str, Any]) -> str:
    return (
        "You are Chloe's nightly quant reflection brain. "
        "Use the signal/gate telemetry to explain, per asset, why trades did or did not happen. "
        "Focus on direction distribution, confidence averages, gate-block counts, and soft-mode state. "
        "Clarify whether each asset is experiencing true no-edge, strict thresholds, or quant-gate blocks. "
        "Suggest advisory next steps only if justified, and never claim a change has been applied. "
        "All trading remains paper-only.\n\n"
        "IMPORTANT: Use the EXACT numeric gates defined in gate_and_size_trade() and exploration_mode config. "
        "Never invent thresholds. If exploration_mode.enabled=true, exploration_pass can bypass confidence "
        "but NOT regime or edge gates. Use only the numeric thresholds provided in the input JSON.\n\n"
        f"DATA:\n{json.dumps(context, indent=2)}"
    )


def run_signal_gate_reflection(
    enabled_symbols: List[str],
    use_gpt: bool = True,
    history_limit: int = 600,
    gate_limit: int = 600,
) -> Dict[str, Any]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    signals_history = _load_lines_json(SIGNAL_HISTORY_PATH, max_lines=history_limit)
    why_blocked = _load_lines_json(WHY_BLOCKED_PATH, max_lines=gate_limit)
    loosen_flags = _safe_load_json(LOOSEN_FLAGS_PATH, default={})

    summaries = _compute_asset_summaries(
        signals_history=signals_history,
        why_blocked=why_blocked,
        loosen_flags=loosen_flags,
        enabled_symbols=enabled_symbols,
    )
    context = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "enabled_assets": enabled_symbols,
        "asset_summaries": {sym: summary.to_dict() for sym, summary in summaries.items()},
    }

    explanation = None
    if use_gpt:
        prompt = _build_prompt(context)
        response = query_gpt(prompt, purpose="signal_gate_reflection")
        if response and response.get("text"):
            explanation = response["text"]
        else:
            explanation = "GPT unavailable; no explanation generated."
    else:
        explanation = "use_gpt=False; skipped GPT explanation."

    record = {
        "ts": context["generated_at"],
        "context": context,
        "explanation": explanation,
    }
    try:
        with REFLECTION_LOG_PATH.open("a") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:
        pass
    return record

