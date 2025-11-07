"""
Portfolio orchestrator - Phase 9 (Paper only)
Coordinates multi-asset shadow trading with correlation guard.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

import yaml

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.regime import RegimeClassifier
from engine_alpha.reflect.trade_analysis import pf_from_trades


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _portfolio_dir() -> Path:
    directory = REPORTS / "portfolio"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _trade_path(symbol: str) -> Path:
    return _portfolio_dir() / f"{symbol}_trades.jsonl"


def _log_trade(symbol: str, event: Dict[str, Any]) -> None:
    path = _trade_path(symbol)
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")


def _load_assets() -> Dict[str, Any]:
    with (CONFIG / "asset_list.yaml").open("r") as f:
        return yaml.safe_load(f)


def _correlation(symbol: str, other: str, corr_map: Dict[str, Any]) -> float:
    return float(corr_map.get(symbol, {}).get(other, 0.0))


def _maybe_close(symbol: str, state: Dict[str, Any], conf: float, trades: List[Dict[str, float]]) -> bool:
    pnl = state["dir"] * conf * 0.01
    trades.append({"pct": pnl})
    _log_trade(
        symbol,
        {
            "ts": _now(),
            "event": "CLOSE",
            "symbol": symbol,
            "dir": state["dir"],
            "conf": conf,
            "bars_open": state["bars_open"],
            "pct": pnl,
        },
    )
    state["dir"] = 0
    state["bars_open"] = 0
    return True


def run_portfolio(steps: int = 60) -> Dict[str, Any]:
    assets = _load_assets()
    symbols = assets.get("symbols", [])
    corr_map = assets.get("correlation", {})
    threshold = float(assets.get("correlation_threshold", 0.75))

    classifier = RegimeClassifier()

    states = {s: {"dir": 0, "bars_open": 0} for s in symbols}
    trades_per_symbol: Dict[str, List[Dict[str, float]]] = {s: [] for s in symbols}
    opens = {s: 0 for s in symbols}
    closes = {s: 0 for s in symbols}
    corr_blocks = 0

    for _ in range(steps):
        for symbol in symbols:
            result = get_signal_vector()
            result["raw_registry"]["symbol"] = symbol
            decision = decide(result["signal_vector"], result["raw_registry"], classifier)
            gates = decision["gates"]
            dir_ = decision["final"]["dir"]
            conf = decision["final"]["conf"]
            state = states[symbol]

            if state["dir"] == 0:
                if dir_ != 0 and conf >= gates["entry_min_conf"]:
                    blocked = False
                    for other_symbol, other_state in states.items():
                        if other_symbol == symbol:
                            continue
                        if other_state["dir"] == dir_ and _correlation(symbol, other_symbol, corr_map) >= threshold:
                            blocked = True
                            corr_blocks += 1
                            break
                    if blocked:
                        continue
                    state["dir"] = dir_
                    state["bars_open"] = 0
                    opens[symbol] += 1
                    _log_trade(
                        symbol,
                        {
                            "ts": _now(),
                            "event": "OPEN",
                            "symbol": symbol,
                            "dir": dir_,
                            "conf": conf,
                        },
                    )
            else:
                state["bars_open"] += 1
                exit_due_conf = conf < gates["exit_min_conf"]
                exit_due_time = state["bars_open"] > 12
                flip_possible = dir_ != 0 and dir_ != state["dir"] and conf >= gates["reverse_min_conf"]

                if exit_due_conf or exit_due_time or flip_possible:
                    closes[symbol] += 1
                    _maybe_close(symbol, state, conf, trades_per_symbol[symbol])
                    if flip_possible:
                        blocked = False
                        for other_symbol, other_state in states.items():
                            if other_symbol == symbol:
                                continue
                            if other_state["dir"] == dir_ and _correlation(symbol, other_symbol, corr_map) >= threshold:
                                blocked = True
                                corr_blocks += 1
                                break
                        if not blocked:
                            state["dir"] = dir_
                            state["bars_open"] = 0
                            opens[symbol] += 1
                            _log_trade(
                                symbol,
                                {
                                    "ts": _now(),
                                    "event": "OPEN",
                                    "symbol": symbol,
                                    "dir": dir_,
                                    "conf": conf,
                                    "reason": "flip",
                                },
                            )

    summary = {}
    all_trades: List[Dict[str, float]] = []
    for symbol in symbols:
        pf = pf_from_trades(trades_per_symbol[symbol])
        summary[symbol] = {"pf": pf, "opens": opens[symbol], "closes": closes[symbol]}
        path = _portfolio_dir() / f"{symbol}_pf.json"
        with path.open("w") as f:
            json.dump({"symbol": symbol, "pf": pf}, f, indent=2)
        all_trades.extend(trades_per_symbol[symbol])

    portfolio_pf = pf_from_trades(all_trades)
    with (_portfolio_dir() / "portfolio_pf.json").open("w") as f:
        json.dump({"portfolio_pf": portfolio_pf}, f, indent=2)

    with (_portfolio_dir() / "portfolio_health.json").open("w") as f:
        json.dump(
            {
                "ts": _now(),
                "portfolio_pf": portfolio_pf,
                "open_positions": {s: states[s]["dir"] for s in symbols},
                "correlation_blocks": corr_blocks,
            },
            f,
            indent=2,
        )

    return {"symbols": symbols, "summary": summary, "portfolio_pf": portfolio_pf}
