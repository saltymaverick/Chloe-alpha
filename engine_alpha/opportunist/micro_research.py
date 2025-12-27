from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.live_prices import get_live_ohlcv

OPPORTUNIST_DIR = REPORTS / "opportunist"
OPPORTUNIST_DIR.mkdir(parents=True, exist_ok=True)
CANDIDATES_PATH = OPPORTUNIST_DIR / "opportunist_candidates.json"


@dataclass
class MicroResearchResult:
    symbol: str
    direction: str
    expected_edge: float
    momentum_slope: float
    atr_rel: float


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


def _linear_slope(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _atr_rel(rows: List[Dict[str, float]], period: int = 14) -> float:
    if len(rows) < period + 1:
        return 0.0
    tr_values: List[float] = []
    prev_close = rows[-period - 1]["close"]
    for r in rows[-period:]:
        high = r["high"]
        low = r["low"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)
        prev_close = r["close"]
    atr = sum(tr_values) / len(tr_values) if tr_values else 0.0
    last_close = rows[-1]["close"]
    if last_close <= 0:
        return 0.0
    return atr / last_close


def _expected_edge(closes: List[float], window: int = 60) -> float:
    if len(closes) < window + 2:
        return 0.0
    returns: List[float] = []
    for i in range(len(closes) - 1):
        prev_close = closes[i]
        if prev_close == 0:
            continue
        returns.append((closes[i + 1] - prev_close) / prev_close)
    if not returns:
        return 0.0
    subset = returns[-window:]
    if not subset:
        return 0.0
    return sum(subset) / len(subset)


def run_micro_research(timeframe: str = "15m", limit: int = 220) -> Dict[str, object]:
    if not CANDIDATES_PATH.exists():
        payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "results": []}
        out_path = OPPORTUNIST_DIR / "micro_research.json"
        out_path.write_text(json.dumps(payload, indent=2))
        return payload

    candidates_doc = json.loads(CANDIDATES_PATH.read_text())
    symbols = [row["symbol"] for row in candidates_doc.get("candidates", []) if row.get("symbol")]

    results: List[MicroResearchResult] = []
    for symbol in symbols:
        rows = get_live_ohlcv(symbol, timeframe, limit=limit, no_cache=True)
        numeric_rows = _rows_to_numeric(rows)
        if len(numeric_rows) < 60:
            continue
        closes = [r["close"] for r in numeric_rows]
        focus_window = closes[-100:] if len(closes) >= 100 else closes
        slope = _linear_slope(focus_window)
        normalized_slope = slope / focus_window[-1] if focus_window[-1] != 0 else 0.0
        atr_rel = _atr_rel(numeric_rows)
        edge = _expected_edge(closes, window=60)
        if normalized_slope > 0 and edge > 0:
            direction = "long"
        elif normalized_slope < 0 and edge < 0:
            direction = "short"
        else:
            direction = "none"
        results.append(
            MicroResearchResult(
                symbol=symbol,
                direction=direction,
                expected_edge=edge,
                momentum_slope=normalized_slope,
                atr_rel=atr_rel,
            )
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "results": [asdict(r) for r in results],
    }
    out_path = OPPORTUNIST_DIR / "micro_research.json"
    out_path.write_text(json.dumps(payload, indent=2))
    return payload


__all__ = ["MicroResearchResult", "run_micro_research"]

