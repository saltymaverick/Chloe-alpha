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

import requests

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

from engine_alpha.core.paths import DATA, CONFIG, LOGS
from engine_alpha.core.timeframe_utils import allowed_staleness_seconds
from engine_alpha.core.provider_stickiness import (
    load_state as load_provider_state,
    save_state as save_provider_state,
    get_preferred_source,
    set_preferred_source,
)
from engine_alpha.core.provider_cooldown import (
    load_state as load_cooldown_state,
    save_state as save_cooldown_state,
    in_cooldown,
    set_cooldown,
    clear_cooldown,
)


def normalize_ohlcv_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize OHLCV rows to ensure 'ts' field exists.
    
    Tries multiple timestamp field names and converts to ISO format if needed.
    
    Args:
        rows: List of OHLCV row dicts
        
    Returns:
        Normalized rows with 'ts' field guaranteed
    """
    if not rows:
        return rows
    
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        
        # Create a copy to avoid mutating original
        normalized_row = dict(row)
        
        # If 'ts' already exists and is valid, use it
        if "ts" in normalized_row and normalized_row["ts"]:
            normalized.append(normalized_row)
            continue
        
        # Try to find timestamp in various field names
        ts_value = None
        for key in ["ts", "timestamp", "open_time", "close_time", "time", "t"]:
            val = normalized_row.get(key)
            if val is not None:
                ts_value = val
                break
        
        # Convert to ISO format if it's a numeric timestamp
        if ts_value is not None:
            if isinstance(ts_value, (int, float)):
                # Assume milliseconds if > 1e10, else seconds
                if ts_value > 1e10:
                    ts_value = ts_value / 1000
                ts_dt = datetime.fromtimestamp(ts_value, tz=timezone.utc)
                normalized_row["ts"] = ts_dt.isoformat()
            elif isinstance(ts_value, str):
                # Already a string, use as-is
                normalized_row["ts"] = ts_value
            else:
                # Fallback to current time
                normalized_row["ts"] = datetime.now(timezone.utc).isoformat()
        else:
            # No timestamp found, use current time as fallback
            normalized_row["ts"] = datetime.now(timezone.utc).isoformat()
        
        normalized.append(normalized_row)
    
    return normalized
import logging

# Set up logger for live feed diagnostics
_live_feed_logger = logging.getLogger("live_feeds")
if not _live_feed_logger.handlers:
    _live_feed_logger.setLevel(logging.INFO)
    _live_feed_logger.propagate = False
    LOGS.mkdir(parents=True, exist_ok=True)
    log_file = LOGS / "live_feeds.log"
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt)
    _live_feed_logger.addHandler(fh)

USER_AGENT = "AlphaChloe-LivePrices/1.0"
TIMEOUT = 3

BINANCE_HOSTS = [
    ("binance_us", "https://api.binance.us"),
    ("binance", "https://api.binance.com"),
]
OKX_HOST = ("okx", "https://www.okx.com")
BYBIT_BASE_URL = "https://api.bybit.com"

BINANCE_INTERVALS = {"1m": "1m", "1h": "1h", "15m": "15m"}
OKX_INTERVALS = {"1m": "1m", "1h": "1H", "15m": "15m"}

CACHE_DIR = DATA / "ohlcv"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# In-memory throttling cache (per symbol:timeframe)
_OHLCV_CACHE: Dict[str, Dict[str, Any]] = {}


def min_refresh_seconds(timeframe: str) -> int:
    """
    Get minimum refresh interval in seconds for a timeframe.
    
    Args:
        timeframe: Timeframe string (e.g., "1m", "15m", "1h")
        
    Returns:
        Minimum refresh interval in seconds
    """
    # Throttle policy: don't refetch too often
    policy = {
        "1m": 30,      # 30 seconds
        "5m": 30,      # 30 seconds
        "15m": 90,     # 90 seconds (1.5 min)
        "1h": 300,     # 5 minutes
        "4h": 600,     # 10 minutes
        "1d": 900,     # 15 minutes
    }
    
    # Default to 2 minutes for unknown timeframes
    return policy.get(timeframe.lower(), 120)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_engine_config_json() -> Dict[str, Any]:
    """
    Load config/engine_config.json (best-effort).

    Used only for non-critical runtime preferences (e.g., OHLCV provider order).
    """
    path = CONFIG / "engine_config.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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


def _okx_candles(host: str, inst_id: str, bar: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    """Fetch candles from OKX using instrument ID."""
    params = parse.urlencode({"instId": inst_id, "bar": bar, "limit": min(limit, 300)})
    url = f"{host}/api/v5/market/candles?{params}"
    payload = _json_from_url(url)
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, list):
        # Check for error message
        code = payload.get("code")
        msg = payload.get("msg", "Unknown error")
        if code:
            _live_feed_logger.warning(f"LIVE_FEED_ERROR exchange=okx inst_id={inst_id} code={code} msg={msg}")
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


BYBIT_INTERVALS = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "D",
}


def _bybit_ohlcv(inst_id: str, timeframe: str, limit: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Fetch OHLCV from Bybit public market API (spot category).
    
    Returns:
        Tuple of (rows, error_code) where error_code is None on success,
        or "429", "403", "timeout", etc. on error
    """
    interval = BYBIT_INTERVALS.get(timeframe)
    if interval is None:
        return None, None

    params = {
        "category": "spot",
        "symbol": inst_id,
        "interval": interval,
        "limit": str(min(limit, 200)),
    }

    try:
        resp = requests.get(f"{BYBIT_BASE_URL}/v5/market/kline", params=params, timeout=10)
        
        # Check for rate limit errors
        if resp.status_code == 429:
            _live_feed_logger.warning(
                f"LIVE_FEED_ERROR exchange=bybit inst_id={inst_id} status=429 rate_limit"
            )
            return None, "429"
        
        if resp.status_code == 403:
            _live_feed_logger.warning(
                f"LIVE_FEED_ERROR exchange=bybit inst_id={inst_id} status=403 forbidden"
            )
            return None, "403"
        
        resp.raise_for_status()
        payload = resp.json()
    except requests.exceptions.Timeout:
        _live_feed_logger.warning(
            f"LIVE_FEED_ERROR exchange=bybit inst_id={inst_id} error=timeout"
        )
        return None, "timeout"
    except requests.exceptions.RequestException as exc:
        _live_feed_logger.warning(
            f"LIVE_FEED_ERROR exchange=bybit inst_id={inst_id} error={str(exc)[:100]}"
        )
        return None, "timeout"
    except Exception as exc:
        _live_feed_logger.warning(
            f"LIVE_FEED_ERROR exchange=bybit inst_id={inst_id} error={str(exc)[:100]}"
        )
        return None, "timeout"

    if payload.get("retCode") != 0:
        ret_code = payload.get("retCode")
        _live_feed_logger.warning(
            f"LIVE_FEED_ERROR exchange=bybit inst_id={inst_id} code={ret_code} msg={payload.get('retMsg')}"
        )
        # Map Bybit retCode to error types (some codes might indicate rate limits)
        if ret_code in [10006, 10007]:  # Common rate limit codes
            return None, "429"
        return None, None

    data = payload.get("result", {}).get("list", [])
    if not isinstance(data, list):
        # Caller expects a (rows, error_code) tuple
        _live_feed_logger.warning(
            f"LIVE_FEED_ERROR exchange=bybit inst_id={inst_id} error=malformed_payload_list"
        )
        return None, "malformed_payload"

    # Bybit returns newest first; reverse to chronological
    data = list(reversed(data))
    rows: List[Dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, (list, tuple)) or len(entry) < 6:
            continue
        try:
            ts_ms = int(entry[0])
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
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
    return rows, None  # Success, no error


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


