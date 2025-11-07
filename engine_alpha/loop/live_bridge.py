"""
Live bridge - Phase 12 (read-only)
Provides HTTP health probes for supported exchanges.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from urllib import request, parse, error

from engine_alpha.core.paths import REPORTS

USER_AGENT = "AlphaChloe/1.0"
TIMEOUT = 5


def _utc_now_ms() -> int:
    return int(time.time() * 1000)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_get(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    if params:
        url = f"{url}?{parse.urlencode(params)}"
    req = request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
            try:
                return json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                return {"raw": data.decode("utf-8", "ignore")}
    except error.HTTPError as exc:  # pragma: no cover - network errors
        raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc
    except Exception as exc:  # pragma: no cover - timeout etc.
        raise RuntimeError(str(exc)) from exc


def check_time(exchange: str) -> Dict[str, Any]:
    url = {
        "binance": "https://api.binance.com/api/v3/time",
        "bybit": "https://api.bybit.com/v5/market/time",
    }.get(exchange.lower())
    result = {"exchange": exchange, "ok": False}
    if not url:
        result["error"] = "unsupported_exchange"
        return result
    try:
        start = _utc_now_ms()
        data = _http_get(url)
        end = _utc_now_ms()
        if exchange.lower() == "binance":
            server_time = int(data.get("serverTime", end))
        else:
            server_time = int(data.get("time", end))
        skew = server_time - end
        result.update(
            {
                "server_time": server_time,
                "clock_skew_ms": skew,
                "latency_ms": end - start,
                "ok": True,
            }
        )
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _binance_symbol(symbol: str) -> Dict[str, Any]:
    return _http_get("https://api.binance.com/api/v3/ticker/24hr", {"symbol": symbol})


def _bybit_symbol(symbol: str) -> Dict[str, Any]:
    return _http_get(
        "https://api.bybit.com/v5/market/tickers",
        {"category": "linear", "symbol": symbol},
    )


def check_symbols(exchange: str, symbols: List[str]) -> Dict[str, Any]:
    result = {"exchange": exchange, "symbols": {}}
    for symbol in symbols:
        entry = {"ok": False}
        try:
            start = _utc_now_ms()
            if exchange.lower() == "binance":
                _binance_symbol(symbol)
            elif exchange.lower() == "bybit":
                payload = _bybit_symbol(symbol)
                if not payload.get("result", {}).get("list"):
                    raise RuntimeError("empty_result")
            else:
                raise RuntimeError("unsupported_exchange")
            latency = _utc_now_ms() - start
            entry.update({"ok": True, "latency_ms": latency})
        except Exception as exc:  # pragma: no cover - network failures
            entry["error"] = str(exc)
        result["symbols"][symbol] = entry
    return result


def _sign_binance(params: Dict[str, Any], secret: str) -> str:
    query = parse.urlencode(params)
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _binance_account() -> Dict[str, Any]:
    key = os.getenv("BINANCE_KEY")
    secret = os.getenv("BINANCE_SECRET")
    if not key or not secret:
        return {"ok": False, "reason": "no_keys"}
    params = {"timestamp": _utc_now_ms(), "recvWindow": 5000}
    signature = _sign_binance(params, secret)
    params["signature"] = signature
    headers = {"X-MBX-APIKEY": key}
    try:
        data = _http_get("https://api.binance.com/api/v3/account", params, headers)
        balances = data.get("balances", [])
        return {"ok": True, "balances_count": len(balances)}
    except Exception as exc:  # pragma: no cover - network/auth failures
        return {"ok": False, "error": str(exc)}


def _sign_bybit(params: Dict[str, Any], secret: str) -> str:
    qs = parse.urlencode(params)
    return hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()


def _bybit_account() -> Dict[str, Any]:
    key = os.getenv("BYBIT_KEY")
    secret = os.getenv("BYBIT_SECRET")
    if not key or not secret:
        return {"ok": False, "reason": "no_keys"}
    params = {
        "api_key": key,
        "timestamp": _utc_now_ms(),
        "recvWindow": 5000,
        "accountType": "UNIFIED",
    }
    signature = _sign_bybit(params, secret)
    params["sign"] = signature
    try:
        data = _http_get("https://api.bybit.com/v5/account/wallet-balance", params)
        result = data.get("result", {})
        return {"ok": True, "asset_count": len(result.get("list", []))}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


def check_account(exchange: str) -> Dict[str, Any]:
    exchange_lower = exchange.lower()
    if exchange_lower == "binance":
        return {"exchange": exchange, **_binance_account()}
    if exchange_lower == "bybit":
        return {"exchange": exchange, **_bybit_account()}
    return {"exchange": exchange, "ok": False, "reason": "unsupported_exchange"}


def run_health(symbols: List[str]) -> Dict[str, Any]:
    payload = {
        "ts": _iso_now(),
        "binance": {
            "time": check_time("binance"),
            "symbols": check_symbols("binance", symbols),
            "account": check_account("binance"),
        },
        "bybit": {
            "time": check_time("bybit"),
            "symbols": check_symbols("bybit", symbols),
            "account": check_account("bybit"),
        },
    }

    report_path = REPORTS / "feeds_health.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w") as f:
        json.dump(payload, f, indent=2)
    return payload
