"""
Wallet abstraction layer - Phase 1
Provides unified interface for paper, CEX, and EVM wallets.
All adapters are read-only / simulated until explicitly enabled.
"""

from engine_alpha.wallets.base import WalletSnapshot, WalletAdapter
from engine_alpha.wallets.registry import load_wallets

__all__ = ["WalletSnapshot", "WalletAdapter", "load_wallets"]



