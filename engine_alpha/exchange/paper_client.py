"""
Paper Exchange Client - Simulated exchange for paper trading.

Mimics real exchange interface for seamless switching between paper and live.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional

from engine_alpha.core.models import ValidatedOrder, Venue, Side, OrderType

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
PAPER_STATE_FILE = REPORTS_DIR / "paper_trading_state.json"


class PaperExchangeClient:
    """
    Simulated exchange client for paper trading.
    
    Provides the same interface as real exchange clients but executes
    trades against simulated balances and positions.
    """

    def __init__(
        self,
        initial_balance_usdt: float = 10000.0,
        simulated_fee_rate: float = 0.0004,  # 0.04% taker fee
        simulated_slippage_bps: float = 5.0,  # 5 bps slippage
    ):
        """
        Args:
            initial_balance_usdt: Starting paper balance
            simulated_fee_rate: Fee rate to simulate (decimal)
            simulated_slippage_bps: Slippage to simulate (basis points)
        """
        self.venue = Venue.BINANCE  # Paper mimics Binance
        self.name = "Paper"
        self.fee_rate = simulated_fee_rate
        self.slippage_bps = simulated_slippage_bps
        
        # Load or initialize state
        self.state = self._load_state(initial_balance_usdt)
        
        logger.info(
            f"[PAPER] Initialized: balance={self.state['balance_usdt']:.2f} USDT"
        )

    def _load_state(self, initial_balance: float) -> Dict[str, Any]:
        """Load paper trading state from disk or initialize."""
        try:
            if PAPER_STATE_FILE.exists():
                state = json.loads(PAPER_STATE_FILE.read_text())
                logger.info(f"[PAPER] Loaded existing state")
                return state
        except Exception as e:
            logger.warning(f"[PAPER] Could not load state: {e}")
        
        # Initialize new state
        return {
            "balance_usdt": initial_balance,
            "positions": {},  # symbol -> position dict
            "orders": {},  # order_id -> order dict
            "order_counter": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _save_state(self) -> None:
        """Save paper trading state to disk."""
        try:
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            PAPER_STATE_FILE.write_text(json.dumps(self.state, indent=2, default=str))
        except Exception as e:
            logger.error(f"[PAPER] Could not save state: {e}")

    def _get_next_order_id(self) -> str:
        """Generate next order ID."""
        self.state["order_counter"] += 1
        return f"PAPER_{self.state['order_counter']:08d}"

    def _simulate_fill_price(self, symbol: str, side: Side, base_price: float) -> float:
        """Simulate fill price with slippage."""
        slippage_mult = self.slippage_bps / 10000.0
        if side == Side.BUY:
            return base_price * (1 + slippage_mult)  # Buy higher
        else:
            return base_price * (1 - slippage_mult)  # Sell lower

    # ---------- Order Operations ----------

    def place_order(self, order: ValidatedOrder) -> Dict[str, Any]:
        """
        Place a simulated order.
        
        Market orders are filled immediately at simulated price.
        Limit orders are stored and may be filled later.
        """
        order_id = self._get_next_order_id()
        timestamp = datetime.now(timezone.utc)
        
        # For market orders, simulate immediate fill
        if order.order_type == OrderType.MARKET:
            # Get current price (simplified - use order price or fetch)
            base_price = float(order.price) if order.price else 100.0  # Placeholder
            fill_price = self._simulate_fill_price(order.symbol, order.side, base_price)
            quantity = float(order.quantity)
            notional = fill_price * quantity
            fee = notional * self.fee_rate
            
            # Update balance
            if order.side == Side.BUY:
                cost = notional + fee
                if cost > self.state["balance_usdt"]:
                    return {
                        "orderId": order_id,
                        "status": "REJECTED",
                        "reason": "Insufficient balance",
                    }
                self.state["balance_usdt"] -= cost
                
                # Update position
                pos = self.state["positions"].get(order.symbol, {
                    "symbol": order.symbol,
                    "positionAmt": 0.0,
                    "entryPrice": 0.0,
                    "unrealizedProfit": 0.0,
                })
                old_amt = pos["positionAmt"]
                new_amt = old_amt + quantity
                if new_amt != 0:
                    pos["entryPrice"] = (
                        (pos["entryPrice"] * abs(old_amt) + fill_price * quantity)
                        / abs(new_amt)
                    )
                pos["positionAmt"] = new_amt
                self.state["positions"][order.symbol] = pos
                
            else:  # SELL
                revenue = notional - fee
                self.state["balance_usdt"] += revenue
                
                # Update position
                pos = self.state["positions"].get(order.symbol, {
                    "symbol": order.symbol,
                    "positionAmt": 0.0,
                    "entryPrice": 0.0,
                    "unrealizedProfit": 0.0,
                })
                pos["positionAmt"] -= quantity
                if abs(pos["positionAmt"]) < 0.0001:
                    pos["positionAmt"] = 0.0
                    pos["entryPrice"] = 0.0
                self.state["positions"][order.symbol] = pos
            
            self._save_state()
            
            logger.info(
                f"[PAPER] Order filled: {order.side.value} {quantity} {order.symbol} @ {fill_price:.4f}"
            )
            
            return {
                "orderId": order_id,
                "symbol": order.symbol,
                "status": "FILLED",
                "side": order.side.value.upper(),
                "type": "MARKET",
                "origQty": str(order.quantity),
                "executedQty": str(order.quantity),
                "avgPrice": str(fill_price),
                "cumQuote": str(notional),
                "updateTime": int(timestamp.timestamp() * 1000),
            }
        
        # Store limit order for later processing
        order_record = {
            "orderId": order_id,
            "symbol": order.symbol,
            "side": order.side.value.upper(),
            "type": order.order_type.value.upper(),
            "price": str(order.price),
            "origQty": str(order.quantity),
            "executedQty": "0",
            "status": "NEW",
            "time": int(timestamp.timestamp() * 1000),
        }
        self.state["orders"][order_id] = order_record
        self._save_state()
        
        return order_record

    def cancel_order(
        self,
        symbol: str,
        ord_id: Optional[str] = None,
        cl_ord_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cancel a paper order."""
        order_id = ord_id or cl_ord_id
        if order_id and order_id in self.state["orders"]:
            order = self.state["orders"].pop(order_id)
            order["status"] = "CANCELED"
            self._save_state()
            return order
        
        return {"status": "UNKNOWN", "msg": "Order not found"}

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get open paper orders."""
        orders = list(self.state["orders"].values())
        if symbol:
            orders = [o for o in orders if o["symbol"] == symbol]
        return [o for o in orders if o["status"] == "NEW"]

    # ---------- Position Operations ----------

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get paper positions."""
        positions = []
        for sym, pos in self.state["positions"].items():
            if symbol and sym != symbol:
                continue
            if abs(pos.get("positionAmt", 0)) > 0.0001:
                positions.append({
                    "symbol": sym,
                    "positionAmt": str(pos["positionAmt"]),
                    "entryPrice": str(pos["entryPrice"]),
                    "unrealizedProfit": str(pos.get("unrealizedProfit", 0)),
                    "positionSide": "BOTH",
                    "leverage": "1",
                })
        return positions

    def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """Set leverage (no-op for paper)."""
        return {"symbol": symbol, "leverage": leverage}

    def set_margin_type(self, symbol: str, margin_type: str) -> Dict[str, Any]:
        """Set margin type (no-op for paper)."""
        return {"symbol": symbol, "marginType": margin_type}

    # ---------- Account Operations ----------

    def get_account(self) -> Dict[str, Any]:
        """Get paper account info."""
        return {
            "totalWalletBalance": str(self.state["balance_usdt"]),
            "availableBalance": str(self.state["balance_usdt"]),
            "totalUnrealizedProfit": "0",
            "positions": list(self.state["positions"].values()),
        }

    def get_balance(self) -> List[Dict[str, Any]]:
        """Get paper balances."""
        return [
            {
                "asset": "USDT",
                "balance": str(self.state["balance_usdt"]),
                "availableBalance": str(self.state["balance_usdt"]),
                "crossWalletBalance": str(self.state["balance_usdt"]),
                "crossUnPnl": "0",
            }
        ]

    def get_usdt_balance(self) -> Dict[str, Any]:
        """Get USDT balance."""
        return {
            "asset": "USDT",
            "balance": self.state["balance_usdt"],
            "available": self.state["balance_usdt"],
        }

    # ---------- Market Data ----------

    def get_instrument_meta(self, symbol: str) -> Dict[str, Any]:
        """Get instrument metadata (generic for paper)."""
        return {
            "symbol": symbol,
            "status": "TRADING",
            "pricePrecision": 2,
            "quantityPrecision": 3,
            "filters": {
                "lotSize": {"minQty": "0.001", "stepSize": "0.001"},
                "priceFilter": {"tickSize": "0.01"},
                "minNotional": "5",
            },
        }

    def get_ticker_price(self, symbol: str) -> Dict[str, Any]:
        """Get ticker price from live data feeds."""
        # Fetch real price from live prices module for realistic paper trading
        try:
            from engine_alpha.data.live_prices import get_live_ohlcv
            rows, meta = get_live_ohlcv(symbol, "15m", limit=1)
            if rows and len(rows) > 0:
                price = rows[-1].get("close", 0)
                if price and price > 0:
                    return {"symbol": symbol, "price": str(price)}
        except Exception:
            pass
        
        # Fallback: try price feed health
        try:
            from engine_alpha.data.price_feed_health import get_latest_price
            price, meta = get_latest_price(symbol)
            if price and price > 0:
                return {"symbol": symbol, "price": str(price)}
        except Exception:
            pass
        
        # Final fallback: return 0 (caller should handle)
        return {"symbol": symbol, "price": "0"}

    def get_mark_price(self, symbol: str) -> Dict[str, Any]:
        """Get mark price (placeholder)."""
        return {"symbol": symbol, "markPrice": "0", "lastFundingRate": "0"}

    # ---------- Paper-Specific Methods ----------

    def reset_state(self, initial_balance: float = 10000.0) -> Dict[str, Any]:
        """Reset paper trading state to initial values."""
        self.state = {
            "balance_usdt": initial_balance,
            "positions": {},
            "orders": {},
            "order_counter": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state()
        logger.info(f"[PAPER] State reset: balance={initial_balance} USDT")
        return {"success": True, "balance": initial_balance}

    def add_balance(self, amount: float) -> Dict[str, Any]:
        """Add balance to paper account (simulated deposit)."""
        self.state["balance_usdt"] += amount
        self._save_state()
        return {
            "success": True,
            "added": amount,
            "new_balance": self.state["balance_usdt"],
        }

    def get_paper_summary(self) -> Dict[str, Any]:
        """Get summary of paper trading state."""
        total_position_value = 0.0
        for pos in self.state["positions"].values():
            amt = abs(pos.get("positionAmt", 0))
            price = pos.get("entryPrice", 0)
            total_position_value += amt * price
        
        return {
            "balance_usdt": self.state["balance_usdt"],
            "open_positions": len([
                p for p in self.state["positions"].values()
                if abs(p.get("positionAmt", 0)) > 0.0001
            ]),
            "pending_orders": len(self.get_open_orders()),
            "total_position_value": total_position_value,
            "created_at": self.state.get("created_at"),
        }

