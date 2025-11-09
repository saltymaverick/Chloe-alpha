#!/usr/bin/env python3
"""
Diagnostic live loop - Phase 24
Runs a read-only step using live OHLCV-backed signals.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict

from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.paths import REPORTS
from engine_alpha.signals.signal_processor import get_signal_vector_live

SYMBOL = "ETHUSDT"
TIMEFRAME = "1h"


def _load_policy() -> Dict[str, Any]:
    snapshot_path = REPORTS / "orchestrator_snapshot.json"
    if not snapshot_path.exists():
        return {"policy": {"allow_opens": True}, "inputs": {}}
    try:
        with snapshot_path.open("r") as f:
            return json.load(f)
    except Exception:
        return {"policy": {"allow_opens": True}, "inputs": {}}


def main() -> int:
    try:
        signals = get_signal_vector_live(SYMBOL, TIMEFRAME)
    except Exception as exc:  # pragma: no cover - network errors
        print(f"LIVE: fetch_failed error={exc}")
        return 1

    if not signals.get("signal_vector"):
        print("LIVE: no signals generated (empty vector)")
        return 1

    decision = decide(signals["signal_vector"], signals["raw_registry"])
    final = decision.get("final", {})
    policy_blob = _load_policy()
    policy = policy_blob.get("policy", {})
    inputs = policy_blob.get("inputs", {})

    allow_opens = policy.get("allow_opens", True)
    risk_band = inputs.get("risk_band", "N/A")

    ts = signals.get("ts", "N/A")
    dir_val = final.get("dir", 0)
    try:
        conf_val = float(final.get("conf", 0.0))
    except (TypeError, ValueError):
        conf_val = 0.0

    print(
        f"LIVE: ts={ts} final.dir={dir_val} conf={conf_val:.4f} "
        f"allow_opens={allow_opens} risk_band={risk_band}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

