"""
Base exchange client interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from decimal import Decimal

from engine_alpha.core.models import ValidatedOrder, Venue


class BaseExchange(ABC):
    """
    Generic exchange interface. Each venue (OKX, Bybit, Binance) implements this.
    """

    def __init__(self, venue: Venue, name: Optional[str] = None):
        self.venue = venue
        self.name = name or venue.value

    @abstractmethod
    def place_order(self, order: ValidatedOrder) -> Dict[str, Any]:
        """Place a validated order at this venue."""
        raise NotImplementedError

    @abstractmethod
    def cancel_order(
        self,
        symbol: str,
        ord_id: Optional[str] = None,
        cl_ord_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_instrument_meta(self, symbol: str) -> Dict[str, Any]:
        """
        Return instrument metadata (minSz, lotSz, tickSz, etc.)
        """
        raise NotImplementedError

