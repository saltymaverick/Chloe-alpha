"""
Mirror manager - Phase 8
Runs shadow sessions for top candidate wallets (paper only).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from engine_alpha.core.paths import REPORTS
from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.regime import RegimeClassifier
from engine_alpha.mirror.wallet_hunter import ensure_registry, score_wallets
from engine_alpha.mirror.strategy_inference import infer_strategy, explain_inference
from engine_alpha.reflect.trade_analysis import pf_from_trades


def _append_memory(entry: Dict[str, Any]) -> None:
    path = REPORTS / "mirror_memory.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _shadow_trade(wallet: str, entry_type: str, direction: int, pct: float, style: str) -> None:
    _append_memory(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "wallet": wallet,
            "type": entry_type,
            "dir": direction,
            "pct": float(pct),
            "style": style,
        }
    )


def _simulate_wallet(wallet: Dict[str, Any], steps: int, classifier: RegimeClassifier) -> Dict[str, Any]:
    wallet_id = wallet.get("id", "unknown")
    observations: List[Dict[str, float]] = []
    trades: List[Dict[str, float]] = []
    in_position = 0
    bars_open = 0

    for _ in range(steps):
        signal_result = get_signal_vector()
        decision = decide(signal_result["signal_vector"], signal_result["raw_registry"], classifier)
        momentum_score = decision["buckets"].get("momentum", {}).get("score", 0.0)
        vol_delta = signal_result["raw_registry"].get("Vol_Delta", {}).get("value", 0.0)

        observations.append(
            {
                "momentum": momentum_score,
                "reversion": -momentum_score,
                "flow": vol_delta,
            }
        )

    inference = infer_strategy(observations)
    style = inference.get("style", "momentum")

    # Reset to run simulation with style
    in_position = 0
    bars_open = 0

    for obs in observations:
        momentum_score = obs["momentum"]
        flow_score = obs["flow"]
        direction = 0

        if style == "momentum":
            direction = 1 if momentum_score >= 0 else -1
        elif style == "meanrev":
            direction = -1 if abs(momentum_score) > 0 else 0
        elif style == "flow":
            direction = 1 if flow_score >= 0 else -1

        conf = abs(momentum_score)

        if in_position == 0 and direction != 0 and conf >= 0.1:
            in_position = direction
            bars_open = 0
            _shadow_trade(wallet_id, "open", in_position, 0.0, style)
        elif in_position != 0:
            pnl = in_position * momentum_score * 0.01
            trades.append({"pct": pnl})
            bars_open += 1
            if conf < 0.05 or abs(momentum_score) < 0.01 or bars_open > 12:
                _shadow_trade(wallet_id, "close", in_position, pnl, style)
                in_position = 0
                bars_open = 0

    return {
        "wallet": wallet_id,
        "style": style,
        "explain": explain_inference(inference),
        "trades": trades,
    }


def run_shadow(K: int = 2, steps: int = 60) -> Dict[str, Any]:
    registry = ensure_registry()
    ranked = score_wallets(registry)
    classifier = RegimeClassifier()

    selected = ranked[:K]
    results: Dict[str, Any] = {}

    for wallet in selected:
        report = _simulate_wallet(wallet, steps, classifier)
        trades = report["trades"]
        pf = pf_from_trades(trades)
        results[wallet["id"]] = {
            "style": report["style"],
            "explain": report["explain"],
            "pf": pf,
            "trades": len(trades),
        }

    snapshot = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "shadow_pnl": {wid: data["pf"] for wid, data in results.items()},
        "inferences": {wid: data["explain"] for wid, data in results.items()},
    }

    snapshot_path = REPORTS / "mirror_snapshot.json"
    with snapshot_path.open("w") as f:
        json.dump(snapshot, f, indent=2)

    return snapshot
