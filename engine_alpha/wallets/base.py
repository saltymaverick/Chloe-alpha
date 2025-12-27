"""
Base wallet adapter interface - Phase 1
Defines the abstract interface that all wallet types must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class WalletSnapshot:
    """
    Snapshot of wallet state at a point in time.
    All values are read-only representations.
    """
    id: str
    label: str
    kind: str  # "paper" | "cex" | "evm" | "cex_stub" | "evm_stub"
    equity: float  # Total equity in base currency
    base_ccy: str  # Base currency (e.g., "USDT", "USD")
    positions: Dict[str, Any]  # Open positions, e.g. {"ETHUSDT": {"qty": 1.0, "entry_px": 3000.0}}
    
    def __repr__(self) -> str:
        return (
            f"WalletSnapshot(id={self.id!r}, label={self.label!r}, "
            f"kind={self.kind!r}, equity={self.equity:.2f} {self.base_ccy}, "
            f"positions={len(self.positions)} symbols)"
        )


class WalletAdapter(ABC):
    """
    Abstract base class for all wallet adapters.
    
    All adapters must implement:
    - snapshot(): Returns current wallet state
    - simulate_order(): Dry-run order simulation (never hits real exchange)
    
    This interface is designed to be safe and read-only by default.
    Real trading functionality will be added later as explicit opt-in.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize adapter with configuration from wallet_registry.json.
        
        Args:
            config: Wallet configuration dict with id, label, kind, etc.
        """
        self.config = config
        self.id = config.get("id", "unknown")
        self.label = config.get("label", "Unnamed Wallet")
        self.kind = config.get("kind", "paper")
    
    @abstractmethod
    def snapshot(self) -> WalletSnapshot:
        """
        Get current wallet state snapshot.
        
        Returns:
            WalletSnapshot with current equity, positions, etc.
        """
        pass
    
    @abstractmethod
    def simulate_order(self, symbol: str, side: str, qty: float) -> Dict[str, Any]:
        """
        Dry-run order simulation - returns what *would* happen, but never hits an exchange.
        
        This is safe to call at any time. It performs calculations but makes no API calls.
        
        Args:
            symbol: Trading pair (e.g., "ETHUSDT")
            side: "buy" or "sell"
            qty: Quantity to trade
        
        Returns:
            Dict with simulated order result:
            {
                "status": "simulated" | "stub" | ...,
                "symbol": str,
                "side": str,
                "qty": float,
                "fills": List[Dict],  # Simulated fills
                "note": Optional[str]  # Optional note about simulation
            }
        """
        pass



