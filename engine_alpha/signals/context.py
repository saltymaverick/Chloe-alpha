"""
SignalContext - Standardized context object for all signal modules.

This is the canonical data contract for Flow, Volatility, Microstructure, and Cross-Asset signals.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List

try:
    import pandas as pd
except ImportError:
    pd = None  # pandas optional, but recommended


@dataclass
class SignalContext:
    """
    Standardized context object for signal computation.
    
    All signal modules (Flow, Volatility, Microstructure, Cross-Asset) should
    accept a SignalContext as their primary input.
    
    Attributes:
        symbol: Trading symbol (e.g. "ETHUSDT")
        timeframe: Timeframe (e.g. "1h")
        ohlcv: DataFrame with columns ["open", "high", "low", "close", "volume"]
               or list of dicts with those keys. Required.
        onchain: Optional on-chain/flow aggregates (e.g. exchange_reserves, whale_inflows)
        derivatives: Optional derivatives data (funding_rate, open_interest, basis, etc.)
        microstructure: Optional orderbook/microstructure info (bid_ask_imbalance, etc.)
        cross_asset: Optional cross-asset snapshot keyed by symbol
        meta: Optional metadata (timestamp, regime hints, etc.)
    """
    symbol: str
    timeframe: str
    ohlcv: Any  # pd.DataFrame or List[Dict[str, Any]]
    
    # Optional: on-chain / flow aggregates
    onchain: Optional[Dict[str, Any]] = None
    
    # Optional: derivatives data (perps, funding, OI, basis, etc.)
    derivatives: Optional[Dict[str, Any]] = None
    
    # Optional: orderbook / microstructure info
    microstructure: Optional[Dict[str, Any]] = None
    
    # Optional: cross-asset snapshot keyed by symbol
    cross_asset: Optional[Dict[str, Dict[str, Any]]] = None
    
    # Misc metadata
    meta: Optional[Dict[str, Any]] = None
    
    def get_ohlcv_rows(self) -> List[Dict[str, Any]]:
        """
        Convert ohlcv to a list of dicts (rows) for backward compatibility.
        
        Returns:
            List of dicts with keys: ["ts", "open", "high", "low", "close", "volume"]
        """
        if isinstance(self.ohlcv, list):
            return self.ohlcv
        elif pd is not None and isinstance(self.ohlcv, pd.DataFrame):
            # Convert DataFrame to list of dicts
            df = self.ohlcv.copy()
            if "ts" not in df.columns and df.index.name == "ts":
                df = df.reset_index()
            return df.to_dict("records")
        else:
            # Fallback: try to treat as iterable
            try:
                return list(self.ohlcv)
            except Exception:
                return []

