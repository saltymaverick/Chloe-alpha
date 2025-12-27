"""
Bybit API v5 REST client with proper signing.
"""

from __future__ import annotations

import os
import time
import json
import hmac
import hashlib
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode

import requests

from engine_alpha.core.models import ValidatedOrder, TdMode, Venue, OrderType, Side
from engine_alpha.exchanges.base_exchange import BaseExchange

logger = logging.getLogger(__name__)


class BybitClient(BaseExchange):
    """
    Bybit API v5 REST client with:
      - proper signing (X-BAPI-* headers)
      - testnet support
      - simple retry + error handling
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.bybit.com",
        use_testnet: bool = False,
        session: Optional[requests.Session] = None,
    ):
        """
        Args:
            api_key: Bybit API key
            api_secret: Bybit API secret
            base_url: Base URL (default: https://api.bybit.com)
            use_testnet: If True, use testnet URL
            session: Optional requests.Session for connection pooling
        """
        super().__init__(venue=Venue.BYBIT, name="Bybit")
        self.api_key = api_key
        self.api_secret = api_secret
        
        if use_testnet:
            self.base_url = "https://api-testnet.bybit.com"
        else:
            self.base_url = base_url.rstrip("/")
        
        self.session = session or requests.Session()
        
        # ---------- PROXY SETUP ----------
        proxy_host = os.environ.get("BYBIT_PROXY_HOST")
        proxy_port = os.environ.get("BYBIT_PROXY_PORT")
        proxy_user = os.environ.get("BYBIT_PROXY_USER")
        proxy_pass = os.environ.get("BYBIT_PROXY_PASS")
        proxy_proto = os.environ.get("BYBIT_PROXY_PROTOCOL", "http")
        
        if proxy_host and proxy_port and proxy_user and proxy_pass:
            proxy_url = f"{proxy_proto}://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
            self.session.proxies.update({
                "http": proxy_url,
                "https": proxy_url,
            })
            logger.info(f"[BYBIT] Proxy enabled: {proxy_proto}://{proxy_user}:***@{proxy_host}:{proxy_port}")
        else:
            logger.debug("[BYBIT] Proxy NOT set. Direct connection.")

    # ---------- Public helpers ----------

    def place_order(self, order: ValidatedOrder) -> Dict[str, Any]:
        assert order.venue == Venue.BYBIT, "BybitClient only handles Bybit orders"

        # Map order types
        if order.order_type == OrderType.MARKET:
            order_type = "Market"
        elif order.order_type == OrderType.LIMIT:
            order_type = "Limit"
        else:
            raise ValueError(f"Unsupported order type for Bybit: {order.order_type}")

        # Map side
        side = "Buy" if order.side == Side.BUY else "Sell"

        # Build payload
        payload: Dict[str, Any] = {
            "category": "linear",  # linear perpetuals
            "symbol": order.symbol,  # e.g. BTCUSDT
            "side": side,
            "orderType": order_type,
            "qty": str(order.quantity),
        }

        # Add price for limit orders
        if order.order_type == OrderType.LIMIT and order.price is not None:
            payload["price"] = str(order.price)

        # Add reduce-only flag
        if order.reduce_only:
            payload["reduceOnly"] = True

        # Add client order ID if provided
        if order.exchange_specific and order.exchange_specific.get("clOrdId"):
            payload["orderLinkId"] = order.exchange_specific["clOrdId"]

        logger.debug("Sending Bybit order payload: %s", payload)

        return self._request(
            method="POST",
            path="/v5/order/create",
            params=None,
            body=payload,
            auth=True,
        )

    def cancel_order(
        self,
        symbol: str,
        ord_id: Optional[str] = None,
        cl_ord_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not (ord_id or cl_ord_id):
            raise ValueError("Must provide ord_id or cl_ord_id to cancel Bybit order")

        body = {
            "category": "linear",
            "symbol": symbol,
        }

        if ord_id:
            body["orderId"] = ord_id
        if cl_ord_id:
            body["orderLinkId"] = cl_ord_id

        return self._request(
            "POST",
            "/v5/order/cancel",
            params=None,
            body=body,
            auth=True,
        )

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "category": "linear",
        }
        if symbol:
            params["symbol"] = symbol

        resp = self._request(
            "GET",
            "/v5/order/realtime",
            params=params,
            body=None,
            auth=True,
        )
        return resp.get("result", {}).get("list", [])

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "category": "linear",
        }
        if symbol:
            params["symbol"] = symbol

        resp = self._request(
            "GET",
            "/v5/position/list",
            params=params,
            body=None,
            auth=True,
        )
        return resp.get("result", {}).get("list", [])

    def get_instrument_meta(self, symbol: str) -> Dict[str, Any]:
        """Get instrument metadata (lot size, tick size, min order size, etc.)."""
        params = {
            "category": "linear",
            "symbol": symbol,
        }
        resp = self._request(
            "GET",
            "/v5/market/instruments-info",
            params=params,
            body=None,
            auth=False,
        )
        data = resp.get("result", {}).get("list", [])
        if not data:
            raise ValueError(f"Instrument not found on Bybit: {symbol}")
        return data[0]

    # ---------- Internal REST plumbing ----------

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]],
        body: Optional[Dict[str, Any]],
        auth: bool = False,
        retries: int = 3,
        timeout: int = 10,
    ) -> Dict[str, Any]:
        method = method.upper()
        url = self.base_url + path

        query_string = ""
        if params:
            query_string = "?" + urlencode(params)
            url = url + query_string

        body_str = ""
        if body is not None:
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if auth:
            # Bybit v5 signing: timestamp + api_key + recv_window + query_string + body
            # Note: query_string for signing should NOT include the "?" prefix
            timestamp = str(int(time.time() * 1000))  # milliseconds
            recv_window = "5000"  # 5 seconds

            # Build param_str for signing
            param_str = timestamp + self.api_key + recv_window
            if query_string:
                # Remove "?" prefix for signing (Bybit expects query params without "?")
                sign_query = query_string[1:] if query_string.startswith("?") else query_string
                param_str += sign_query
            if body_str:
                param_str += body_str

            # Sign with HMAC-SHA256, hex encode
            sign = hmac.new(
                self.api_secret.encode("utf-8"),
                param_str.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            headers.update(
                {
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-TIMESTAMP": timestamp,
                    "X-BAPI-RECV-WINDOW": recv_window,
                    "X-BAPI-SIGN": sign,
                }
            )

        for attempt in range(1, retries + 1):
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=body_str if body_str else None,
                    timeout=timeout,
                )
            except Exception as exc:
                if attempt == retries:
                    raise
                logger.warning("Bybit request error (%s), retry %s/%s", exc, attempt, retries)
                time.sleep(0.2 * attempt)
                continue

            if resp.status_code >= 500:
                if attempt == retries:
                    resp.raise_for_status()
                logger.warning(
                    "Bybit server error %s, retry %s/%s", resp.status_code, attempt, retries
                )
                time.sleep(0.2 * attempt)
                continue

            try:
                payload = resp.json()
            except ValueError:
                logger.error("Non-JSON response from Bybit: %s", resp.text)
                resp.raise_for_status()
                raise

            ret_code = payload.get("retCode")
            if ret_code != 0:
                msg = payload.get("retMsg", "")
                raise RuntimeError(f"Bybit API error {ret_code}: {msg} (path={path})")

            return payload

        raise RuntimeError("Bybit request failed after retries")