def _load_live_feeds_config() -> Dict[str, Any]:
    """Load live feeds configuration from config/live_feeds.json."""
    config_path = CONFIG / "live_feeds.json"
    default_config = {
        "default": {
            "max_staleness_minutes": 30,
            # Default provider order: bybit-first → binance fallback.
            # OKX is supported, but should be enabled explicitly (avoid surprise lag/semantics differences).
            "exchanges": ["bybit", "binance"]
        },
        "symbols": {}
    }
    
    if not config_path.exists():
        return default_config
    
    try:
        with config_path.open("r") as f:
            data = json.load(f)
        # Ensure structure is valid
        if "default" not in data:
            data["default"] = default_config["default"]
        if "symbols" not in data:
            data["symbols"] = {}
        return data
    except Exception as e:
        _live_feed_logger.error(f"Failed to load live_feeds.json: {e}, using defaults")
        return default_config


def _check_staleness(
    rows: List[Dict[str, Any]],
    max_staleness_seconds: float,
    now: datetime,
    timeframe: Optional[str] = None,
) -> Tuple[bool, float]:
    """
    Check if OHLCV data is stale.
    
    Args:
        rows: OHLCV rows
        max_staleness_seconds: Maximum allowed staleness in seconds
        now: Current datetime
        
    Returns:
        (is_fresh, age_seconds): True if fresh, False if stale, and age in seconds
    """
    if not rows:
        return False, float('inf')

    # Only consider completed candles (drop an in-progress last bar if present)
    rows = _ensure_completed(rows, timeframe, now_dt=now)
    if not rows:
        return False, float('inf')
    
    last_row = rows[-1]
    last_ts_str = last_row.get("ts")
    if not isinstance(last_ts_str, str):
        return False, float('inf')
    
    try:
        if "T" in last_ts_str:
            last_dt = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
        else:
            last_dt = datetime.fromisoformat(last_ts_str)

        # NOTE: In this module, row["ts"] is treated as candle OPEN time.
        # For freshness, we want "age since last completed candle CLOSE".
        tf_s = _timeframe_seconds(timeframe) if timeframe else None
        last_close_dt = last_dt + timedelta(seconds=int(tf_s)) if tf_s else last_dt

        age_seconds = (now - last_close_dt).total_seconds()

        # Future timestamps (negative age) are invalid; treat as stale and clamp to 0
        if age_seconds < 0:
            return False, 0.0
        
        # Data is fresh only if age is non-negative and within staleness threshold
        is_fresh = age_seconds <= max_staleness_seconds
        return is_fresh, age_seconds
    except Exception:
        return False, float('inf')


