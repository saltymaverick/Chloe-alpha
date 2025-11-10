#!/usr/bin/env python3
"""
Dream Mode Diagnostic - Phase 6
Runs counterfactual replay and summarizes proposals.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.dream_mode import run_dream


def _safe_float(value, default="N/A"):
    try:
        return f"{float(value):.4f}"
    except Exception:
        return default


def main():
    result = run_dream()

    snapshot = result.get("snapshot", {})
    summary = result.get("summary", {})

    snapshot_path = REPORTS / "dream_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2))

    print("Dream mode run complete")
    print(f" Dream log: {REPORTS / 'dream_log.jsonl'}")
    print(f" Proposal file: {REPORTS / 'dream_proposals.json'}")
    print(f" Snapshot: {snapshot_path}")

    # Four-line summary output (fail-soft)
    ts = summary.get("ts") or snapshot.get("ts") or "N/A"
    governance = summary.get("governance") or {}
    rec = governance.get("rec", "N/A")
    sci = governance.get("sci")
    sci_display = _safe_float(sci) if sci is not None else "N/A"

    pf_trend = summary.get("pf_adj_trend") or {}
    slope50 = _safe_float(pf_trend.get("slope_50"))
    slope10 = _safe_float(pf_trend.get("slope_10"))

    trades = summary.get("trades") or {}
    wins = trades.get("wins", "N/A")
    losses = trades.get("losses", "N/A")

    proposal_kind = summary.get("proposal_kind", snapshot.get("proposal_kind", "N/A"))

    print(
        f"Dream ts={ts} rec={rec} sci={sci_display} slope50={slope50} slope10={slope10} "
        f"closes={wins}/{losses} proposal={proposal_kind}"
    )


if __name__ == "__main__":
    main()
