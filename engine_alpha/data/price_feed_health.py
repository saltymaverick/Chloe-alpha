"""
Price Feed Health Module (Single Source of Truth)
-------------------------------------------------

Provides unified price feed health checking across the system.
Uses existing OHLCV cache and live price infrastructure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

from engine_alpha.data.live_prices import get_live_ohlcv
from engine_alpha.data import live_prices
from engine_alpha.core.paths import DATA, REPORTS


def get_latest_price(symbol: str) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    Get the latest price for a symbol.
    
    Args:
        symbol: Trading symbol (e.g., "SOLUSDT")
    
    Returns:
        Tuple of (price, meta_dict)
        - price: Latest price or None if unavailable
        - meta_dict: Metadata including source, age, errors, etc.
    """
    meta: Dict[str, Any] = {
        "source_used": None,
        "age_seconds": None,
        "latest_ts": None,
        "latest_price": None,
        "errors": [],
    }
    
    try:
        rows, ohlcv_meta = get_live_ohlcv(symbol, "15m", limit=1)
        
        if not rows:
            meta["errors"].append("no_rows_returned")
            return None, meta
        
        latest_row = rows[-1]
        price = latest_row.get("close")
        
        if price is None:
            meta["errors"].append("no_close_price_in_row")
            return None, meta
        
        try:
            price_float = float(price)
            if price_float <= 0:
                meta["errors"].append(f"invalid_price_value: {price_float}")
                return None, meta
        except (ValueError, TypeError) as e:
            meta["errors"].append(f"price_conversion_error: {str(e)}")
            return None, meta
        
        # Extract metadata from OHLCV meta
        meta["source_used"] = ohlcv_meta.get("source", "unknown")
        meta["age_seconds"] = ohlcv_meta.get("age_s")
        meta["latest_ts"] = latest_row.get("ts") or ohlcv_meta.get("latest_ts")
        meta["latest_price"] = price_float
        
        # Include any errors from OHLCV meta
        if "errors" in ohlcv_meta:
            meta["errors"].extend(ohlcv_meta["errors"])
        
        return price_float, meta
    
    except Exception as e:
        meta["errors"].append(f"exception: {str(e)}")
        return None, meta


def get_latest_trade_price(symbol: str) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    Get a mark-to-market trade/quote price (NOT candle close).

    Uses Binance `/api/v3/ticker/price` across our configured hosts.
    Returns (price, meta). This is intended for MTM close logic where we want a
    real current price rather than the last OHLCV close.
    """
    from urllib import error, parse, request
    import json as _json

    meta: Dict[str, Any] = {
        "source_used": None,
        "age_seconds": None,
        "latest_ts": datetime.now(timezone.utc).isoformat(),
        "latest_price": None,
        "errors": [],
    }
    symbol_u = symbol.upper()

    hosts = getattr(live_prices, "BINANCE_HOSTS", [])
    for host_name, host in hosts:
        try:
            params = parse.urlencode({"symbol": symbol_u})
            url = f"{host}/api/v3/ticker/price?{params}"
            req = request.Request(url, headers={"User-Agent": "AlphaChloe-PriceFeedHealth/1.0"})
            with request.urlopen(req, timeout=3) as resp:
                payload = resp.read()
            obj = _json.loads(payload)
            if not isinstance(obj, dict):
                meta["errors"].append(f"{host_name}:bad_payload")
                continue
            px = obj.get("price")
            if px is None:
                meta["errors"].append(f"{host_name}:no_price_field")
                continue
            try:
                px_f = float(px)
            except Exception:
                meta["errors"].append(f"{host_name}:price_parse_error")
                continue
            if px_f <= 0:
                meta["errors"].append(f"{host_name}:price_nonpositive")
                continue
            meta["source_used"] = f"{host_name}:ticker_price"
            meta["latest_price"] = px_f
            return px_f, meta
        except (error.HTTPError, error.URLError, TimeoutError, _json.JSONDecodeError) as e:
            meta["errors"].append(f"{host_name}:{type(e).__name__}")
        except Exception as e:
            meta["errors"].append(f"{host_name}:exception:{type(e).__name__}")
    return None, meta


def get_latest_candle_ts(symbol: str, timeframe: str = "15m") -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Get the timestamp of the latest candle for a symbol.
    
    Args:
        symbol: Trading symbol
        timeframe: Timeframe (default "15m")
    
    Returns:
        Tuple of (timestamp_iso, meta_dict)
        - timestamp_iso: ISO timestamp string or None
        - meta_dict: Metadata including source, age, errors, etc.
    """
    meta: Dict[str, Any] = {
        "source_used": None,
        "age_seconds": None,
        "latest_ts": None,
        "errors": [],
    }
    
    try:
        rows, ohlcv_meta = get_live_ohlcv(symbol, timeframe, limit=1)
        
        if not rows:
            meta["errors"].append("no_rows_returned")
            return None, meta
        
        latest_row = rows[-1]
        ts = latest_row.get("ts")
        
        if not ts:
            meta["errors"].append("no_timestamp_in_row")
            return None, meta
        
        meta["source_used"] = ohlcv_meta.get("source", "unknown")
        meta["age_seconds"] = ohlcv_meta.get("age_s")
        meta["latest_ts"] = ts
        
        if "errors" in ohlcv_meta:
            meta["errors"].extend(ohlcv_meta["errors"])
        
        return ts, meta
    
    except Exception as e:
        meta["errors"].append(f"exception: {str(e)}")
        return None, meta


