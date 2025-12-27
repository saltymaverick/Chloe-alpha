"""
Correlation Engine - Phase 5
Computes correlation matrix between symbol returns.

Aligns returns by timestamp and computes Pearson correlation
between all symbol pairs for diversification analysis.
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
CORRELATION_MATRIX_PATH = RESEARCH_DIR / "correlation_matrix.json"


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


def _compute_correlation(x: List[float], y: List[float]) -> Optional[float]:
    """
    Compute Pearson correlation coefficient.
    
    Returns:
        Correlation coefficient in [-1, 1] or None if insufficient data
    """
    if len(x) != len(y) or len(x) < 2:
        return None
    
    n = len(x)
    
    # Compute means
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    # Compute covariance and variances
    covariance = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    var_x = sum((x[i] - mean_x) ** 2 for i in range(n))
    var_y = sum((y[i] - mean_y) ** 2 for i in range(n))
    
    # Compute correlation
    denominator = (var_x * var_y) ** 0.5
    if denominator == 0:
        return None
    
    correlation = covariance / denominator
    return max(-1.0, min(1.0, correlation))  # Clamp to [-1, 1]


def compute_correlation_matrix() -> Dict[str, Any]:
    """
    Compute correlation matrix for all symbol pairs.
    
    Returns:
        Dict with correlation matrix and metadata
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
    
    # Get all symbols
    symbols = sorted(symbol_returns.keys())
    
    if len(symbols) < 2:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbols": [],
            "matrix": {},
            "notes": ["Insufficient symbols for correlation analysis"],
        }
    
    # Build aligned return series by timestamp
    # For each timestamp, collect returns from all symbols
    timestamp_returns: Dict[str, Dict[str, float]] = defaultdict(dict)
    
    for symbol in symbols:
        for ts, pct in symbol_returns[symbol]:
            timestamp_returns[ts][symbol] = pct
    
    # Find common timestamps (where at least 2 symbols have data)
    common_timestamps = [
        ts for ts, returns in timestamp_returns.items()
        if len(returns) >= 2
    ]
    
    if len(common_timestamps) < 2:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbols": symbols,
            "matrix": {},
            "notes": ["Insufficient overlapping timestamps for correlation"],
        }
    
    # Build correlation matrix
    matrix: Dict[str, Dict[str, float]] = {}
    
    for i, sym1 in enumerate(symbols):
        matrix[sym1] = {}
        for sym2 in symbols:
            if sym1 == sym2:
                matrix[sym1][sym2] = 1.0
            elif sym2 in matrix and sym1 in matrix[sym2]:
                # Use symmetry: corr(A, B) = corr(B, A)
                matrix[sym1][sym2] = matrix[sym2][sym1]
            else:
                # Extract aligned return series
                x = []
                y = []
                for ts in common_timestamps:
                    if sym1 in timestamp_returns[ts] and sym2 in timestamp_returns[ts]:
                        x.append(timestamp_returns[ts][sym1])
                        y.append(timestamp_returns[ts][sym2])
                
                corr = _compute_correlation(x, y)
                matrix[sym1][sym2] = corr if corr is not None else 0.0
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "matrix": matrix,
        "common_timestamps_count": len(common_timestamps),
    }
    
    # Write report
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    CORRELATION_MATRIX_PATH.write_text(json.dumps(report, indent=2))
    
    return report

