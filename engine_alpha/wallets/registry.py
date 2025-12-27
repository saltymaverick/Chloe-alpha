"""
Wallet registry loader - Phase 1
Loads wallet configurations from wallet_registry.json and instantiates adapters.
"""

import json
from pathlib import Path
from typing import Dict, Optional

from engine_alpha.wallets.base import WalletAdapter
from engine_alpha.wallets.paper_wallet import PaperWalletAdapter
from engine_alpha.wallets.cex_stub import CexWalletStubAdapter
from engine_alpha.wallets.evm_stub import EvmWalletStubAdapter


# Registry of available wallet adapter classes
ADAPTERS: Dict[str, type] = {
    "paper": PaperWalletAdapter,
    "cex_stub": CexWalletStubAdapter,
    "evm_stub": EvmWalletStubAdapter,
    # Future adapters:
    # "cex": CexWalletAdapter,  # When real CEX integration is implemented
    # "evm": EvmWalletAdapter,   # When real EVM integration is implemented
}


def load_wallets(registry_path: Path) -> Dict[str, WalletAdapter]:
    """
    Load wallets from registry file and instantiate adapters.
    
    Args:
        registry_path: Path to wallet_registry.json file
    
    Returns:
        Dict mapping wallet ID to WalletAdapter instance
    
    Raises:
        FileNotFoundError: If registry_path doesn't exist
        json.JSONDecodeError: If registry file is invalid JSON
    """
    if not registry_path.exists():
        return {}
    
    try:
        data = json.loads(registry_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in wallet registry: {e}")
    
    if not isinstance(data, list):
        raise ValueError("wallet_registry.json must contain a JSON array")
    
    wallets: Dict[str, WalletAdapter] = {}
    
    for entry in data:
        if not isinstance(entry, dict):
            continue
        
        wallet_id = entry.get("id")
        if not wallet_id:
            continue
        
        kind = entry.get("kind", "paper")
        adapter_cls = ADAPTERS.get(kind)
        
        if not adapter_cls:
            # Skip unknown wallet kinds (allows registry to have future entries)
            continue
        
        try:
            wallets[wallet_id] = adapter_cls(entry)
        except Exception as e:
            # Log error but continue loading other wallets
            print(f"Warning: Failed to load wallet {wallet_id} (kind={kind}): {e}")
            continue
    
    return wallets


def get_wallet(wallet_id: str, registry_path: Path) -> Optional[WalletAdapter]:
    """
    Get a single wallet by ID.
    
    Args:
        wallet_id: Wallet ID to look up
        registry_path: Path to wallet_registry.json
    
    Returns:
        WalletAdapter instance if found, None otherwise
    """
    wallets = load_wallets(registry_path)
    return wallets.get(wallet_id)



