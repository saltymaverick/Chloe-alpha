"""
Risk engine for order validation before execution.
"""

from __future__ import annotations

import logging
import yaml
from pathlib import Path
from typing import Dict, Any, Callable, Optional
from decimal import Decimal
from datetime import datetime, timezone
from collections import defaultdict

from engine_alpha.core.models import OrderIntent, ValidatedOrder, Venue, TdMode, OrderType, Side
from engine_alpha.core.paths import CONFIG

logger = logging.getLogger(__name__)


class RiskEngine:
    """
    Validates orders before execution.
    Enforces global limits, venue rules, strategy caps, and rate limits.
    """

    def __init__(
        self,
        risk_config_path: str = "config/risk.yaml",
        pnl_provider: Optional[Callable[[], Dict[str, float]]] = None,
        position_provider: Optional[Callable[[], list]] = None,
    ):
        """
        Args:
            risk_config_path: Path to risk.yaml config file
            pnl_provider: Function that returns {"daily_loss_abs": float, "daily_loss_pct": float}
            position_provider: Function that returns list of open positions
        """
        self.config_path = Path(risk_config_path)
        self.config = self._load_config()
        self.pnl_provider = pnl_provider or (lambda: {"daily_loss_abs": 0.0, "daily_loss_pct": 0.0})
        self.position_provider = position_provider or (lambda: [])
        
        # Rate limiting: track orders per minute
        self._order_timestamps: list[float] = []
        self._symbol_order_timestamps: Dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = datetime.now(timezone.utc).timestamp()

    def _load_config(self) -> Dict[str, Any]:
        """Load risk configuration from YAML file."""
        if not self.config_path.exists():
            logger.warning(f"Risk config not found at {self.config_path}, using defaults")
            return self._default_config()
        
        try:
            with self.config_path.open() as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load risk config: {e}, using defaults")
            return self._default_config()

    def _default_config(self) -> Dict[str, Any]:
        """Return default risk configuration."""
        return {
            "global": {
                "trading_enabled": True,
                "safe_mode": False,
                "max_total_notional_usd": 1000.0,
                "max_open_positions": 3,
                "max_daily_loss_abs": 50.0,
                "max_daily_loss_pct": 0.05,
                "max_orders_per_minute": 30,
                "max_orders_per_symbol_per_minute": 10,
            },
            "venue_rules": {
                "OKX": {
                    "enabled": True,
                    "allowed_inst_types": ["SWAP"],
                    "allowed_inst_ids": ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
                    "max_order_notional_usd": 300.0,
                    "max_leverage": 3.0,
                    "allowed_td_modes": ["cross"],
                    "allowed_pos_sides": ["net"],
                }
            },
            "strategies": {
                "exploration": {
                    "enabled": True,
                    "max_notional_usd": 300.0,
                    "max_concurrent_positions": 2,
                    "allowed_venues": ["OKX"],
                    "max_leverage": 3.0,
                }
            },
        }

    def validate_order(
        self,
        intent: OrderIntent,
        exchange: Any,  # Exchange client (for getting price)
        price_usd: Optional[float] = None,
        leverage: Optional[int] = None,
    ) -> ValidatedOrder:
        """
        Validate an order intent and return a ValidatedOrder if valid.
        
        Raises ValueError if order is rejected.
        """
        global_cfg = self.config.get("global", {})
        
        # 1. Global trading enabled check
        if not global_cfg.get("trading_enabled", True):
            raise ValueError("Global trading is disabled")
        
        if global_cfg.get("safe_mode", False):
            raise ValueError("Safe mode is active - trading disabled")
        
        # 2. Venue enabled check
        venue_name = intent.venue.value
        venue_rules = self.config.get("venue_rules", {}).get(venue_name, {})
        
        if not venue_rules.get("enabled", False):
            raise ValueError(f"Venue {venue_name} is not enabled")
        
        # 3. Symbol allowed check
        # Bybit uses "allowed_symbols", OKX uses "allowed_inst_ids"
        allowed_symbols = venue_rules.get("allowed_symbols", [])
        allowed_inst_ids = venue_rules.get("allowed_inst_ids", [])
        allowed_list = allowed_symbols + allowed_inst_ids
        
        if intent.symbol not in allowed_list:
            raise ValueError(f"Symbol {intent.symbol} not allowed for venue {venue_name}")
        
        # 4. Strategy checks
        strategy_cfg = self.config.get("strategies", {}).get(intent.strategy_id, {})
        
        if not strategy_cfg.get("enabled", True):
            raise ValueError(f"Strategy {intent.strategy_id} is disabled")
        
        allowed_venues = strategy_cfg.get("allowed_venues", [])
        if venue_name not in allowed_venues:
            raise ValueError(f"Strategy {intent.strategy_id} not allowed on venue {venue_name}")
        
        # 5. Notional check
        # Estimate notional: quantity * price_usd (or use mark price from exchange)
        if price_usd is None:
            # Try to get mark price from exchange (stub for now)
            price_usd = 50000.0  # Fallback BTC price estimate
        
        notional_usd = float(intent.quantity) * price_usd
        
        # Check venue max notional
        venue_max_notional = venue_rules.get("max_order_notional_usd", float("inf"))
        if notional_usd > venue_max_notional:
            raise ValueError(
                f"Order notional ${notional_usd:.2f} exceeds venue max ${venue_max_notional:.2f}"
            )
        
        # Check strategy max notional
        strategy_max_notional = strategy_cfg.get("max_notional_usd", float("inf"))
        if notional_usd > strategy_max_notional:
            raise ValueError(
                f"Order notional ${notional_usd:.2f} exceeds strategy max ${strategy_max_notional:.2f}"
            )
        
        # Check global total notional (stub - would need to track open orders)
        global_max_notional = global_cfg.get("max_total_notional_usd", float("inf"))
        # TODO: Track total open notional across all positions
        # For now, just check per-order
        
        # 6. Position count check
        positions = self.position_provider()
        open_count = len([p for p in positions if p.get("symbol") == intent.symbol])
        strategy_max_positions = strategy_cfg.get("max_concurrent_positions", float("inf"))
        
        if open_count >= strategy_max_positions:
            raise ValueError(
                f"Max concurrent positions ({strategy_max_positions}) reached for strategy {intent.strategy_id}"
            )
        
        global_max_positions = global_cfg.get("max_open_positions", float("inf"))
        total_positions = len(positions)
        if total_positions >= global_max_positions:
            raise ValueError(
                f"Global max open positions ({global_max_positions}) reached"
            )
        
        # 7. Daily loss check
        pnl = self.pnl_provider()
        daily_loss_abs = pnl.get("daily_loss_abs", 0.0)
        daily_loss_pct = pnl.get("daily_loss_pct", 0.0)
        
        max_daily_loss_abs = global_cfg.get("max_daily_loss_abs", float("inf"))
        if daily_loss_abs > max_daily_loss_abs:
            raise ValueError(
                f"Daily loss ${daily_loss_abs:.2f} exceeds max ${max_daily_loss_abs:.2f}"
            )
        
        max_daily_loss_pct = global_cfg.get("max_daily_loss_pct", float("inf"))
        if daily_loss_pct > max_daily_loss_pct:
            raise ValueError(
                f"Daily loss {daily_loss_pct:.2%} exceeds max {max_daily_loss_pct:.2%}"
            )
        
        # 8. Rate limiting
        self._cleanup_old_timestamps()
        
        max_orders_per_minute = global_cfg.get("max_orders_per_minute", 30)
        if len(self._order_timestamps) >= max_orders_per_minute:
            raise ValueError(f"Rate limit exceeded: {max_orders_per_minute} orders per minute")
        
        max_orders_per_symbol_per_minute = global_cfg.get("max_orders_per_symbol_per_minute", 10)
        symbol_timestamps = self._symbol_order_timestamps[intent.symbol]
        if len(symbol_timestamps) >= max_orders_per_symbol_per_minute:
            raise ValueError(
                f"Rate limit exceeded for {intent.symbol}: {max_orders_per_symbol_per_minute} orders per minute"
            )
        
        # Record this order timestamp
        now = datetime.now(timezone.utc).timestamp()
        self._order_timestamps.append(now)
        self._symbol_order_timestamps[intent.symbol].append(now)
        
        # 9. Leverage check
        if leverage is not None:
            venue_max_leverage = venue_rules.get("max_leverage", float("inf"))
            if leverage > venue_max_leverage:
                raise ValueError(
                    f"Leverage {leverage}x exceeds venue max {venue_max_leverage}x"
                )
            
            strategy_max_leverage = strategy_cfg.get("max_leverage", float("inf"))
            if leverage > strategy_max_leverage:
                raise ValueError(
                    f"Leverage {leverage}x exceeds strategy max {strategy_max_leverage}x"
                )
        
        # 10. TD mode check
        allowed_td_modes = venue_rules.get("allowed_td_modes", ["cross"])
        # Default to cross for SWAP contracts
        td_mode = TdMode.CROSS
        if td_mode.value not in allowed_td_modes:
            raise ValueError(f"TD mode {td_mode.value} not allowed for venue {venue_name}")
        
        # All checks passed - create ValidatedOrder
        validated = ValidatedOrder(
            venue=intent.venue,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            price=intent.price,
            order_type=intent.order_type,
            td_mode=td_mode,
            strategy_id=intent.strategy_id,
            reduce_only=intent.reduce_only,
            exchange_specific={},
        )
        
        logger.info(
            f"Order validated: {intent.strategy_id} {intent.side.value} {intent.quantity} {intent.symbol}"
        )
        
        return validated

    def _cleanup_old_timestamps(self):
        """Remove timestamps older than 60 seconds."""
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - 60.0
        
        # Clean global timestamps
        self._order_timestamps = [ts for ts in self._order_timestamps if ts > cutoff]
        
        # Clean per-symbol timestamps
        for symbol in list(self._symbol_order_timestamps.keys()):
            self._symbol_order_timestamps[symbol] = [
                ts for ts in self._symbol_order_timestamps[symbol] if ts > cutoff
            ]
            if not self._symbol_order_timestamps[symbol]:
                del self._symbol_order_timestamps[symbol]

