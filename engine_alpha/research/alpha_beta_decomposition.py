"""
Alpha/Beta Decomposition - Phase 5
Decomposes symbol returns into alpha (idiosyncratic) and beta (market-driven) components.

Uses BTCUSDT as the market benchmark and computes linear regression:
pct_symbol ~ alpha + beta * pct_btc
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from collections import defaultdict

from engine_alpha.core.paths import REPORTS

TRADES_PATH = REPORTS / "trades.jsonl"
RESEARCH_DIR = REPORTS / "research"
ALPHA_BETA_PATH = RESEARCH_DIR / "alpha_beta.json"

BENCHMARK_SYMBOL = "BTCUSDT"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read JSONL file, return empty list if missing or invalid."""
    if not path.exists():
        return []
    entries = []
    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return entries


def _linear_regression(x: List[float], y: List[float]) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute linear regression: y = alpha + beta * x
    
    Returns:
        Tuple of (alpha, beta) or (None, None) if insufficient data
    """
    if len(x) != len(y) or len(x) < 2:
        return None, None
    
    n = len(x)
    
    # Compute means
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    # Compute beta (slope)
    numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    denominator = sum((x[i] - mean_x) ** 2 for i in range(n))
    
    if denominator == 0:
        return None, None
    
    beta = numerator / denominator
    
    # Compute alpha (intercept)
    alpha = mean_y - beta * mean_x
    
    return alpha, beta


def compute_alpha_beta() -> Dict[str, Any]:
    """
    Compute alpha/beta decomposition for all symbols vs BTCUSDT benchmark.
    
    Returns:
        Dict with per-symbol alpha and beta
    """
    trades = _read_jsonl(TRADES_PATH)
    
    # Build time series: symbol -> list of (timestamp, pct) tuples
    symbol_returns: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    
    for trade in trades:
        if trade.get("type") != "close":
            continue
        if trade.get("trade_kind") != "exploration":
            continue
        
        symbol = trade.get("symbol")
        ts = trade.get("ts") or trade.get("time")
        try:
            pct = float(trade.get("pct", 0.0))
        except (ValueError, TypeError):
            continue
        
        if symbol and ts:
            symbol_returns[symbol].append((ts, pct))
    
    # Get benchmark returns (BTCUSDT)
    benchmark_returns = symbol_returns.get(BENCHMARK_SYMBOL, [])
    
    if not benchmark_returns:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "benchmark": BENCHMARK_SYMBOL,
            "symbols": {},
            "notes": [f"Benchmark symbol {BENCHMARK_SYMBOL} has no trades"],
        }
    
    # Build aligned return series
    timestamp_returns: Dict[str, Dict[str, float]] = defaultdict(dict)
    
    for symbol in symbol_returns.keys():
        for ts, pct in symbol_returns[symbol]:
            timestamp_returns[ts][symbol] = pct
    
    # Find timestamps where benchmark has data
    benchmark_timestamps = {ts for ts, pct in benchmark_returns}
    
    # Compute alpha/beta for each symbol
    alpha_beta_data: Dict[str, Dict[str, Any]] = {}
    
    for symbol in sorted(symbol_returns.keys()):
        if symbol == BENCHMARK_SYMBOL:
            # Benchmark has beta=1, alpha=0 by definition
            alpha_beta_data[symbol] = {
                "alpha": 0.0,
                "beta": 1.0,
                "sample_size": len(benchmark_returns),
            }
            continue
        
        # Extract aligned returns
        x = []  # Benchmark returns
        y = []  # Symbol returns
        
        for ts in benchmark_timestamps:
            if ts in timestamp_returns:
                if BENCHMARK_SYMBOL in timestamp_returns[ts] and symbol in timestamp_returns[ts]:
                    x.append(timestamp_returns[ts][BENCHMARK_SYMBOL])
                    y.append(timestamp_returns[ts][symbol])
        
        if len(x) < 2:
            alpha_beta_data[symbol] = {
                "alpha": None,
                "beta": None,
                "sample_size": len(x),
                "notes": "Insufficient overlapping data",
            }
            continue
        
        alpha, beta = _linear_regression(x, y)
        
        alpha_beta_data[symbol] = {
            "alpha": alpha,
            "beta": beta,
            "sample_size": len(x),
        }
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": BENCHMARK_SYMBOL,
        "symbols": alpha_beta_data,
    }
    
    # Write report
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    ALPHA_BETA_PATH.write_text(json.dumps(report, indent=2))
    
    return report

