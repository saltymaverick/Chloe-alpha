#!/usr/bin/env python3
"""Diagnostic runner for mirror → evolver promotion pipeline (Phase 34)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from engine_alpha.core.paths import REPORTS
from engine_alpha.mirror import mirror_manager
from engine_alpha.evolve import promotion_manager


def _count_candidates(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
        if isinstance(data, list):
            return len(data)
    except Exception:
        pass
    return 0


def _count_recent_proposals(path: Path) -> Dict[str, int]:
    counts = {"total": 0, "promote": 0, "hold": 0}
    if not path.exists():
        return counts
    try:
        for raw in path.read_text().splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except Exception:
                continue
            if not isinstance(entry, dict):
                continue
            counts["total"] += 1
            rec = entry.get("recommendation")
            if rec == "PROMOTE":
                counts["promote"] += 1
            elif rec == "HOLD":
                counts["hold"] += 1
    except Exception:
        return counts
    return counts


def main() -> int:
    mirror_result = mirror_manager.run_once()
    promotion_result = promotion_manager.run_once()

    candidates_count = _count_candidates(REPORTS / "mirror_candidates.json")
    proposal_counts = _count_recent_proposals(REPORTS / "promotion_proposals.jsonl")

    summary = {
        "candidates": mirror_result.get("count", candidates_count),
        "proposals": promotion_result.get("generated", proposal_counts["total"]),
        "promote": promotion_result.get("promote", proposal_counts["promote"]),
        "hold": promotion_result.get("hold", proposal_counts["hold"]),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
