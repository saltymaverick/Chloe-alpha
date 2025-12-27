"""
EVM wallet stub adapter - Phase 1
Placeholder for future EVM (Ethereum, L2s) wallet integration.
All methods return stub responses - no real blockchain calls.
"""

from typing import Dict, Any
from engine_alpha.wallets.base import WalletAdapter, WalletSnapshot


class EvmWalletStubAdapter(WalletAdapter):
    """
    Stub adapter for EVM wallets.
    
    This is a placeholder that returns empty/zero values.
    When real EVM integration is implemented, this will be replaced
    with actual blockchain RPC calls (behind explicit opt-in flags).
    """
    
    def snapshot(self) -> WalletSnapshot:
        """
        Return stub snapshot - zero equity, no positions.
        
        In real implementation, this would query blockchain for:
        - Token balances (USDC, ETH, etc.)
        - Pending transactions
        - DeFi positions (if applicable)
        """
        return WalletSnapshot(
            id=self.id,
            label=self.label,
            kind="evm_stub",
            equity=0.0,
            base_ccy=self.config.get("base_ccy", "USDT"),
            positions={},
        )
    
    def simulate_order(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        """
        Return stub order simulation.
        
        In real implementation, this would:
        1. Check wallet balance
        2. Estimate gas costs
        3. Simulate DEX swap or order placement
        4. Return simulation result
        """
        return {
            "status": "stub",
            "symbol": symbol,
            "side": side.lower(),
            "qty": float(qty),
            "fills": [],
            "note": "EVM adapter not implemented yet; dry run only. No real blockchain calls made.",
        }