def get_ohlcv_live_multi_with_meta(
    symbol: str,
    timeframe: str,
    limit: int = 300,
    *,
    now: Optional[datetime] = None,
    no_cache: bool = False
) -> Tuple[Optional[List[Dict[str, Any]]], Dict[str, Any]]:
    """
    Fetch live OHLCV using multi-exchange fallback with timeframe-aware staleness and provider stickiness.
    
    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        timeframe: Timeframe (e.g., "1h")
        limit: Maximum number of bars to return
        now: Current time (defaults to UTC now)
        no_cache: If True, don't use cached data as fallback
    
    Returns:
        Tuple of (rows, meta) where:
        - rows: List of OHLCV rows if available, None otherwise
        - meta: Dict with source, age_s, max_age_s, is_stale, rejected info
    """
    if now is None:
        now = datetime.now(timezone.utc)
    
    # Compute timeframe-aware staleness threshold
    max_staleness_seconds = allowed_staleness_seconds(timeframe)
    max_staleness_minutes = max_staleness_seconds / 60.0
    
    # Load provider stickiness state
    # Load cooldown state
    cooldown_state = load_cooldown_state()
    # Use the caller-provided `now` consistently for all time calculations
    now_dt = now.astimezone(timezone.utc)
    now_ts = now_dt.isoformat()
    
    # Check throttling cache first
    cache_key = f"{symbol}:{timeframe}"
    min_refresh_s = min_refresh_seconds(timeframe)
    
    if cache_key in _OHLCV_CACHE:
        cache_entry = _OHLCV_CACHE[cache_key]
        cache_ts_iso = cache_entry.get("ts_iso")
        cached_rows = cache_entry.get("rows")
        cached_meta = cache_entry.get("meta", {})
        
        if cache_ts_iso and cached_rows:
            try:
                cache_ts = datetime.fromisoformat(cache_ts_iso.replace("Z", "+00:00"))
                age_s = (now_dt - cache_ts).total_seconds()
                
                # If within throttle window, check if cached data is still valid
                if age_s < min_refresh_s:
                    # Check staleness against timeframe-aware window
                    max_staleness_s = allowed_staleness_seconds(timeframe)
                    is_fresh, cached_age_s = _check_staleness(cached_rows, max_staleness_s, now_dt, timeframe)
                    
                    if is_fresh:
                        # Return cached data (throttled), but ensure we have enough bars
                        # If cached has fewer bars than requested, still return it but log warning
                        if limit and len(cached_rows) < limit:
                            _live_feed_logger.warning(
                                f"OHLCV_CACHE_SHORT symbol={symbol} timeframe={timeframe} "
                                f"cached={len(cached_rows)} requested={limit}"
                            )
                        # Return up to limit bars from cache
                        cached_meta["source"] = cached_meta.get("source", "cached")
                        cached_meta["ohlcv_fetch_throttled"] = True
                        cached_meta.setdefault("attempts", [])
                        cached_meta.setdefault("cooldown_skipped", {})
                        cached_meta.setdefault("rejected", {})
                        normalized_cached = normalize_ohlcv_rows(cached_rows[-limit:] if limit else cached_rows)
                        return normalized_cached, cached_meta
            except (ValueError, TypeError, AttributeError):
                pass  # Continue to fetch if cache parse fails
    
    provider_state = load_provider_state()
    preferred_source = get_preferred_source(provider_state, symbol, timeframe)
    
    # Load feed configuration
    feeds_config = _load_live_feeds_config()
    default_config = feeds_config.get("default", {})
    symbol_config = feeds_config.get("symbols", {}).get(symbol.upper(), {})
    
    # Provider priority (configurable):
    # - If config/engine_config.json defines "ohlcv_providers", use that order.
    # - Otherwise default to Bybit-first → Binance fallback.
    engine_cfg = _load_engine_config_json()
    cfg_order = engine_cfg.get("ohlcv_providers")
    if isinstance(cfg_order, list) and all(isinstance(x, str) for x in cfg_order) and cfg_order:
        default_exchanges = [x.strip().lower() for x in cfg_order if x and str(x).strip()]
    else:
        default_exchanges = ["bybit", "binance"]
    exchanges = symbol_config.get("exchanges", default_config.get("exchanges", default_exchanges))
    inst_ids = symbol_config.get("inst_ids", {})

    # Operator-proof instrumentation: record provider selection attempts and reasons.
    attempts: List[Dict[str, Any]] = []
    
    # Filter out providers in cooldown
    available_exchanges = []
    cooldown_skipped = {}
    
    for ex in exchanges:
        provider_name = ex.upper()
        if in_cooldown(cooldown_state, provider_name, now_ts):
            cooldown_skipped[provider_name] = cooldown_state.get(provider_name, {}).get("cooldown_until_ts")
            attempts.append(
                {
                    "exchange": ex,
                    "status": "cooldown",
                    "cooldown_until_ts": cooldown_skipped[provider_name],
                }
            )
            continue
        available_exchanges.append(ex)
    
    # If preferred source is not in cooldown, prioritize it
    if preferred_source and preferred_source in available_exchanges:
        available_exchanges = [preferred_source] + [e for e in available_exchanges if e != preferred_source]
    elif preferred_source and preferred_source not in available_exchanges:
        # Preferred is in cooldown, use priority order
        priority_order = ["binance", "bybit", "okx"]
        available_exchanges = [e for e in priority_order if e in available_exchanges] + [
            e for e in available_exchanges if e not in priority_order
        ]
    
    meta: Dict[str, Any] = {
        "source": None,
        "age_s": None,
        "max_age_s": max_staleness_seconds,
        "is_stale": True,
        "rejected": {},
        "cooldown_skipped": cooldown_skipped,
        "attempts": attempts,
        "ohlcv_fetch_throttled": False,
    }
    
    best_rows = None
    best_meta = None
    best_age_s = float('inf')
    
    # Try each available exchange in order
    for exchange_name in available_exchanges:
        try:
            rows = None
            exchange_meta = {"exchange": exchange_name}
            attempt_meta: Dict[str, Any] = {"exchange": exchange_name}
            
            if exchange_name == "bybit":
                inst_id = inst_ids.get("bybit", symbol.upper())
                rows, error_code = _bybit_ohlcv(inst_id, timeframe, limit)
                attempt_meta["inst_id"] = inst_id
                
                # Handle rate limit errors
                if error_code in ["429", "403", "timeout"]:
                    cooldown_state = set_cooldown(cooldown_state, "BYBIT", now_ts, error_code)
                    save_cooldown_state(cooldown_state)
                    meta["rejected"]["bybit"] = f"cooldown_{error_code}"
                    attempt_meta["status"] = "cooldown_set"
                    attempt_meta["error_code"] = error_code
                    attempts.append(attempt_meta)
                    continue
                
                if rows:
                    # Clear cooldown on success
                    cooldown_state = clear_cooldown(cooldown_state, "BYBIT")
                    save_cooldown_state(cooldown_state)
                    exchange_meta["host"] = BYBIT_BASE_URL
                    exchange_meta["exchange"] = "bybit"
            
            elif exchange_name == "binance":
                # Try Binance hosts in order
                interval = BINANCE_INTERVALS.get(timeframe, timeframe)
                for name, host in BINANCE_HOSTS:
                    inst_id = inst_ids.get("binance", symbol.upper())
                    rows = _binance_klines(host, inst_id, interval, limit)
                    attempts.append(
                        {
                            "exchange": "binance",
                            "host": host,
                            "inst_id": inst_id,
                            "status": "success" if rows else "no_data",
                        }
                    )
                    if rows:
                        exchange_meta["host"] = host
                        exchange_meta["exchange"] = name
                        break
            
            elif exchange_name == "okx":
                name, host = OKX_HOST
                okx_bar = OKX_INTERVALS.get(timeframe, timeframe.upper())
                inst_id = inst_ids.get("okx", f"{symbol.upper().replace('USDT', '-USDT')}")
                rows = _okx_candles(host, inst_id, okx_bar, limit)
                attempts.append(
                    {
                        "exchange": "okx",
                        "host": host,
                        "inst_id": inst_id,
                        "status": "success" if rows else "no_data",
                    }
                )
                if rows:
                    exchange_meta["host"] = host
                    exchange_meta["exchange"] = name
            
            if rows:
                # Normalize rows to ensure 'ts' field exists
                rows = normalize_ohlcv_rows(rows)
                
                # Check staleness using seconds-based threshold (now_dt is defined above)
                is_fresh, age_seconds = _check_staleness(rows, max_staleness_seconds, now_dt, timeframe)
                age_minutes = age_seconds / 60.0
                
                if is_fresh:
                    # Data is fresh - process and return
                    completed = _ensure_completed(rows, timeframe, now_dt=now_dt)
                    trimmed = completed[-limit:] if limit else completed
                    
                    # Save to cache
                    save_live_cache(symbol, timeframe, trimmed, exchange_meta)
                    
                    # Update provider stickiness
                    set_preferred_source(provider_state, symbol, timeframe, exchange_name, now.isoformat())
                    save_provider_state(provider_state)
                    
                    # Update in-memory cache
                    _OHLCV_CACHE[cache_key] = {
                        "ts_iso": now_ts,
                        "rows": trimmed,
                        "meta": exchange_meta,
                    }
                    
                    # Build metadata
                    result_meta = {
                        "source": exchange_name,
                        "age_s": age_seconds,
                        "max_age_s": max_staleness_seconds,
                        "is_stale": False,
                        "rejected": meta.get("rejected", {}),
                        "cooldown_skipped": cooldown_skipped,
                        "attempts": attempts,
                    }
                    
                    last_ts = trimmed[-1].get("ts") if trimmed else "unknown"
                    _live_feed_logger.info(
                        f"LIVE_FEED_OK symbol={symbol} exchange={exchange_name} "
                        f"last_ts={last_ts} age_minutes={age_minutes:.1f} rows={len(trimmed)}"
                    )
                    
                    return trimmed, result_meta
                else:
                    # Data is stale - track as rejected, but keep as best if better than previous
                    if age_seconds < best_age_s:
                        best_rows = rows
                        best_age_s = age_seconds
                        best_meta = {
                            "source": exchange_name,
                            "age_s": age_seconds,
                            "max_age_s": max_staleness_seconds,
                            "is_stale": True,
                            "rejected": meta.get("rejected", {}),
                            "cooldown_skipped": cooldown_skipped,
                            "attempts": attempts,
                        }
                    
                    meta["rejected"][exchange_name] = f"stale age_s={age_seconds:.1f} > max_age_s={max_staleness_seconds:.1f}"
                    last_ts = rows[-1].get("ts") if rows else "unknown"
                    _live_feed_logger.warning(
                        f"LIVE_FEED_STALE symbol={symbol} exchange={exchange_name} "
                        f"last_ts={last_ts} age_minutes={age_minutes:.1f} max_staleness_minutes={max_staleness_minutes:.1f}"
                    )
            else:
                # Fetch failed - log and continue
                meta["rejected"][exchange_name] = "No data returned"
                if exchange_name == "bybit":
                    attempt_meta["status"] = "no_data"
                    attempts.append(attempt_meta)
                _live_feed_logger.warning(
                    f"LIVE_FEED_ERROR symbol={symbol} exchange={exchange_name} "
                    f"error=No data returned"
                )
        
        except Exception as e:
            meta["rejected"][exchange_name] = f"Exception: {str(e)[:50]}"
            attempts.append({"exchange": exchange_name, "status": "exception", "error": str(e)[:100]})
            _live_feed_logger.error(
                f"LIVE_FEED_ERROR symbol={symbol} exchange={exchange_name} "
                f"error={str(e)[:100]}"
            )
            continue
    
    # All exchanges failed or returned stale data
    # Return best available if we have any data (even if stale)
    if best_rows:
        # Normalize rows before returning
        best_rows = normalize_ohlcv_rows(best_rows)
        completed = _ensure_completed(best_rows, timeframe, now_dt=now_dt)
        trimmed = completed[-limit:] if limit else completed
        
        # Update provider stickiness even for stale data (it's the best we have)
        if best_meta:
            set_preferred_source(provider_state, symbol, timeframe, best_meta["source"], now.isoformat())
            save_provider_state(provider_state)
        
        _live_feed_logger.warning(
            f"LIVE_FEED_BEST_AVAILABLE symbol={symbol} timeframe={timeframe} "
            f"source={best_meta.get('source')} age_s={best_age_s:.1f} max_age_s={max_staleness_seconds:.1f} "
            f"exchanges_tried={exchanges}"
        )
        
        return trimmed, best_meta or meta
    
    # No data available from live providers - try cached fallback
    if not no_cache:
        # First try in-memory cache
        if cache_key in _OHLCV_CACHE:
            cached_entry = _OHLCV_CACHE[cache_key]
            cached_rows = cached_entry.get("rows")
            cached_meta = cached_entry.get("meta", {})
            
            if cached_rows:
                # Normalize cached rows
                cached_rows = normalize_ohlcv_rows(cached_rows)
                
                is_fresh, cached_age_s = _check_staleness(cached_rows, max_staleness_seconds, now, timeframe)
                if is_fresh:
                    meta["source"] = cached_meta.get("source", "cached")
                    meta["age_s"] = cached_age_s
                    meta["is_stale"] = False
                    meta["ohlcv_fetch_throttled"] = True
                    return cached_rows[-limit:] if limit else cached_rows, meta
                else:
                    # Even if stale, return cached if within reasonable bounds (bounded staleness)
                    max_reasonable_age = max_staleness_seconds * 2  # Allow 2x for fallback
                    if cached_age_s <= max_reasonable_age:
                        meta["source"] = cached_meta.get("source", "cached_stale")
                        meta["age_s"] = cached_age_s
                        meta["is_stale"] = True
                        meta["ohlcv_fetch_throttled"] = True
                        return cached_rows[-limit:] if limit else cached_rows, meta
        
        # Fallback to disk cache
        cached_rows = load_live_cache(symbol, timeframe)
        if cached_rows:
            is_fresh, cached_age_s = _check_staleness(cached_rows, max_staleness_seconds, now, timeframe)
            if is_fresh:
                meta["source"] = "cached"
                meta["age_s"] = cached_age_s
                meta["is_stale"] = False
                meta["ohlcv_fetch_throttled"] = True
                return cached_rows[-limit:] if limit else cached_rows, meta
            else:
                # Even if stale, return cached if within reasonable bounds (bounded staleness)
                max_reasonable_age = max_staleness_seconds * 2  # Allow 2x for fallback
                if cached_age_s <= max_reasonable_age:
                    meta["source"] = "cached_stale"
                    meta["age_s"] = cached_age_s
                    meta["is_stale"] = True
                    meta["ohlcv_fetch_throttled"] = True
                    return cached_rows[-limit:] if limit else cached_rows, meta
    
    # No data available at all
    _live_feed_logger.error(
        f"LIVE_FEED_UNAVAILABLE symbol={symbol} timeframe={timeframe} "
        f"exchanges_tried={available_exchanges} max_staleness_seconds={max_staleness_seconds:.1f}"
    )
    
    meta["rejected"] = meta.get("rejected", {})
    return None, meta


