"""
Backtest replay - Phase 23 (paper only)
Feeds historical bars through signal/confidence decision logic.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List

from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.regime import RegimeClassifier
from engine_alpha.reflect.trade_analysis import adjust_pct, _load_accounting


def replay(symbol: str, timeframe: str, rows: List[Dict[str, Any]], seed: int = 42) -> Dict[str, Any]:
    """Run paper replay for provided OHLCV rows."""
    random.seed(seed)
    classifier = RegimeClassifier()
    accounting = _load_accounting()

    trades: List[Dict[str, Any]] = []
    state = {"dir": 0, "bars_open": 0}

    for row in rows:
        ctx = {
            "symbol": symbol,
            "timeframe": timeframe,
            "now": row.get("ts"),
            "mode": "backtest",
        }
        _ = ctx  # reserved for future use
        out = get_signal_vector()
        decision = decide(out["signal_vector"], out["raw_registry"], classifier)
        final = decision["final"]
        gates = decision["gates"]

        if state["dir"] == 0:
            if final["dir"] != 0 and final["conf"] >= gates["entry_min_conf"]:
                state.update({"dir": final["dir"], "bars_open": 0})
                trades.append(
                    {
                        "ts": row.get("ts"),
                        "type": "open",
                        "dir": final["dir"],
                        "symbol": symbol,
                        "timeframe": timeframe,
                    }
                )
        else:
            state["bars_open"] += 1
            flip = final["dir"] != 0 and final["dir"] != state["dir"] and final["conf"] >= gates["reverse_min_conf"]
            drop = final["conf"] < gates["exit_min_conf"]
            decay = state["bars_open"] > 12
            if drop or flip or decay:
                base_pct = final["conf"] if final["dir"] == state["dir"] else -final["conf"]
                close_trade = {
                    "ts": row.get("ts"),
                    "type": "close",
                    "dir": state["dir"],
                    "pct": base_pct,
                    "symbol": symbol,
                    "timeframe": timeframe,
                }
                close_trade["adj_pct"] = adjust_pct(close_trade, accounting)
                trades.append(close_trade)
                state.update({"dir": 0, "bars_open": 0})
                if flip:
                    state.update({"dir": final["dir"], "bars_open": 0})
                    trades.append(
                        {
                            "ts": row.get("ts"),
                            "type": "open",
                            "dir": final["dir"],
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "reason": "flip",
                        }
                    )

    return {"trades": trades, "bars": len(rows)}