def is_price_feed_ok(
    symbol: str,
    max_age_seconds: int = 600,
    require_price: bool = True,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Check if price feed is OK for a symbol.
    
    Uses live OHLCV data as primary source. Ignores stale feeds_health.json files.
    
    Args:
        symbol: Trading symbol
        max_age_seconds: Maximum age in seconds for feed to be considered OK (default 600 = 10 min)
        require_price: If True, require valid price > 0 (default True)
    
    Returns:
        Tuple of (is_ok, meta_dict)
        - is_ok: True if feed is OK, False otherwise
        - meta_dict: Rich metadata including source, age, errors, etc.
    """
    meta: Dict[str, Any] = {
        "source_used": None,
        "age_seconds": None,
        "latest_ts": None,
        "latest_price": None,
        "is_stale": True,
        "errors": [],
    }
    
    try:
        # Use live OHLCV data (ignores stale feeds_health.json)
        rows, ohlcv_meta = get_live_ohlcv(symbol, "15m", limit=1)
        
        if not rows:
            meta["errors"].append("no_rows_returned")
            return False, meta
        
        latest_row = rows[-1]
        
        # Check price if required
        if require_price:
            price = latest_row.get("close")
            if price is None:
                meta["errors"].append("no_close_price_in_row")
                return False, meta
            
            try:
                price_float = float(price)
                if price_float <= 0:
                    meta["errors"].append(f"invalid_price_value: {price_float}")
                    return False, meta
                meta["latest_price"] = price_float
            except (ValueError, TypeError) as e:
                meta["errors"].append(f"price_conversion_error: {str(e)}")
                return False, meta
        
        # Extract timestamp
        ts = latest_row.get("ts")
        meta["latest_ts"] = ts
        
        # Check staleness from OHLCV meta (primary source)
        age_s = ohlcv_meta.get("age_s")
        is_stale_flag = ohlcv_meta.get("is_stale", False)
        
        meta["source_used"] = ohlcv_meta.get("source", "unknown")
        meta["age_seconds"] = age_s
        
        # Check age threshold
        if age_s is not None:
            if age_s > max_age_seconds:
                meta["is_stale"] = True
                meta["errors"].append(f"age_exceeded: {age_s:.0f}s > {max_age_seconds}s")
                return False, meta
        
        # Check stale flag from OHLCV (but only if age is also beyond threshold)
        # If OHLCV reports stale but age is within threshold, trust the age
        # This prevents stale feeds_health.json from causing false positives
        if is_stale_flag and (age_s is None or age_s > max_age_seconds):
            meta["is_stale"] = True
            meta["errors"].append("ohlcv_meta_reports_stale")
            return False, meta
        
        # All checks passed
        meta["is_stale"] = False
        return True, meta
    
    except Exception as e:
        meta["errors"].append(f"exception: {str(e)}")
        return False, meta


class PriceFeedHealth:
    """
    Lightweight class wrapper for price feed health functions.
    
    Provides both class-based and module-level function access for backward compatibility.
    """
    
    @staticmethod
    def get_latest_price(symbol: str) -> Tuple[Optional[float], Dict[str, Any]]:
        """Get the latest price for a symbol."""
        return get_latest_price(symbol)
    
    @staticmethod
    def get_latest_candle_ts(symbol: str, timeframe: str = "15m") -> Tuple[Optional[str], Dict[str, Any]]:
        """Get the timestamp of the latest candle for a symbol."""
        return get_latest_candle_ts(symbol, timeframe=timeframe)
    
    @staticmethod
    def is_price_feed_ok(
        symbol: str,
        max_age_seconds: int = 600,
        require_price: bool = True,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Check if price feed is OK for a symbol."""
        return is_price_feed_ok(symbol, max_age_seconds=max_age_seconds, require_price=require_price)


__all__ = [
    "PriceFeedHealth",
    "get_latest_price",
    "get_latest_candle_ts",
    "is_price_feed_ok",
]

