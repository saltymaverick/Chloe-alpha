from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.live_prices import get_live_ohlcv

OPPORTUNIST_DIR = REPORTS / "opportunist"
OPPORTUNIST_DIR.mkdir(parents=True, exist_ok=True)
MICRO_RESEARCH_PATH = OPPORTUNIST_DIR / "micro_research.json"
OPPORTUNIST_TRADES_PATH = OPPORTUNIST_DIR / "opportunist_trades.jsonl"
MAIN_TRADES_PATH = REPORTS / "trades.jsonl"

BASE_NOTIONAL_USD = 1_000.0
SIZE_FACTOR = 0.10
MAX_TRADES_PER_RUN = 3
TP_PCT = 0.01
SL_PCT = -0.0075


def _rows_to_numeric(rows: List[Dict[str, float]]) -> List[Dict[str, float]]:
    numeric_rows: List[Dict[str, float]] = []
    for r in rows:
        try:
            numeric_rows.append(
                {
                    "ts": r["ts"],
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r.get("volume", 0.0)),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return numeric_rows


def _load_micro_research() -> List[Dict[str, object]]:
    if not MICRO_RESEARCH_PATH.exists():
        return []
    try:
        payload = json.loads(MICRO_RESEARCH_PATH.read_text())
    except json.JSONDecodeError:
        return []
    return payload.get("results", [])


def _simulate_trade(symbol: str, direction: str, timeframe: str) -> Dict[str, object] | None:
    rows = get_live_ohlcv(symbol, timeframe, limit=3, no_cache=True)
    numeric_rows = _rows_to_numeric(rows)
    if len(numeric_rows) < 2:
        return None
    entry_row = numeric_rows[-2]
    exit_row = numeric_rows[-1]
    entry_px = entry_row["close"]
    exit_px = exit_row["close"]
    if entry_px <= 0 or exit_px <= 0:
        return None
    raw_ret = (exit_px - entry_px) / entry_px
    pct_ret = raw_ret if direction == "long" else -raw_ret
    pct_ret = max(SL_PCT, min(TP_PCT, pct_ret))

    base_notional = BASE_NOTIONAL_USD * SIZE_FACTOR
    qty = base_notional / entry_px

    trade = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "strategy": "opportunist",
        "direction": direction,
        "entry_ts": entry_row["ts"],
        "exit_ts": exit_row["ts"],
        "entry_px": entry_px,
        "exit_px": exit_px,
        "ret": pct_ret,
        "size_notional": base_notional,
        "size_qty": qty,
        "tp_pct": TP_PCT,
        "sl_pct": SL_PCT,
    }
    return trade


def _append_jsonl(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def run_opportunist_trader(timeframe: str = "15m") -> Dict[str, object]:
    research_results = _load_micro_research()
    if not research_results:
        payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "trades": []}
        return payload

    sorted_results = sorted(
        research_results,
        key=lambda r: abs(r.get("expected_edge", 0.0)),
        reverse=True,
    )

    trades: List[Dict[str, object]] = []
    for result in sorted_results[:MAX_TRADES_PER_RUN]:
        direction = result.get("direction")
        symbol = result.get("symbol")
        if direction not in ("long", "short") or not symbol:
            continue
        trade = _simulate_trade(symbol, direction, timeframe=timeframe)
        if not trade:
            continue
        trade.update(
            {
                "expected_edge": result.get("expected_edge", 0.0),
                "momentum_slope": result.get("momentum_slope", 0.0),
                "atr_rel": result.get("atr_rel", 0.0),
            }
        )
        trades.append(trade)

    if trades:
        _append_jsonl(OPPORTUNIST_TRADES_PATH, trades)
        agg_events = []
        for trade in trades:
            agg_events.append(
                {
                    "ts": trade["ts"],
                    "type": "close",
                    "symbol": trade["symbol"],
                    "strategy": "opportunist",
                    "pct": trade["ret"],
                    "entry_px": trade["entry_px"],
                    "exit_px": trade["exit_px"],
                    "regime": "opportunist",
                    "risk_band": "OPP",
                    "risk_mult": SIZE_FACTOR,
                }
            )
        _append_jsonl(MAIN_TRADES_PATH, agg_events)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trades": trades,
    }


__all__ = ["run_opportunist_trader"]

