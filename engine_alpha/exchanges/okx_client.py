"""
OKX API v5 REST client with proper signing and DEMO/LIVE support.
"""

from __future__ import annotations

import time
import json
import hmac
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode

import requests
import base64

from engine_alpha.core.models import ValidatedOrder, TdMode, Venue, OrderType, Side
from engine_alpha.exchanges.base_exchange import BaseExchange

logger = logging.getLogger(__name__)


@dataclass
class OkxCredentials:
    api_key: str
    secret_key: str
    passphrase: str
    simulated: bool = False  # demo trading if True


class OkxClient(BaseExchange):
    """
    OKX API v5 REST client with:
      - proper signing (OK-ACCESS-* headers)
      - demo/live selection via x-simulated-trading
      - simple retry + error handling
    """

    def __init__(
        self,
        creds: OkxCredentials,
        rest_base_url: str,
        environment: str = "demo",
        session: Optional[requests.Session] = None,
    ):
        super().__init__(venue=Venue.OKX, name="OKX")
        self.creds = creds
        self.base_url = rest_base_url.rstrip("/")
        self.environment = environment
        self.session = session or requests.Session()

    # ---------- Public helpers ----------

    def place_order(self, order: ValidatedOrder) -> Dict[str, Any]:
        assert order.venue == Venue.OKX, "OkxClient only handles OKX orders"

        if order.order_type == OrderType.MARKET:
            ord_type = "market"
            px = None
        elif order.order_type == OrderType.LIMIT:
            ord_type = "limit"
            px = str(order.price) if order.price is not None else None
        elif order.order_type == OrderType.POST_ONLY:
            ord_type = "post_only"
            px = str(order.price) if order.price is not None else None
        elif order.order_type == OrderType.FOK:
            ord_type = "fok"
            px = str(order.price) if order.price is not None else None
        elif order.order_type == OrderType.IOC:
            ord_type = "ioc"
            px = str(order.price) if order.price is not None else None
        else:
            raise ValueError(f"Unsupported order type for OKX: {order.order_type}")

        payload: Dict[str, Any] = {
            "instId": order.symbol,                 # OKX instId, e.g. BTC-USDT-SWAP
            "tdMode": order.td_mode.value,          # "cross" or "isolated" or "cash"
            "side": order.side.value,               # "buy" / "sell"
            "ordType": ord_type,
            "sz": str(order.quantity),              # contract size as string
        }

        if px is not None:
            payload["px"] = px

        pos_side = None
        if order.exchange_specific:
            pos_side = order.exchange_specific.get("posSide")
        if pos_side:
            payload["posSide"] = pos_side

        if order.reduce_only:
            payload["reduceOnly"] = True

        if order.exchange_specific and order.exchange_specific.get("clOrdId"):
            payload["clOrdId"] = order.exchange_specific["clOrdId"]

        logger.debug("Sending OKX order payload: %s", payload)

        return self._request(
            method="POST",
            path="/api/v5/trade/order",
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
            raise ValueError("Must provide ord_id or cl_ord_id to cancel OKX order")

        body = {
            "instId": symbol,
        }
        if ord_id:
            body["ordId"] = ord_id
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id

        return self._request(
            "POST",
            "/api/v5/trade/cancel-order",
            params=None,
            body=body,
            auth=True,
        )

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if symbol:
            params["instId"] = symbol

        resp = self._request(
            "GET",
            "/api/v5/trade/orders-pending",
            params=params,
            body=None,
            auth=True,
        )
        return resp.get("data", [])

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if symbol:
            params["instId"] = symbol

        resp = self._request(
            "GET",
            "/api/v5/account/positions",
            params=params,
            body=None,
            auth=True,
        )
        return resp.get("data", [])

    def get_instrument_meta(self, symbol: str) -> Dict[str, Any]:
        params = {
            "instType": "SWAP",
            "instId": symbol,
        }
        resp = self._request(
            "GET",
            "/api/v5/public/instruments",
            params=params,
            body=None,
            auth=False,
        )
        data = resp.get("data", [])
        if not data:
            raise ValueError(f"Instrument not found on OKX: {symbol}")
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
            ts = self._iso_timestamp()
            # OKX prehash format: timestamp + method + requestPath + queryString (GET) or body (POST/PUT)
            if method == "GET":
                prehash = ts + method + path + query_string
            else:
                # POST, PUT, DELETE
                prehash = ts + method + path + (body_str if body_str else "")

            sign = self._sign(prehash)
            
            # Debug logging for troubleshooting
            logger.debug(f"OKX auth prehash: {prehash[:100]}...")
            logger.debug(f"OKX timestamp: {ts}")
            logger.debug(f"OKX API key (first 8): {self.creds.api_key[:8]}...")
            logger.debug(f"OKX simulated: {self.creds.simulated}")

            headers.update(
                {
                    "OK-ACCESS-KEY": self.creds.api_key,
                    "OK-ACCESS-SIGN": sign,
                    "OK-ACCESS-TIMESTAMP": ts,
                    "OK-ACCESS-PASSPHRASE": self.creds.passphrase,
                }
            )

            headers["x-simulated-trading"] = "1" if self.creds.simulated else "0"

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
                logger.warning("OKX request error (%s), retry %s/%s", exc, attempt, retries)
                time.sleep(0.2 * attempt)
                continue

            if resp.status_code >= 500:
                if attempt == retries:
                    resp.raise_for_status()
                logger.warning(
                    "OKX server error %s, retry %s/%s", resp.status_code, attempt, retries
                )
                time.sleep(0.2 * attempt)
                continue

            try:
                payload = resp.json()
            except ValueError:
                logger.error("Non-JSON response from OKX: %s", resp.text)
                resp.raise_for_status()
                raise

            code = payload.get("code")
            if code != "0":
                msg = payload.get("msg", "")
                error_msg = f"OKX API error {code}: {msg} (path={path})"
                
                # Provide helpful hints for common errors
                if code == "50119":
                    error_msg += (
                        "\n   Hint: Error 50119 'API key doesn't exist' usually means:\n"
                        "   - REGION MISMATCH: If you're in the US, use 'us.okx.com' instead of 'www.okx.com'\n"
                        "   - API key is incorrect or not created on OKX\n"
                        "   - API key needs to be activated/enabled on OKX dashboard\n"
                        "   - API key permissions are wrong (needs READ + TRADE)\n"
                        "   - API key is for wrong environment (demo vs live)\n"
                        "   - Check OKX dashboard: https://www.okx.com/account/my-api\n"
                        "   - Try: OkxClient(creds, 'https://us.okx.com', 'demo') for US users"
                    )
                
                raise RuntimeError(error_msg)

            return payload

        raise RuntimeError("OKX request failed after retries")

    @staticmethod
    def _iso_timestamp() -> str:
        now = datetime.now(timezone.utc)
        return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _sign(self, message: str) -> str:
        mac = hmac.new(
            self.creds.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

