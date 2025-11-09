"""
Backtest replay - Phase 23 (paper only)
Feeds historical bars through signal/confidence decision logic.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.regime import RegimeClassifier
from engine_alpha.reflect.trade_analysis import adjust_pct, _load_accounting


def replay(
    symbol: str,
    timeframe: str,
    rows: List[Dict[str, Any]],
    cfg: Optional[Dict[str, Any]] = None,
    seed: int = 42,
) -> Dict[str, Any]:
    """Run paper replay for provided OHLCV rows."""
    random.seed(seed)
    cfg = cfg or {}
    classifier = RegimeClassifier()
    accounting = _load_accounting()
    pct_per_conf = float(cfg.get("pct_per_conf", 0.02))
    max_trade_pct = float(cfg.get("max_trade_pct", 0.05))

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
                reason = "FLIP" if flip else ("TIMEOUT" if decay else "LOW_CONF")
                same_dir = final["dir"] == state["dir"] and not flip
                direction_sign = 1.0 if same_dir else -1.0
                base_pct = float(final["conf"]) * pct_per_conf * direction_sign
                temp_trade = {
                    "ts": row.get("ts"),
                    "type": "close",
                    "dir": state["dir"],
                    "pct": base_pct,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "reason": reason,
                }
                adj_pct = adjust_pct(temp_trade, accounting)
                adj_pct = max(-max_trade_pct, min(max_trade_pct, adj_pct))
                close_trade = {
                    **temp_trade,
                    "pct": adj_pct,
                    "adj_pct": adj_pct,
                }
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
