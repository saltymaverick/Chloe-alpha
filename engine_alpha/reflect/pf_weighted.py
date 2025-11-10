"""Risk-weighted profit factor computation for live paper execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from engine_alpha.core import position_sizing
from engine_alpha.core.paths import REPORTS

EQUITY_CURVE_LIVE = REPORTS / "equity_curve_live.jsonl"
TRADES_PATH = REPORTS / "trades.jsonl"
PF_OUT = REPORTS / "pf_local_live.json"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    try:
        for raw in path.read_text().splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if isinstance(obj, dict):
                entries.append(obj)
    except Exception:
        return []
    return entries


def _series_from_equity(curve: List[Dict[str, Any]]) -> List[float]:
    if not curve:
        return []
    returns: List[float] = []
    prev_equity = None
    for entry in curve:
        equity = entry.get("equity")
        if not isinstance(equity, (int, float)):
            continue
        if prev_equity in (None, 0):
            prev_equity = float(equity)
            continue
        delta = float(equity) - float(prev_equity)
        if prev_equity != 0:
            returns.append(delta / float(prev_equity))
        prev_equity = float(equity)
    return returns


def _series_from_trades(cfg: Dict[str, Any]) -> List[float]:
    trades = _read_jsonl(TRADES_PATH)
    if not trades:
        return []
    fraction = position_sizing.risk_fraction(cfg)
    returns: List[float] = []
    for trade in trades:
        if str(trade.get("type") or trade.get("event")) != "close":
            continue
        adj_pct = trade.get("pct")
        try:
            adj_val = float(adj_pct)
        except Exception:
            continue
        returns.append(adj_val * fraction)
    return returns


def update() -> Dict[str, Any]:
    cfg = position_sizing.load_cfg()
    curve = _read_jsonl(EQUITY_CURVE_LIVE)
    returns = _series_from_equity(curve)
    if not returns:
        returns = _series_from_trades(cfg)

    count = len(returns)
    pf = 0.0
    if returns:
        pos_sum = sum(r for r in returns if r > 0)
        neg_sum = sum(r for r in returns if r < 0)
        if neg_sum < 0:
            pf = pos_sum / abs(neg_sum)
        elif pos_sum > 0:
            pf = float("inf")
        else:
            pf = 0.0

    PF_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pf": pf, "count": count}
    try:
        PF_OUT.write_text(json.dumps(payload, indent=2))
    except Exception:
        pass
    return payload


if __name__ == "__main__":  # manual diagnostic
    print(json.dumps(update(), indent=2))
