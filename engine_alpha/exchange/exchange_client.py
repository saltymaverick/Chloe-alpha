"""
Exchange Client - Central accessor for paper/real exchange clients

Chooses paper or real based on wallet_config.
"""

from __future__ import annotations

from typing import Any, Dict

from engine_alpha.config.config_loader import load_wallet_config, load_real_exchange_keys


def create_paper_client() -> Any:
    """
    Create paper trading client.
    
    Stub: replace with your real paper client implementation.
    e.g. connects to a local simulator or testnet.
    """
    # TODO: Implement actual paper client
    # from engine_alpha.exchange.paper_client import PaperClient
    # return PaperClient()
    
    # For now, return None (paper trading handled elsewhere)
    return None


def create_real_client(venue: str, creds: Dict[str, str]) -> Any:
    """
    Create real exchange client for given venue.
    
    Args:
        venue: Exchange name (bybit, binance, okx)
        creds: Credentials dict with api_key, api_secret, optionally passphrase
    
    Returns:
        Exchange client instance
    """
    venue_l = venue.lower()
    
    if venue_l == "bybit":
        # TODO: Implement actual Bybit client
        # from engine_alpha.exchange.bybit_client import BybitClient
        # return BybitClient(
        #     api_key=creds.get("api_key", ""),
        #     api_secret=creds.get("api_secret", ""),
        # )
        raise NotImplementedError("Bybit client not yet implemented")
    
    elif venue_l == "binance":
        # TODO: Implement actual Binance client
        # from engine_alpha.exchange.binance_client import BinanceClient
        # return BinanceClient(
        #     api_key=creds.get("api_key", ""),
        #     api_secret=creds.get("api_secret", ""),
        # )
        raise NotImplementedError("Binance client not yet implemented")
    
    elif venue_l == "okx":
        # TODO: Implement actual OKX client
        # from engine_alpha.exchange.okx_client import OkxClient
        # return OkxClient(
        #     api_key=creds.get("api_key", ""),
        #     api_secret=creds.get("api_secret", ""),
        #     passphrase=creds.get("passphrase", ""),
        # )
        raise NotImplementedError("OKX client not yet implemented")
    
    else:
        raise ValueError(f"Unsupported real exchange venue: {venue}")


def get_active_exchange_client() -> Any:
    """
    Central accessor used by trading code.
    
    Chooses paper or real based on wallet_config.
    
    Returns:
        Exchange client instance (paper or real)
    """
    wallet_cfg = load_wallet_config()
    
    if wallet_cfg.active_wallet_mode == "paper":
        return create_paper_client()
    
    # active_wallet_mode == "real"
    keys = load_real_exchange_keys()
    creds = keys.get(wallet_cfg.real_exchange)
    
    if not creds or not creds.get("api_key"):
        raise RuntimeError(
            f"No real credentials configured for {wallet_cfg.real_exchange}. "
            f"Set {wallet_cfg.real_exchange.upper()}_API_KEY and "
            f"{wallet_cfg.real_exchange.upper()}_API_SECRET environment variables."
        )
    
    return create_real_client(wallet_cfg.real_exchange, creds)


