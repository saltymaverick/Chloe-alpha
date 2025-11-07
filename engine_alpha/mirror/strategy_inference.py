"""
Strategy inference - Phase 8
Stubbed logic to infer style from observed sequences.
"""

from __future__ import annotations

from typing import List, Dict


def infer_strategy(observed: List[Dict[str, float]]) -> Dict[str, str]:
    if not observed:
        return {"style": "momentum", "notes": "insufficient data; default momentum"}

    momentum_bias = sum(o.get("momentum", 0.0) for o in observed)
    meanrev_bias = sum(o.get("reversion", 0.0) for o in observed)
    flow_bias = sum(o.get("flow", 0.0) for o in observed)

    if momentum_bias >= max(meanrev_bias, flow_bias):
        return {"style": "momentum", "notes": "signals trend-following skew"}
    if meanrev_bias >= max(momentum_bias, flow_bias):
        return {"style": "meanrev", "notes": "signals mean-reversion skew"}
    return {"style": "flow", "notes": "volume/flow skew"}


def explain_inference(inf: Dict[str, str]) -> str:
    return f"Style={inf.get('style', 'unknown')} ({inf.get('notes', 'n/a')})"
