"""
Paper wallet adapter - Phase 1
Simulated wallet with fixed equity, no real funds.
"""

from typing import Dict, Any
from engine_alpha.wallets.base import WalletAdapter, WalletSnapshot


class PaperWalletAdapter(WalletAdapter):
    """
    Paper trading wallet adapter.
    
    Returns a fixed $10,000 equity snapshot and simulates orders
    without any real exchange interaction.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Default equity for paper wallets
        self._default_equity = float(config.get("equity", 10_000.0))
        self._base_ccy = config.get("base_ccy", "USDT")
    
    def snapshot(self) -> WalletSnapshot:
        """
        Return paper wallet snapshot with fixed equity.
        
        Note: In a real implementation, this would read from a paper trading
        ledger or equity tracking file. For now, we return a fixed value.
        """
        return WalletSnapshot(
            id=self.id,
            label=self.label,
            kind="paper",
            equity=self._default_equity,
            base_ccy=self._base_ccy,
            positions={},  # Paper wallets start with no open positions
        )
    
    def simulate_order(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        """
        Simulate an order without executing it.
        
        Returns a simulated fill result that shows what would happen
        if the order were executed, but makes no API calls.
        """
        return {
            "status": "simulated",
            "symbol": symbol,
            "side": side.lower(),
            "qty": float(qty),
            "fills": [
                {
                    "price": 0.0,  # Would be filled at current market price in real implementation
                    "qty": float(qty),
                    "fee": 0.0,
                }
            ],
            "note": f"Paper wallet simulation - no real funds affected",
        }



