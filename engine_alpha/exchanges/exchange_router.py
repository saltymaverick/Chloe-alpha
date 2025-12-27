"""
Exchange router - routes validated orders to the correct exchange client.
"""

from __future__ import annotations

import os
import logging
import uuid
from decimal import Decimal
from typing import Dict, Any, Optional

from engine_alpha.core.models import OrderIntent, ValidatedOrder, Venue
from engine_alpha.exchanges.base_exchange import BaseExchange
from engine_alpha.risk.risk_engine import RiskEngine

logger = logging.getLogger(__name__)


class ExchangeRouter:
    """
    Routes orders to exchange clients after validation.
    """

    def __init__(
        self,
        risk_engine: RiskEngine,
        okx_client: Optional[BaseExchange] = None,  # Deprecated - kept for compatibility
        bybit_client: Optional[BaseExchange] = None,
    ):
        """
        Args:
            risk_engine: Risk engine for order validation
            okx_client: OKX client instance (deprecated, not used)
            bybit_client: Bybit client instance
        """
        self.risk_engine = risk_engine
        self.okx_client = okx_client  # Deprecated
        self.bybit_client = bybit_client

    def route_and_execute(self, intent: OrderIntent) -> Dict[str, Any]:
        """
        Route an order intent to the appropriate exchange and execute it.
        
        Steps:
        1. Get instrument meta from exchange
        2. Round quantity to lotSz, check minSz
        3. Estimate price for risk calculation
        4. Validate via risk engine
        5. Enrich with clOrdId
        6. Place order via exchange client
        
        Returns:
            Exchange API response dict
        """
        # ---- GLOBAL SHADOW MODE ----
        shadow_mode = os.environ.get("BYBIT_SHADOW_MODE", "true").lower() in ("true", "1", "yes", "on")
        if shadow_mode:
            logger.warning(
                f"[SHADOW-MODE] Blocking real order for {intent.symbol}: "
                f"{intent.side.value} {intent.quantity}"
            )
            return {
                "shadow": True,
                "symbol": intent.symbol,
                "side": intent.side.value,
                "qty": float(intent.quantity),
                "price": float(intent.price) if intent.price else None,
                "strategy": intent.strategy_id,
                "message": "Shadow mode active - order not sent to exchange.",
            }
        # ---- END SHADOW MODE ----
        
        venue = intent.venue
        
        if venue == Venue.BYBIT:
            return self._route_bybit(intent)
        elif venue == Venue.OKX:
            # OKX decommissioned - kept for reference
            raise ValueError("OKX integration is decommissioned. Use BYBIT instead.")
        else:
            raise ValueError(f"Unsupported venue: {venue}")

    def _route_bybit(self, intent: OrderIntent) -> Dict[str, Any]:
        """Route order to Bybit."""
        if not self.bybit_client:
            raise ValueError("Bybit client not configured")
        
        # 1. Get instrument metadata
        try:
            meta = self.bybit_client.get_instrument_meta(intent.symbol)
        except Exception as e:
            raise ValueError(f"Failed to get instrument meta for {intent.symbol}: {e}")
        
        # Extract lotSizeFilter and priceFilter
        lot_size_filter = meta.get("lotSizeFilter", {})
        price_filter = meta.get("priceFilter", {})
        
        lot_size = Decimal(lot_size_filter.get("qtyStep", "1"))
        min_qty = Decimal(lot_size_filter.get("minQty", "0"))
        tick_size = Decimal(price_filter.get("tickSize", "0.01"))
        
        # 2. Round quantity to lot size
        rounded_qty = (intent.quantity / lot_size) * lot_size
        rounded_qty = rounded_qty.quantize(Decimal("0.00000001"))
        
        if rounded_qty < min_qty:
            raise ValueError(
                f"Quantity {rounded_qty} below minimum {min_qty} for {intent.symbol}"
            )
        
        # Update intent with rounded quantity
        intent.quantity = rounded_qty
        
        # Round price to tick size if limit order
        if intent.price is not None:
            rounded_price = (intent.price / tick_size) * tick_size
            intent.price = rounded_price.quantize(Decimal("0.00000001"))
        
        # 3. Get mark price for risk estimation
        price_usd = None
        if intent.price is not None:
            price_usd = float(intent.price)
        else:
            # Estimate from symbol (stub - would fetch mark price)
            if "BTC" in intent.symbol:
                price_usd = 50000.0
            elif "ETH" in intent.symbol:
                price_usd = 3000.0
            else:
                price_usd = 1.0  # Fallback
        
        # 4. Validate via risk engine
        try:
            validated = self.risk_engine.validate_order(
                intent=intent,
                exchange=self.bybit_client,
                price_usd=price_usd,
                leverage=None,  # Would get from config
            )
        except ValueError as e:
            logger.warning(f"Order validation failed: {e}")
            raise
        
        # 5. Enrich with client order ID
        cl_ord_id = f"chloe_{intent.strategy_id}_{uuid.uuid4().hex[:8]}"
        if validated.exchange_specific is None:
            validated.exchange_specific = {}
        validated.exchange_specific["clOrdId"] = cl_ord_id
        
        # 6. Place order via Bybit client
        logger.info(
            f"Placing order: {intent.strategy_id} {intent.side.value} {validated.quantity} {intent.symbol} "
            f"(clOrdId={cl_ord_id})"
        )
        
        try:
            response = self.bybit_client.place_order(validated)
            logger.info(f"Order placed successfully: {response}")
            return response
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            raise

    def _route_okx(self, intent: OrderIntent) -> Dict[str, Any]:
        """Route order to OKX (deprecated - kept for reference)."""
        """Route order to OKX."""
        if not self.okx_client:
            raise ValueError("OKX client not configured")
        
        # 1. Get instrument metadata
        try:
            meta = self.okx_client.get_instrument_meta(intent.symbol)
        except Exception as e:
            raise ValueError(f"Failed to get instrument meta for {intent.symbol}: {e}")
        
        # Extract lotSz and minSz
        lot_sz = Decimal(meta.get("lotSz", "1"))
        min_sz = Decimal(meta.get("minSz", "0"))
        
        # 2. Round quantity to lotSz
        rounded_qty = (intent.quantity / lot_sz) * lot_sz
        rounded_qty = rounded_qty.quantize(Decimal("0.00000001"))
        
        if rounded_qty < min_sz:
            raise ValueError(
                f"Quantity {rounded_qty} below minimum {min_sz} for {intent.symbol}"
            )
        
        # Update intent with rounded quantity
        intent.quantity = rounded_qty
        
        # 3. Get mark price for risk estimation
        # For now, use a simple estimate (would normally fetch from exchange)
        price_usd = None
        if intent.price is not None:
            price_usd = float(intent.price)
        else:
            # Estimate from symbol (stub - would fetch mark price)
            if "BTC" in intent.symbol:
                price_usd = 50000.0
            elif "ETH" in intent.symbol:
                price_usd = 3000.0
            else:
                price_usd = 1.0  # Fallback
        
        # 4. Validate via risk engine
        try:
            validated = self.risk_engine.validate_order(
                intent=intent,
                exchange=self.okx_client,
                price_usd=price_usd,
                leverage=None,  # Would get from config
            )
        except ValueError as e:
            logger.warning(f"Order validation failed: {e}")
            raise
        
        # 5. Enrich with client order ID
        cl_ord_id = f"chloe_{intent.strategy_id}_{uuid.uuid4().hex[:8]}"
        if validated.exchange_specific is None:
            validated.exchange_specific = {}
        validated.exchange_specific["clOrdId"] = cl_ord_id
        
        # 6. Place order via OKX client
        logger.info(
            f"Placing order: {intent.strategy_id} {intent.side.value} {validated.quantity} {intent.symbol} "
            f"(clOrdId={cl_ord_id})"
        )
        
        try:
            response = self.okx_client.place_order(validated)
            logger.info(f"Order placed successfully: {response}")
            return response
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            raise