def get_ohlcv_live_multi(
    symbol: str,
    timeframe: str,
    limit: int = 300,
    *,
    now: Optional[datetime] = None,
    no_cache: bool = False
) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch live OHLCV using multi-exchange fallback with timeframe-aware staleness.
    
    Legacy wrapper that returns only rows (for backward compatibility).
    
    Args:
        symbol: Trading symbol (e.g., "MATICUSDT")
        timeframe: Timeframe (e.g., "15m")
        limit: Maximum number of bars to return
        now: Current time (defaults to UTC now)
        no_cache: If True, don't use cached data as fallback
    
    Returns:
        List of OHLCV rows if available, None otherwise
    """
    rows, _ = get_ohlcv_live_multi_with_meta(symbol, timeframe, limit=limit, now=now, no_cache=no_cache)
    return rows


def _fetch_from_sources(symbol: str, timeframe: str, limit: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Legacy function - now routes through get_ohlcv_live_multi.
    Kept for backward compatibility.
    """
    rows = get_ohlcv_live_multi(symbol, timeframe, limit=limit, no_cache=True)
    if rows:
        return rows, {"exchange": "multi-source"}
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


def _ensure_completed(
    rows: List[Dict[str, Any]],
    timeframe: str,
    *,
    now_dt: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
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
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    if ts_dt + timedelta(seconds=seconds) > now_dt:
        trimmed = sorted_rows[:-1]
        return trimmed if trimmed else sorted_rows
    return sorted_rows


def get_live_ohlcv_packet(
    symbol: str,
    timeframe: str,
    limit: int = 300,
    *,
    now: Optional[datetime] = None,
    no_cache: bool = False,
) -> Dict[str, Any]:
    """
    Canonical candle packet for upstream consumers (signals/gates/reflection).

    Returns a stable schema:
      {
        "symbol": "...",
        "timeframe": "...",
        "candles": [{"t": epoch_s, "o":..., "h":..., "l":..., "c":..., "v":...}, ...],
        "meta": {
          "source": "bybit|binance|okx|cached|...",
          "fetched_at": ISO-UTC,
          "age_seconds": float|None,
          "aligned_to_tf": bool,
          "last_candle_ts": ISO-UTC|None,
        }
      }
    """
    if now is None:
        now = datetime.now(timezone.utc)
    now_dt = now.astimezone(timezone.utc)

    rows, meta = get_ohlcv_live_multi_with_meta(
        symbol,
        timeframe,
        limit=limit,
        now=now_dt,
        no_cache=no_cache,
    )
    rows = rows or []

    tf_s = _timeframe_seconds(timeframe) or 0
    candles: List[Dict[str, Any]] = []
    aligned = True

    def _iso_to_epoch_s(ts_iso: Any) -> Optional[int]:
        if not isinstance(ts_iso, str) or not ts_iso:
            return None
        try:
            dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return None

    seen_t = set()
    for r in rows:
        t = _iso_to_epoch_s(r.get("ts"))
        if t is None:
            continue
        if tf_s and (t % tf_s) != 0:
            aligned = False
        if t in seen_t:
            continue
        seen_t.add(t)
        try:
            candles.append(
                {
                    "t": t,
                    "o": float(r.get("open")),
                    "h": float(r.get("high")),
                    "l": float(r.get("low")),
                    "c": float(r.get("close")),
                    "v": float(r.get("volume", 0.0)),
                }
            )
        except Exception:
            continue

    candles.sort(key=lambda x: x["t"])
    last_open_ts = rows[-1].get("ts") if rows else None
    last_open_t = candles[-1]["t"] if candles else None
    last_close_ts = None
    if last_open_t is not None and tf_s:
        try:
            last_close_dt = datetime.fromtimestamp(int(last_open_t + tf_s), tz=timezone.utc)
            last_close_ts = last_close_dt.isoformat()
        except Exception:
            last_close_ts = None

    # Prefer age since last completed close (derived) over provider meta.age_s (which may be open-based).
    age_seconds = meta.get("age_s")
    if last_close_ts:
        try:
            lcdt = datetime.fromisoformat(str(last_close_ts).replace("Z", "+00:00"))
            if lcdt.tzinfo is None:
                lcdt = lcdt.replace(tzinfo=timezone.utc)
            age_seconds = (now_dt - lcdt).total_seconds()
        except Exception:
            pass

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": candles[-limit:] if limit else candles,
        "meta": {
            "source": meta.get("source"),
            "fetched_at": now_dt.isoformat(),
            "age_seconds": age_seconds,
            "aligned_to_tf": bool(aligned),
            # Operator-proof debugging for provider selection:
            "attempts": meta.get("attempts", []),
            # Back-compat name kept (this module treats ts as candle OPEN time)
            "last_candle_ts": last_open_ts,
            # Explicit fields to avoid operator confusion
            "last_bar_open_ts": last_open_ts,
            "last_bar_close_ts": last_close_ts,
        },
    }


def get_live_ohlcv(
    symbol: str,
    timeframe: str,
    limit: int = 300,
    *,
    no_cache: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Get live OHLCV data with multi-exchange fallback, timeframe-aware staleness, and provider stickiness.
    
    Args:
        symbol: Trading symbol (e.g., "ETHUSDT")
        timeframe: Timeframe (e.g., "1h")
        limit: Maximum number of bars
        no_cache: If True, don't use cached data
    
    Returns:
        Tuple of (rows, meta) where:
        - rows: List of OHLCV rows (empty list if unavailable)
        - meta: Dict with source, age_s, max_age_s, is_stale info
    """
    rows, meta = get_ohlcv_live_multi_with_meta(symbol, timeframe, limit=limit, no_cache=no_cache)
    
    if rows:
        return rows, meta
    
    # Return empty list with metadata
    return [], meta

