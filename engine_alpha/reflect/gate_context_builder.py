from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _load_why_blocks(path: Path, max_lines: int) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r") as handle:
            lines = handle.readlines()
    except Exception:
        return []
    entries: List[Dict[str, Any]] = []
    for line in lines[-max_lines:]:
        try:
            record = json.loads(line)
            if isinstance(record, dict):
                entries.append(record)
        except json.JSONDecodeError:
            continue
    return entries


def build_gate_context(
    why_path: str = "reports/debug/why_blocked.jsonl",
    output_path: str = "reports/research/gate_context.json",
    lookback_bars: int = 96,
    max_lines: int = 4000,
) -> Dict[str, Any]:
    """
    Summarize gate behavior per symbol:
        - counts per gate_stage
        - average confidence/edge when gate fired
        - last_block snapshot
    """
    why_file = Path(why_path)
    output_file = Path(output_path)

    entries = _load_why_blocks(why_file, max_lines=max_lines)
    by_symbol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        sym = entry.get("symbol")
        if not sym:
            continue
        by_symbol[sym.upper()].append(entry)

    assets_summary: Dict[str, Any] = {}
    for sym, blocks in by_symbol.items():
        window = blocks[-lookback_bars:]
        if not window:
            continue
        gate_counts: Counter[str] = Counter()
        conf_acc: Dict[str, Dict[str, float]] = defaultdict(lambda: {"sum": 0.0, "count": 0})
        edge_acc: Dict[str, Dict[str, float]] = defaultdict(lambda: {"sum": 0.0, "count": 0})

        for block in window:
            stage = block.get("gate_stage", "unknown")
            gate_counts[stage] += 1
            conf = block.get("conf")
            edge = block.get("combined_edge")
            if isinstance(conf, (int, float)):
                conf_acc[stage]["sum"] += float(conf)
                conf_acc[stage]["count"] += 1
            if isinstance(edge, (int, float)):
                edge_acc[stage]["sum"] += float(edge)
                edge_acc[stage]["count"] += 1

        avg_conf_by_gate = {
            stage: acc["sum"] / acc["count"] if acc["count"] else None
            for stage, acc in conf_acc.items()
        }
        avg_edge_by_gate = {
            stage: acc["sum"] / acc["count"] if acc["count"] else None
            for stage, acc in edge_acc.items()
        }
        last_block = window[-1]
        # Only keep relevant keys for readability
        last_block_filtered = {
            key: last_block.get(key)
            for key in (
                "ts",
                "regime",
                "gate_stage",
                "reason",
                "conf",
                "combined_edge",
                "dir",
            )
        }

        assets_summary[sym] = {
            "gate_counts": dict(gate_counts),
            "avg_confidence_by_gate": avg_conf_by_gate,
            "avg_edge_by_gate": avg_edge_by_gate,
            "last_block": last_block_filtered,
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": "15m",
        "lookback_bars": lookback_bars,
        "assets": assets_summary,
    }
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(payload, indent=2))
    except Exception:
        pass
    return payload


__all__ = ["build_gate_context"]

