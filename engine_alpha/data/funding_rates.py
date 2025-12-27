from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, Optional

import requests

from engine_alpha.core.paths import CONFIG

_FUNDING_CONFIG_CACHE: Optional[Dict[str, object]] = None


def _load_funding_config() -> Dict[str, object]:
    global _FUNDING_CONFIG_CACHE
    if _FUNDING_CONFIG_CACHE is not None:
        return _FUNDING_CONFIG_CACHE
    path = CONFIG / "funding_feeds.json"
    if not path.exists():
        _FUNDING_CONFIG_CACHE = {"default": {"exchanges": [], "max_staleness_minutes": 60}, "symbols": {}}
        return _FUNDING_CONFIG_CACHE
    try:
        _FUNDING_CONFIG_CACHE = json.loads(path.read_text())
    except Exception:
        _FUNDING_CONFIG_CACHE = {"default": {"exchanges": [], "max_staleness_minutes": 60}, "symbols": {}}
    return _FUNDING_CONFIG_CACHE


def _bybit_funding(perp_symbol: Optional[str]) -> Optional[float]:
    if not perp_symbol:
        return None
    try:
        resp = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear", "symbol": perp_symbol},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json().get("result", {}).get("list", [])
        if not data:
            return None
        return float(data[0].get("fundingRate", 0.0))
    except Exception:
        return None


def _binance_futures_funding(perp_symbol: Optional[str]) -> Optional[float]:
    if not perp_symbol:
        return None
    try:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            params={"symbol": perp_symbol},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("lastFundingRate", 0.0))
    except Exception:
        return None


def _okx_funding(perp_symbol: Optional[str]) -> Optional[float]:
    if not perp_symbol:
        return None
    try:
        resp = requests.get(
            "https://www.okx.com/api/v5/public/funding-rate",
            params={"instId": perp_symbol},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return None
        return float(data[0].get("fundingRate", 0.0))
    except Exception:
        return None


EXCHANGE_FETCHERS = {
    "bybit": _bybit_funding,
    "binance_futures": _binance_futures_funding,
    "okx": _okx_funding,
}


def get_funding_bias(symbol: str) -> float:
    """
    Return normalized funding bias for a spot symbol.

    Positive funding => longs paying shorts => short-leaning bias.
    Negative funding => shorts paying longs => long-leaning bias.
    """
    cfg = _load_funding_config()
    sym_cfg = cfg.get("symbols", {}).get(symbol.upper(), {})
    exchanges = cfg.get("default", {}).get("exchanges", [])

    raw_rate: Optional[float] = None
    for exchange in exchanges:
        fetcher = EXCHANGE_FETCHERS.get(exchange)
        if not fetcher:
            continue
        perp_symbol = sym_cfg.get(exchange)
        raw_rate = fetcher(perp_symbol)
        if raw_rate is not None:
            break

    if raw_rate is None:
        return 0.0

    # Normalize: typical raw funding ~0.0001; spikes can reach >0.01.
    # Scale by 100 then apply tanh to map into [-1, 1].
    return float(math.tanh(raw_rate * 100.0))

