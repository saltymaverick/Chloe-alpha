"""
Live price utilities - Phase 24
Fetches read-only OHLCV bars from friendly hosts with caching.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, parse, request

try:
    import pandas as pd  # type: ignore
except ImportError:  # pragma: no cover - pandas optional in runtime
    pd = None  # type: ignore

try:  # pragma: no cover - optional parquet engines
    if pd is not None:
        import pyarrow  # type: ignore  # noqa: F401

        _HAS_PARQUET = True
    else:
        _HAS_PARQUET = False
except Exception:  # pragma: no cover
    try:
        if pd is not None:
            import fastparquet  # type: ignore  # noqa: F401

            _HAS_PARQUET = True
        else:
            _HAS_PARQUET = False
    except Exception:  # pragma: no cover
        _HAS_PARQUET = False

from engine_alpha.core.paths import DATA

USER_AGENT = "AlphaChloe-LivePrices/1.0"
TIMEOUT = 3

BINANCE_HOSTS = [
    ("binance_us", "https://api.binance.us"),
    ("binance", "https://api.binance.com"),
]
OKX_HOST = ("okx", "https://www.okx.com")

BINANCE_INTERVALS = {"1m": "1m", "1h": "1h"}
OKX_INTERVALS = {"1m": "1m", "1h": "1H"}
OKX_SYMBOLS = {
    "ETHUSDT": "ETH-USDT",
    "BTCUSDT": "BTC-USDT",
    "SOLUSDT": "SOL-USDT",
}

CACHE_DIR = DATA / "ohlcv"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_request(url: str) -> request.Request:
    headers = {"User-Agent": USER_AGENT}
    return request.Request(url, headers=headers)


def _json_from_url(url: str) -> Optional[Any]:
    try:
        with request.urlopen(_build_request(url), timeout=TIMEOUT) as resp:
            data = resp.read()
        return json.loads(data)
    except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _binance_klines(host: str, symbol: str, interval: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    params = parse.urlencode({"symbol": symbol.upper(), "interval": interval, "limit": min(limit, 1000)})
    url = f"{host}/api/v3/klines?{params}"
    payload = _json_from_url(url)
    if not isinstance(payload, list):
        return None
    rows: List[Dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, list) or len(entry) < 6:
            continue
        try:
            open_time = int(entry[0])
            ts = datetime.fromtimestamp(open_time / 1000, tz=timezone.utc).isoformat()
            rows.append(
                {
                    "ts": ts,
                    "open": float(entry[1]),
                    "high": float(entry[2]),
                    "low": float(entry[3]),
                    "close": float(entry[4]),
                    "volume": float(entry[5]),
                }
            )
        except (ValueError, TypeError):
            continue
    return rows


def _okx_candles(host: str, symbol: str, bar: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    inst_id = OKX_SYMBOLS.get(symbol.upper())
    if not inst_id:
        return None
    params = parse.urlencode({"instId": inst_id, "bar": bar, "limit": min(limit, 300)})
    url = f"{host}/api/v5/market/candles?{params}"
    payload = _json_from_url(url)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    rows: List[Dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, list) or len(entry) < 6:
            continue
        try:
            ts = datetime.fromtimestamp(int(entry[0]) / 1000, tz=timezone.utc).isoformat()
            rows.append(
                {
                    "ts": ts,
                    "open": float(entry[1]),
                    "high": float(entry[2]),
                    "low": float(entry[3]),
                    "close": float(entry[4]),
                    "volume": float(entry[5]),
                }
            )
        except (ValueError, TypeError):
            continue
    rows.sort(key=lambda x: x["ts"])
    return rows


def save_live_cache(symbol: str, timeframe: str, rows: List[Dict[str, Any]], meta: Optional[Dict[str, Any]] = None) -> None:
    if not rows:
        return
    base = CACHE_DIR / f"live_{symbol}_{timeframe}"
    meta_payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "saved_at": _now(),
        "rows": len(rows),
        "last_ts": rows[-1].get("ts"),
    }
    if meta:
        meta_payload.update(meta)
    meta_path = CACHE_DIR / f"live_{symbol}_{timeframe}_meta.json"
    meta_path.write_text(json.dumps(meta_payload, indent=2))

    if pd is not None and _HAS_PARQUET:
        try:
            df = pd.DataFrame(rows)
            df.to_parquet(base.with_suffix(".parquet"), index=False)
            return
        except Exception:
            pass

    # Fallback to JSON cache
    with base.with_suffix(".json").open("w") as f:
        json.dump(rows, f)


def load_live_cache(symbol: str, timeframe: str) -> Optional[List[Dict[str, Any]]]:
    base = CACHE_DIR / f"live_{symbol}_{timeframe}"
    parquet_path = base.with_suffix(".parquet")
    json_path = base.with_suffix(".json")

    if parquet_path.exists() and pd is not None:
        try:
            df = pd.read_parquet(parquet_path)
            return df.to_dict("records")
        except Exception:
            pass

    if json_path.exists():
        try:
            with json_path.open("r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            return None
    return None


def _fetch_from_sources(symbol: str, timeframe: str, limit: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    interval = BINANCE_INTERVALS.get(timeframe, timeframe)
    okx_bar = OKX_INTERVALS.get(timeframe, timeframe.upper())

    for name, host in BINANCE_HOSTS:
        rows = _binance_klines(host, symbol, interval, limit)
        if rows:
            return rows, {"host": host, "exchange": name}

    name, host = OKX_HOST
    rows = _okx_candles(host, symbol, okx_bar, limit)
    if rows:
        return rows, {"host": host, "exchange": name}

    return [], {}


from datetime import timedelta


def _timeframe_seconds(timeframe: str) -> Optional[int]:
    try:
        value = int(timeframe[:-1])
        unit = timeframe[-1].lower()
    except (ValueError, IndexError):
        return None
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return value * multipliers.get(unit, 0) or None


def _ensure_completed(rows: List[Dict[str, Any]], timeframe: str) -> List[Dict[str, Any]]:
    if not rows:
        return rows
    seconds = _timeframe_seconds(timeframe)
    if not seconds:
        return rows
    sorted_rows = sorted(rows, key=lambda x: x.get("ts", ""))
    last = sorted_rows[-1]
    ts_val = last.get("ts")
    if not isinstance(ts_val, str):
        return sorted_rows
    try:
        ts_dt = datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
    except ValueError:
        return sorted_rows
    # If the bar is still forming, drop it
    if ts_dt + timedelta(seconds=seconds) > datetime.now(timezone.utc):
        trimmed = sorted_rows[:-1]
        return trimmed if trimmed else sorted_rows
    return sorted_rows


def get_live_ohlcv(
    symbol: str,
    timeframe: str,
    limit: int = 300,
    *,
    no_cache: bool = False,
) -> List[Dict[str, Any]]:
    rows, meta = _fetch_from_sources(symbol, timeframe, limit)

    if rows:
        completed = _ensure_completed(rows, timeframe)
        trimmed = completed[-limit:] if limit else completed
        save_live_cache(symbol, timeframe, trimmed, meta)
        return trimmed

    if not no_cache:
        cached = load_live_cache(symbol, timeframe)
        if cached:
            completed_cached = _ensure_completed(cached, timeframe)
            return completed_cached[-limit:]
    return []

