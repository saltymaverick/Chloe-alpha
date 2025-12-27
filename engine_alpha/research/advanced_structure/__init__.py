"""
Advanced Structure Engine (ASE) - Multi-Timeframe Market Structure Analysis

Provides three core engines:
- Liquidity Sweeps: Detects HTF pool sweeps and breaker blocks
- Volume Imbalance: Computes delta, absorption, and exhaustion signals
- Market Structure: Analyzes swing structure, order blocks, FVGs, and sessions

All outputs are advisory-only and research-oriented.
"""

from engine_alpha.research.advanced_structure.liquidity_sweeps import compute_liquidity_sweeps
from engine_alpha.research.advanced_structure.volume_imbalance import compute_volume_imbalance
from engine_alpha.research.advanced_structure.market_structure import compute_market_structure

__all__ = [
    "compute_liquidity_sweeps",
    "compute_volume_imbalance",
    "compute_market_structure",
]

