"""
Execution Quality Analyzer - Microstructure-aware execution performance analysis.

Measures how well execution performs in different microstructure regimes by analyzing
realized trades against microstructure snapshots. All outputs are advisory-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from collections import defaultdict

from engine_alpha.core.paths import REPORTS

RESEARCH_DIR = REPORTS / "research"
TRADES_PATH = REPORTS / "trades.jsonl"
EXECUTION_QUALITY_PATH = RESEARCH_DIR / "execution_quality.json"


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file, return empty list if missing or invalid."""
    if not path.exists():
        return []
    trades = []
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return trades


def _find_micro_regime_for_trade(
    trade: Dict[str, Any],
    microstructure_snapshot: Dict[str, Any],
    timeframe: str = "15m"
) -> Optional[str]:
    """
    Find the micro_regime for a trade by matching its timestamp to microstructure data.
    
    Args:
        trade: Trade dict with ts or timestamp field
        microstructure_snapshot: Microstructure snapshot dict
        timeframe: Timeframe (default: "15m")
    
    Returns:
        micro_regime string or None if not found
    """
    # Get trade timestamp
    trade_ts = trade.get("ts") or trade.get("timestamp")
    if not trade_ts:
        return None
    
    # Get symbol
    symbol = trade.get("symbol")
    if not symbol:
        return None
    
    # Handle versioned format: {"version": "...", "symbols": {...}}
    # or legacy format: {symbol: {...}}
    if "symbols" in microstructure_snapshot:
        symbols_data = microstructure_snapshot.get("symbols", {})
    else:
        symbols_data = microstructure_snapshot  # legacy shape
    
    symbol_data = symbols_data.get(symbol, {})
    
    # If symbol_data is a dict with micro_regime (summary format), use it
    if isinstance(symbol_data, dict) and "micro_regime" in symbol_data:
        return symbol_data.get("micro_regime")
    
    # Otherwise, try to match timestamp to bar-level features
    # (This would require bar-level timestamp matching, which is more complex)
    # For now, use the summary micro_regime if available
    return None


def analyze_execution_quality(
    trades_path: Path = TRADES_PATH,
    microstructure_path: Path = RESEARCH_DIR / "microstructure_snapshot_15m.json",
    timeframe: str = "15m"
) -> Dict[str, Any]:
    """
    Analyze execution quality per symbol and micro_regime.
    
    Args:
        trades_path: Path to trades.jsonl
        microstructure_path: Path to microstructure snapshot
        timeframe: Timeframe (default: "15m")
    
    Returns:
        Dict of the form:
        {
            "ETHUSDT": {
                "clean_trend": {
                    "trades": 10,
                    "avg_pct": 0.008,
                    "win_rate": 0.7,
                    "big_win": 3,
                    "big_loss": 1,
                    "label": "friendly"
                },
                "noisy": { ... }
            },
            ...
        }
    """
    # Load trades
    trades = load_jsonl(trades_path)
    
    # Load microstructure snapshot
    microstructure_snapshot = load_json(microstructure_path)
    
    if not trades:
        return {}
    
    if not microstructure_snapshot:
        return {}
    
    # Group trades by (symbol, micro_regime)
    trades_by_symbol_regime: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    
    # Process closed trades
    for trade in trades:
        # Only analyze closed trades
        event_type = trade.get("type") or trade.get("event", "").lower()
        if event_type != "close":
            continue
        
        symbol = trade.get("symbol")
        if not symbol:
            continue
        
        # Get pct
        pct = trade.get("pct")
        if pct is None:
            continue
        
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            continue
        
        # Find micro_regime for this trade
        micro_regime = _find_micro_regime_for_trade(trade, microstructure_snapshot, timeframe)
        
        # If we can't determine micro_regime, try to use symbol's dominant regime
        if not micro_regime:
            # Handle versioned format
            if "symbols" in microstructure_snapshot:
                symbols_data = microstructure_snapshot.get("symbols", {})
            else:
                symbols_data = microstructure_snapshot  # legacy shape
            symbol_data = symbols_data.get(symbol, {})
            if isinstance(symbol_data, dict):
                micro_regime = symbol_data.get("micro_regime", "unknown")
            else:
                micro_regime = "unknown"
        
        trades_by_symbol_regime[symbol][micro_regime].append({
            "pct": pct,
            "ts": trade.get("ts") or trade.get("timestamp"),
        })
    
    # Compute metrics per (symbol, micro_regime)
    result: Dict[str, Dict[str, Any]] = {}
    
    for symbol, regimes_dict in trades_by_symbol_regime.items():
        result[symbol] = {}
        
        for micro_regime, regime_trades in regimes_dict.items():
            if not regime_trades:
                continue
            
            pct_values = [t["pct"] for t in regime_trades]
            
            # Compute metrics
            trades_count = len(pct_values)
            avg_pct = sum(pct_values) / trades_count if trades_count > 0 else 0.0
            
            wins = [p for p in pct_values if p > 0]
            losses = [p for p in pct_values if p < 0]
            win_rate = len(wins) / trades_count if trades_count > 0 else 0.0
            
            big_wins = sum(1 for p in pct_values if p >= 0.01)  # >= 1%
            big_losses = sum(1 for p in pct_values if p <= -0.01)  # <= -1%
            
            # Derive label
            label = "neutral"
            if avg_pct > 0 and win_rate > 0.55:
                label = "friendly"
            elif avg_pct < 0 or big_losses > big_wins:
                label = "hostile"
            
            result[symbol][micro_regime] = {
                "trades": trades_count,
                "avg_pct": round(avg_pct, 6),
                "win_rate": round(win_rate, 4),
                "big_win_count": big_wins,  # v2: renamed for clarity
                "big_loss_count": big_losses,  # v2: renamed for clarity
                "label": label,
            }
    
    # v2: Add overall summary per symbol
    for symbol in result.keys():
        symbol_data = result[symbol]
        friendly_regimes = []
        hostile_regimes = []
        
        for regime, regime_data in symbol_data.items():
            label = regime_data.get("label", "neutral")
            if label == "friendly":
                friendly_regimes.append(regime)
            elif label == "hostile":
                hostile_regimes.append(regime)
        
        # Determine overall label
        overall_label = "neutral"
        if len(friendly_regimes) > len(hostile_regimes):
            overall_label = "friendly"
        elif len(hostile_regimes) > len(friendly_regimes):
            overall_label = "hostile"
        
        # Add summary to symbol data
        result[symbol]["summary"] = {
            "friendly_regimes": friendly_regimes,
            "hostile_regimes": hostile_regimes,
            "overall_label": overall_label,
        }
    
    return result


def load_execution_quality(
    path: Path = EXECUTION_QUALITY_PATH
) -> Dict[str, Any]:
    """
    Load execution quality report from disk.
    
    Args:
        path: Path to execution_quality.json
    
    Returns:
        Dict with execution quality data, or empty dict if not found
    """
    return load_json(path)


def save_execution_quality(
    quality_data: Dict[str, Any],
    path: Path = EXECUTION_QUALITY_PATH
) -> Path:
    """
    Save execution quality report to disk.
    
    Args:
        quality_data: Execution quality data dict
        path: Path to save to
    
    Returns:
        Path to saved file
    """
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    
    # Add metadata
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": quality_data,
    }
    
    path.write_text(json.dumps(output, indent=2))
    return path

