"""
Live bridge - Phase 12 (read-only)
Provides HTTP health probes for supported exchanges.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2]/'.env')

import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from urllib import parse, request

from engine_alpha.core.paths import REPORTS

BINANCE_HOSTS = ["https://api.binance.us", "https://api.binance.com"]
BYBIT_HOSTS = ["https://api.bybit.com", "https://api.bybit.global"]
OKX_HOSTS = ["https://www.okx.com"]
DEFAULT_HEADERS = {"User-Agent": "ChloeAlpha/1.0 (+health)"}
DEFAULT_TIMEOUT = 3.0

FEED_BINANCE_ENABLED = os.getenv("FEED_BINANCE_ENABLED", "true").lower() == "true"
FEED_BYBIT_ENABLED = os.getenv("FEED_BYBIT_ENABLED", "true").lower() == "true"
FEED_OKX_ENABLED = os.getenv("FEED_OKX_ENABLED", "false").lower() == "true"


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
    exchange_lower = exchange.lower()
    if exchange_lower == "binance":
        hosts = BINANCE_HOSTS
        endpoint = "/api/v3/time"
    elif exchange_lower == "bybit":
        hosts = BYBIT_HOSTS
        endpoint = "/v5/market/time"
    elif exchange_lower == "okx":
        hosts = OKX_HOSTS
        endpoint = "/api/v5/public/time"
    else:
        return {"exchange": exchange, "ok": False, "error": "unsupported_exchange"}

    last_error = ""
    for host in hosts:
        url = f"{host}{endpoint}"
        try:
            resp = _get_json(url)
            body = resp["body"]
            latency = resp["latency_ms"]
            server_ms: Optional[int] = None
            if exchange_lower == "binance":
                server_ms = int(body.get("serverTime")) if body.get("serverTime") else None
            elif exchange_lower == "bybit":
                result = body.get("result", {})
                if "timeSecond" in result:
                    server_ms = int(result["timeSecond"]) * 1000
                elif "time" in body:
                    server_ms = int(body["time"]) * 1000
            else:  # OKX
                data = body.get("data", [])
                if data and "ts" in data[0]:
                    server_ms = int(data[0]["ts"])
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
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)
    return {"exchange": exchange, "ok": False, "error": last_error or "unreachable"}


def _okx_symbol(symbol: str) -> str:
    mapping = {"ETHUSDT": "ETH-USDT", "BTCUSDT": "BTC-USDT"}
    return mapping.get(symbol, symbol.replace("USDT", "-USDT"))


def check_symbols(exchange: str, symbols: List[str]) -> Dict[str, Any]:
    exchange_lower = exchange.lower()
    if exchange_lower == "binance":
        hosts = BINANCE_HOSTS
    elif exchange_lower == "bybit":
        hosts = BYBIT_HOSTS
    elif exchange_lower == "okx":
        hosts = OKX_HOSTS
    else:
        return {"exchange": exchange, "symbols": {}, "error": "unsupported_exchange"}

    result = {"exchange": exchange, "symbols": {}}
    for symbol in symbols:
        entry = {"ok": False}
        last_error = ""
        for host in hosts:
            try:
                if exchange_lower == "binance":
                    url = f"{host}/api/v3/ticker/price?symbol={symbol}"
                elif exchange_lower == "bybit":
                    params = parse.urlencode({"category": "linear", "symbol": symbol})
                    url = f"{host}/v5/market/tickers?{params}"
                else:  # OKX
                    inst_id = _okx_symbol(symbol)
                    url = f"{host}/api/v5/market/ticker?instId={inst_id}"
                resp = _get_json(url)
                body = resp["body"]
                if exchange_lower == "bybit":
                    if not body.get("result", {}).get("list"):
                        raise RuntimeError("empty_result")
                elif exchange_lower == "okx":
                    if not body.get("data"):
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
    elif exchange_lower == "bybit":
        return _bybit_account(BYBIT_HOSTS[0])
    elif exchange_lower == "okx":
        return {"exchange": exchange, "ok": False, "reason": "no_keys"}
    return {"exchange": exchange, "ok": False, "reason": "unsupported_exchange"}


def run_health(symbols: List[str]) -> Dict[str, Any]:
    payload = {"ts": _iso_now()}
    if FEED_BINANCE_ENABLED:
        payload["binance"] = {
            "enabled": True,
            "time": check_time("binance"),
            "symbols": check_symbols("binance", symbols),
            "account": check_account("binance"),
        }
    else:
        payload["binance"] = {"enabled": False}
    if FEED_BYBIT_ENABLED:
        payload["bybit"] = {
            "enabled": True,
            "time": check_time("bybit"),
            "symbols": check_symbols("bybit", symbols),
            "account": check_account("bybit"),
        }
    else:
        payload["bybit"] = {"enabled": False}
    if FEED_OKX_ENABLED:
        payload["okx"] = {
            "enabled": True,
            "time": check_time("okx"),
            "symbols": check_symbols("okx", symbols),
            "account": check_account("okx"),
        }
    else:
        payload["okx"] = {"enabled": False}

    report_path = REPORTS / "feeds_health.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w") as f:
        json.dump(payload, f, indent=2)
    return payload
