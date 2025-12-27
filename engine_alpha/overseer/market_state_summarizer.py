from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.overseer.staleness_analyst import load_symbols

SUMMARY_PATH = REPORTS / "research" / "market_state_summary.json"
STALENESS_PATH = REPORTS / "research" / "staleness_overseer.json"


@dataclass
class MarketState:
    symbol: str
    regime: str
    slope_5: Optional[float]
    slope_20: Optional[float]
    atr_rel: Optional[float]
    feed_state: str
    expected_trade_frequency: str
    comment: str


def _safe_load(path: Path) -> Dict:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def _pct_change(values: List[float], window: int) -> Optional[float]:
    if len(values) < window + 1:
        return None
    prev = values[-window - 1]
    last = values[-1]
    if prev == 0:
        return None
    return (last - prev) / prev


def _compute_atr(rows: List[Dict[str, float]], period: int = 14) -> Optional[float]:
    if len(rows) < period + 1:
        return None
    trs: List[float] = []
    prev_close = rows[-period - 1]["close"]
    for r in rows[-period:]:
        high = r["high"]
        low = r["low"]
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        trs.append(tr)
        prev_close = r["close"]
    if not trs:
        return None
    return sum(trs) / len(trs)


def _classify_regime(slope5: Optional[float], slope20: Optional[float], atr_rel: Optional[float]) -> str:
    if atr_rel is not None and atr_rel >= 0.025:
        return "high_vol"
    if slope5 is None or slope20 is None:
        return "unknown"
    if slope5 > 0.002 and slope20 > 0.001:
        return "trend_up"
    if slope5 < -0.002 and slope20 < -0.001:
        return "trend_down"
    return "chop"


def _expected_frequency(regime: str, feed_state: str) -> str:
    if feed_state in ("stale", "unavailable"):
        return "blocked"
    if regime == "high_vol":
        return "high"
    if regime in ("trend_up", "trend_down"):
        return "normal"
    if regime == "chop":
        return "low"
    return "unknown"


def summarize_market_state(
    symbols: Optional[List[str]] = None,
    timeframe: str = "15m",
    limit: int = 150,
) -> Dict[str, Dict]:
    now = datetime.now(timezone.utc)
    symbols = symbols or load_symbols()
    staleness_assets = _safe_load(STALENESS_PATH).get("assets", {})

    summary: Dict[str, Dict] = {}
    for symbol in symbols:
        rows = get_live_ohlcv(symbol, timeframe, limit=limit, no_cache=True)
        feed_state = staleness_assets.get(symbol, {}).get("feed_state", "unknown")
        if not rows:
            summary[symbol] = asdict(
                MarketState(
                    symbol=symbol,
                    regime="unknown",
                    slope_5=None,
                    slope_20=None,
                    atr_rel=None,
                    feed_state=feed_state,
                    expected_trade_frequency=_expected_frequency("unknown", feed_state),
                    comment="No fresh OHLCV data available.",
                )
            )
            continue

        closes = [r["close"] for r in rows if "close" in r]
        slope5 = _pct_change(closes, 5)
        slope20 = _pct_change(closes, 20)
        atr = _compute_atr(rows, period=14)
        last_close = closes[-1] if closes else None
        atr_rel = (atr / last_close) if (atr is not None and last_close) else None

        regime = _classify_regime(slope5, slope20, atr_rel)
        freq = _expected_frequency(regime, feed_state)

        comment_parts = []
        if regime == "chop":
            comment_parts.append("Price action is choppy; low trade expectation is normal.")
        elif regime == "trend_up":
            comment_parts.append("Uptrend detected; observation trades may trigger.")
        elif regime == "trend_down":
            comment_parts.append("Downtrend detected; watch for short setups.")
        elif regime == "high_vol":
            comment_parts.append("Volatility is hot; expect opportunistic entries if other gates allow.")
        else:
            comment_parts.append("Regime unclear; monitor feeds and signals.")
        if feed_state in ("stale", "unavailable"):
            comment_parts.append("Feed unhealthy; no trades should occur until fixed.")

        summary[symbol] = asdict(
            MarketState(
                symbol=symbol,
                regime=regime,
                slope_5=slope5,
                slope_20=slope20,
                atr_rel=atr_rel,
                feed_state=feed_state,
                expected_trade_frequency=freq,
                comment=" ".join(comment_parts),
            )
        )

    payload = {
        "generated_at": now.isoformat(),
        "timeframe": timeframe,
        "assets": summary,
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2))
    return payload


__all__ = ["summarize_market_state", "SUMMARY_PATH"]

