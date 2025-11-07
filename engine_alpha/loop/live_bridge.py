"""
Live bridge - Phase 12 (read-only)
Provides HTTP health probes for supported exchanges.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from urllib import error, parse, request

from engine_alpha.core.paths import REPORTS

BINANCE_HOSTS = ["https://api.binance.us", "https://api.binance.com"]
BYBIT_HOSTS = ["https://api.bybit.com", "https://api.bybit.global"]
DEFAULT_HEADERS = {"User-Agent": "ChloeAlpha/1.0 (+health)"}
DEFAULT_TIMEOUT = 3.0


def _utc_now_ms() -> int:
    return int(time.time() * 1000)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_json(url: str, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    t0 = time.monotonic()
    req = request.Request(url, headers=DEFAULT_HEADERS)
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        latency_ms = int((time.monotonic() - t0) * 1000)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {"raw": raw.decode("utf-8", "ignore")}
        return {
            "status": getattr(resp, "status", 200),
            "latency_ms": latency_ms,
            "body": body,
        }


def check_time(exchange: str) -> Dict[str, Any]:
    hosts = BINANCE_HOSTS if exchange.lower() == "binance" else BYBIT_HOSTS
    endpoint = "/api/v3/time" if exchange.lower() == "binance" else "/v5/market/time"
    last_error = ""
    for host in hosts:
        url = f"{host}{endpoint}"
        try:
            resp = _get_json(url)
            body = resp["body"]
            latency = resp["latency_ms"]
            server_ms: Optional[int] = None
            if exchange.lower() == "binance":
                server_ms = int(body.get("serverTime")) if body.get("serverTime") else None
            else:
                result = body.get("result", {})
                if "timeSecond" in result:
                    server_ms = int(result["timeSecond"]) * 1000
                elif "time" in body:
                    server_ms = int(body["time"]) * 1000
            if server_ms is None:
                return {
                    "exchange": exchange,
                    "host": host,
                    "ok": False,
                    "error": "malformed_response",
                }
            skew = abs(server_ms - _utc_now_ms())
            return {
                "exchange": exchange,
                "host": host,
                "latency_ms": latency,
                "clock_skew_ms": int(skew),
                "ok": True,
            }
        except Exception as exc:  # pragma: no cover - network errors
            last_error = str(exc)
    return {"exchange": exchange, "ok": False, "error": last_error or "unreachable"}


def check_symbols(exchange: str, symbols: List[str]) -> Dict[str, Any]:
    hosts = BINANCE_HOSTS if exchange.lower() == "binance" else BYBIT_HOSTS
    result = {"exchange": exchange, "symbols": {}}
    for symbol in symbols:
        entry = {"ok": False}
        last_error = ""
        for host in hosts:
            try:
                if exchange.lower() == "binance":
                    url = f"{host}/api/v3/ticker/price?symbol={symbol}"
                else:
                    params = parse.urlencode({"category": "linear", "symbol": symbol})
                    url = f"{host}/v5/market/tickers?{params}"
                resp = _get_json(url)
                body = resp["body"]
                if exchange.lower() == "bybit":
                    if not body.get("result", {}).get("list"):
                        raise RuntimeError("empty_result")
                entry = {
                    "ok": True,
                    "host": host,
                    "latency_ms": resp["latency_ms"],
                }
                break
            except Exception as exc:  # pragma: no cover
                last_error = str(exc)
        if not entry.get("ok"):
            entry["error"] = last_error or "unreachable"
        result["symbols"][symbol] = entry
    return result


def _sign_binance(params: Dict[str, Any], secret: str) -> str:
    query = parse.urlencode(params)
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _binance_account(host: str) -> Dict[str, Any]:
    key = os.getenv("BINANCE_KEY")
    secret = os.getenv("BINANCE_SECRET")
    if not key or not secret:
        return {"ok": False, "reason": "no_keys"}
    params = {"timestamp": _utc_now_ms(), "recvWindow": 5000}
    params["signature"] = _sign_binance(params, secret)
    headers = {**DEFAULT_HEADERS, "X-MBX-APIKEY": key}
    url = f"{host}/api/v3/account?{parse.urlencode(params)}"
    try:
        resp = _get_json(url)
        balances = resp["body"].get("balances", [])
        return {"ok": True, "balances_count": len(balances), "host": host}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc), "host": host}


def _sign_bybit(params: Dict[str, Any], secret: str) -> str:
    query = parse.urlencode(params)
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _bybit_account(host: str) -> Dict[str, Any]:
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
    params["sign"] = _sign_bybit(params, secret)
    url = f"{host}/v5/account/wallet-balance?{parse.urlencode(params)}"
    try:
        resp = _get_json(url)
        result = resp["body"].get("result", {})
        return {"ok": True, "host": host, "asset_count": len(result.get("list", []))}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc), "host": host}


def check_account(exchange: str) -> Dict[str, Any]:
    exchange_lower = exchange.lower()
    if exchange_lower == "binance":
        return _binance_account(BINANCE_HOSTS[0])
    if exchange_lower == "bybit":
        return _bybit_account(BYBIT_HOSTS[0])
    return {"ok": False, "reason": "unsupported_exchange", "exchange": exchange}


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
