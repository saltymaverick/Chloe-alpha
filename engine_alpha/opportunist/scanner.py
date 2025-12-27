from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from engine_alpha.core.paths import REPORTS
from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.opportunist.universe_manager import (
    get_active_universe,
    update_universe_stats,
)

BYBIT_BASE_URL = "https://api.bybit.com"
OPPORTUNIST_DIR = REPORTS / "opportunist"
OPPORTUNIST_DIR.mkdir(parents=True, exist_ok=True)

EXCLUDED_SUBSTRINGS = ("UPUSDT", "DOWNUSDT", "BEARUSDT", "BULLUSDT", "3LUSDT", "3SUSDT")

_logger = logging.getLogger("opportunist.scanner")


@dataclass
class Candidate:
    symbol: str
    pct_change_15m: float
    pct_change_1h: float
    atr_rel: float
    liquidity_usd: float
    volume_ratio: float
    impulse_score: float


def fetch_bybit_spot_usdt_symbols(timeout: int = 10) -> List[str]:
    """
    Return all Bybit spot symbols quoted in USDT. Raises if the exchange cannot be
    reached so that the caller can fall back to the dynamic universe state.
    """
    url = f"{BYBIT_BASE_URL}/v5/market/instruments-info"
    params = {"category": "spot"}
    headers = {"User-Agent": "AlphaChloe-Opportunist/1.0"}
    try:
        resp = requests.get(url, params=params, timeout=timeout, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        _logger.warning(
            "Opportunist scanner unable to reach Bybit instruments endpoint (%s).",
            exc,
        )
        raise

    rows = payload.get("result", {}).get("list", []) or []
    symbols: List[str] = []
    for row in rows:
        symbol = row.get("symbol")
        quote = row.get("quoteCoin")
        if not symbol or quote != "USDT":
            continue
        if any(token in symbol for token in EXCLUDED_SUBSTRINGS):
            continue
        symbols.append(symbol.upper())
    final = sorted(set(symbols))
    if not final:
        raise ValueError("Bybit instruments endpoint returned no eligible USDT symbols.")
    return final


def _safe_pct_change(new_val: float, old_val: float) -> float:
    if old_val == 0:
        return 0.0
    return (new_val - old_val) / old_val


def _compute_volume_ratio(volumes: List[float]) -> float:
    if len(volumes) < 5:
        return 0.0
    latest = volumes[-1]
    prior = volumes[-5:-1]
    avg_prior = sum(prior) / len(prior) if prior else 0.0
    if avg_prior == 0:
        return 0.0
    return latest / avg_prior


def _compute_atr_rel(rows: List[Dict[str, float]], period: int = 5) -> float:
    if len(rows) < period + 1:
        return 0.0
    true_ranges: List[float] = []
    prev_close = rows[-period - 1]["close"]
    for r in rows[-period:]:
        high = r["high"]
        low = r["low"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
        prev_close = r["close"]
    atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0.0
    last_close = rows[-1]["close"]
    if last_close <= 0:
        return 0.0
    return atr / last_close


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


def _compute_candidate(symbol: str, timeframe: str, limit: int) -> Optional[Candidate]:
    rows = get_live_ohlcv(symbol, timeframe, limit=limit, no_cache=True)
    if len(rows) < 8:
        return None
    numeric_rows = _rows_to_numeric(rows)
    if len(numeric_rows) < 8:
        return None
    closes = [r["close"] for r in numeric_rows]
    volumes = [r["volume"] for r in numeric_rows]

    pct_change_15m = _safe_pct_change(closes[-1], closes[-2])
    pct_change_1h = _safe_pct_change(closes[-1], closes[-5])
    atr_rel = _compute_atr_rel(numeric_rows, period=6)
    liquidity_usd = closes[-1] * volumes[-1]
    volume_ratio = _compute_volume_ratio(volumes)

    impulse_score = (
        abs(pct_change_15m) * 0.6
        + abs(pct_change_1h) * 0.3
        + max(0.0, volume_ratio - 1.0) * 0.05
        + atr_rel * 0.25
    )

    return Candidate(
        symbol=symbol,
        pct_change_15m=pct_change_15m,
        pct_change_1h=pct_change_1h,
        atr_rel=atr_rel,
        liquidity_usd=liquidity_usd,
        volume_ratio=volume_ratio,
        impulse_score=impulse_score,
    )


def scan_opportunist_candidates(
    *,
    timeframe: str = "15m",
    min_liquidity_usd: float = 100_000.0,
    top_n: int = 3,
    exclude_symbols: Optional[List[str]] = None,
) -> Dict[str, object]:
    """
    Scan the Bybit USDT spot universe and return the strongest movers.
    """
    exclude_symbols = [s.upper() for s in (exclude_symbols or [])]
    universe = _resolve_symbol_universe()
    candidates: List[Candidate] = []
    for symbol in universe:
        if symbol in exclude_symbols:
            continue
        try:
            candidate = _compute_candidate(symbol, timeframe, limit=32)
        except Exception:
            continue
        if not candidate:
            continue
        if candidate.liquidity_usd < min_liquidity_usd:
            continue
        update_universe_stats(
            candidate.symbol,
            realized_vol_15m=abs(candidate.pct_change_15m),
            realized_vol_1h=abs(candidate.pct_change_1h),
            liquidity_usd=candidate.liquidity_usd,
        )
        candidates.append(candidate)

    candidates.sort(key=lambda c: c.impulse_score, reverse=True)
    selected = candidates[:top_n]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "universe_size": len(universe),
        "candidates": [asdict(c) for c in selected],
    }

    out_path = OPPORTUNIST_DIR / "opportunist_candidates.json"
    out_path.write_text(json.dumps(payload, indent=2))
    return payload


def _resolve_symbol_universe(max_symbols: int = 80) -> List[str]:
    symbols: List[str] = []
    try:
        symbols = fetch_bybit_spot_usdt_symbols()
    except Exception:
        symbols = []

    if symbols:
        return symbols[:max_symbols] if max_symbols else symbols

    fallback = get_active_universe(max_symbols=max_symbols)
    if fallback:
        _logger.info(
            "Opportunist scanner using dynamic fallback universe (size=%s).",
            len(fallback),
        )
        return fallback

    _logger.warning(
        "Opportunist scanner fallback universe empty; ensure seed config exists at %s.",
        "config/opportunist_universe_seed.json",
    )
    return []


__all__ = [
    "Candidate",
    "fetch_bybit_spot_usdt_symbols",
    "scan_opportunist_candidates",
]

