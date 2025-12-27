"""
Core models for order routing and exchange integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any
from decimal import Decimal


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    POST_ONLY = "post_only"
    FOK = "fok"
    IOC = "ioc"


class TdMode(str, Enum):
    CASH = "cash"
    CROSS = "cross"
    ISOLATED = "isolated"


class Venue(str, Enum):
    OKX = "OKX"
    BYBIT = "BYBIT"
    BINANCE = "BINANCE"


@dataclass
class OrderIntent:
    """
    High-level instruction from Chloe/the brain.
    This is NOT exchange-specific.
    """
    strategy_id: str
    venue: Venue
    symbol: str               # For OKX, use instId (e.g. BTC-USDT-SWAP)
    side: Side
    quantity: Decimal         # contracts or base units
    price: Optional[Decimal]  # None for market
    order_type: OrderType
    reduce_only: bool = False
    meta: Optional[Dict[str, Any]] = None  # confidence, reasoning, etc.


@dataclass
class ValidatedOrder:
    """
    Order after risk/rules validation. Safe to send to an exchange client.
    """
    venue: Venue
    symbol: str
    side: Side
    quantity: Decimal
    price: Optional[Decimal]
    order_type: OrderType
    td_mode: TdMode
    strategy_id: str
    reduce_only: bool = False
    exchange_specific: Dict[str, Any] | None = None  # e.g. posSide, clOrdId, etc.

