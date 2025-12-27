"""
CEX wallet stub adapter - Phase 1
Placeholder for future CEX (Binance, Bybit, etc.) integration.
All methods return stub responses - no real API calls.
"""

from typing import Dict, Any
from engine_alpha.wallets.base import WalletAdapter, WalletSnapshot


class CexWalletStubAdapter(WalletAdapter):
    """
    Stub adapter for CEX wallets.
    
    This is a placeholder that returns empty/zero values.
    When real CEX integration is implemented, this will be replaced
    with actual API calls (behind explicit opt-in flags).
    """
    
    def snapshot(self) -> WalletSnapshot:
        """
        Return stub snapshot - zero equity, no positions.
        
        In real implementation, this would query exchange API for:
        - Account balance
        - Open orders
        - Open positions
        """
        return WalletSnapshot(
            id=self.id,
            label=self.label,
            kind="cex_stub",
            equity=0.0,
            base_ccy=self.config.get("base_ccy", "USDT"),
            positions={},
        )
    
    def simulate_order(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        """
        Return stub order simulation.
        
        In real implementation, this would:
        1. Check order would be valid (balance, limits, etc.)
        2. Calculate estimated fill price
        3. Return simulation result
        """
        return {
            "status": "stub",
            "symbol": symbol,
            "side": side.lower(),
            "qty": float(qty),
            "fills": [],
            "note": "CEX adapter not implemented yet; dry run only. No real API calls made.",
        }



