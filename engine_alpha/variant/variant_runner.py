"""
Strategy Variant Runner - Execute mutation strategies in parallel.

This module allows Chloe to run multiple strategy variants simultaneously,
testing mutations safely without affecting the main trading loop.

All execution is paper-only, isolated, and non-invasive.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.signals.signal_processor import get_signal_vector
from engine_alpha.core.confidence_engine import decide
from engine_alpha.core.regime import classify_regime
from engine_alpha.data.live_prices import get_live_ohlcv

ROOT = Path(__file__).resolve().parents[2]
MUTATION_STRATEGIES_PATH = REPORTS / "evolver" / "mutation_strategies.jsonl"
VARIANT_DIR = REPORTS / "variant"
VARIANT_DIR.mkdir(parents=True, exist_ok=True)


def load_active_variants() -> List[Dict[str, Any]]:
    """
    Load all active variant strategies from mutation_strategies.jsonl.
    
    Returns:
        List of variant strategy dicts with status="shadow"
    """
    if not MUTATION_STRATEGIES_PATH.exists():
        return []
    
    variants = []
    try:
        with MUTATION_STRATEGIES_PATH.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    variant = json.loads(line)
                    # Only load shadow variants (not promoted ones)
                    if variant.get("status") == "shadow":
                        variants.append(variant)
                except Exception:
                    continue
    except Exception:
        pass
    
    return variants


def initialize_variant_states(variants: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Initialize state for each variant.
    
    Args:
        variants: List of variant strategy dicts
    
    Returns:
        Dict mapping variant_id -> variant state
    """
    states: Dict[str, Dict[str, Any]] = {}
    
    for variant in variants:
        variant_id = variant["id"]
        symbol = variant["symbol"]
        
        # Load existing state if available
        summary_path = VARIANT_DIR / f"{variant_id}_summary.json"
        existing_state = {}
        if summary_path.exists():
            try:
                existing_state = json.loads(summary_path.read_text())
            except Exception:
                pass
        
        states[variant_id] = {
            "id": variant_id,
            "symbol": symbol,
            "mutations": variant.get("mutations", {}),
            "position": existing_state.get("position", {"dir": 0, "entry_px": None, "bars_open": 0}),
            "stats": existing_state.get("stats", {
                "exp_trades": 0,
                "exp_pf": None,
                "norm_trades": 0,
                "norm_pf": None,
                "total_pnl": 0.0,
                "wins": 0,
                "losses": 0,
            }),
            "trades": existing_state.get("trades", []),
        }
    
    return states


def _load_base_thresholds() -> Dict[str, float]:
    """Load base entry thresholds from gates.yaml."""
    try:
        gates_path = CONFIG / "gates.yaml"
        if gates_path.exists():
            import yaml
            data = yaml.safe_load(gates_path.read_text())
            entry_min_conf = data.get("entry_exit", {}).get("entry_min_conf", {})
            return {
                "trend": float(entry_min_conf.get("trend", 0.70)),
                "chop": float(entry_min_conf.get("chop", 0.72)),
                "high_vol": float(entry_min_conf.get("high_vol", 0.71)),
            }
    except Exception:
        pass
    
    # Fallback defaults
    return {
        "trend": 0.70,
        "chop": 0.72,
        "high_vol": 0.71,
    }


def _apply_mutations(base_thresholds: Dict[str, float], mutations: Dict[str, Any], regime: str) -> float:
    """
    Apply mutations to base thresholds for a given regime.
    
    Args:
        base_thresholds: Base thresholds per regime
        mutations: Mutation dict with conf_min_delta
        regime: Current regime (trend/chop/high_vol)
    
    Returns:
        Mutated threshold value
    """
    # Map regime to threshold key
    regime_key = regime
    if regime in ("trend_up", "trend_down", "panic_down"):
        regime_key = "trend"
    
    base_threshold = base_thresholds.get(regime_key, base_thresholds.get("chop", 0.72))
    
    # Apply conf_min_delta mutation
    conf_min_delta = mutations.get("conf_min_delta", 0.0)
    mutated_threshold = base_threshold + conf_min_delta
    
    # Clamp to reasonable bounds
    return max(0.50, min(0.95, mutated_threshold))


def simulate_variant_step(
    variant_state: Dict[str, Any],
    symbol: str,
    timeframe: str = "15m",
) -> None:
    """
    Simulate one step (one bar) for a variant strategy.
    
    This mirrors exploration lane logic but uses mutated thresholds.
    
    Args:
        variant_state: Variant state dict (modified in-place)
        symbol: Symbol to trade
        timeframe: Timeframe (default: "15m")
    """
    # Get latest candle
    try:
        ohlcv = get_live_ohlcv(symbol, timeframe)
        if not ohlcv or len(ohlcv) == 0:
            return
        
        latest_candle = ohlcv.iloc[-1]
    except Exception:
        return
    
    # Get signals
    try:
        result = get_signal_vector(symbol=symbol, timeframe=timeframe)
        signal_vector = result["signal_vector"]
        raw_registry = result["raw_registry"]
    except Exception:
        return
    
    # Classify regime
    try:
        regime_result = classify_regime(signal_vector, raw_registry)
        regime = regime_result.get("regime", "chop")
    except Exception:
        regime = "chop"
    
    # Compute confidence decision
    try:
        decision = decide(signal_vector, raw_registry)
        final_conf = decision["final"]["conf"]
        final_dir = decision["final"]["dir"]
    except Exception:
        return
    
    # Load base thresholds and apply mutations
    base_thresholds = _load_base_thresholds()
    mutations = variant_state["mutations"]
    mutated_threshold = _apply_mutations(base_thresholds, mutations, regime)
    
    # Get exploration cap mutation
    exploration_cap_delta = mutations.get("exploration_cap_delta", 0)
    base_exploration_cap = 2  # Default exploration cap
    mutated_exploration_cap = max(1, base_exploration_cap + exploration_cap_delta)
    
    position = variant_state["position"]
    stats = variant_state["stats"]
    trades = variant_state["trades"]
    
    current_price = float(latest_candle["close"])
    now = datetime.now(timezone.utc).isoformat()
    
    # Exit logic: check if we should close existing position
    if position["dir"] != 0:
        position["bars_open"] += 1
        
        # Simple exit conditions (mirror exploration lane)
        should_exit = False
        exit_reason = None
        
        # Exit if confidence drops below threshold
        if final_conf < 0.30:  # exit_min_conf
            should_exit = True
            exit_reason = "low_conf"
        
        # Exit if direction flips and opposite confidence is high
        current_dir = position["dir"]
        if final_dir != 0 and final_dir != current_dir and final_conf >= 0.60:  # reverse_min_conf
            should_exit = True
            exit_reason = "reverse"
        
        # Exit if position open too long
        if position["bars_open"] >= 10:  # max_bars_open
            should_exit = True
            exit_reason = "timeout"
        
        if should_exit:
            # Calculate P&L (simplified: use price change)
            entry_px = position.get("entry_px", current_price)
            if entry_px:
                pct_change = ((current_price - entry_px) / entry_px) * position["dir"]
            else:
                pct_change = 0.0
            
            # Log close trade
            close_trade = {
                "ts": now,
                "type": "close",
                "symbol": symbol,
                "variant_id": variant_state["id"],
                "dir": position["dir"],
                "entry_px": entry_px,
                "exit_px": current_price,
                "pct": pct_change,
                "exit_reason": exit_reason,
                "regime": regime,
                "bars_open": position["bars_open"],
            }
            trades.append(close_trade)
            
            # Update stats
            stats["exp_trades"] += 1
            stats["total_pnl"] += pct_change
            if pct_change > 0:
                stats["wins"] += 1
            elif pct_change < 0:
                stats["losses"] += 1
            
            # Calculate PF
            if stats["losses"] > 0:
                stats["exp_pf"] = abs(stats["wins"] * 0.01 / stats["losses"]) if stats["losses"] > 0 else None
            else:
                stats["exp_pf"] = float("inf") if stats["wins"] > 0 else None
            
            # Reset position
            position["dir"] = 0
            position["entry_px"] = None
            position["bars_open"] = 0
    
    # Entry logic: check if we should open new position
    if position["dir"] == 0:
        # Check if we've hit exploration cap
        if stats["exp_trades"] >= mutated_exploration_cap:
            return  # Cap reached, no more entries
        
        # Check if confidence meets mutated threshold
        if final_dir != 0 and final_conf >= mutated_threshold:
            # Open position
            position["dir"] = final_dir
            position["entry_px"] = current_price
            position["bars_open"] = 0
            
            # Log open trade
            open_trade = {
                "ts": now,
                "type": "open",
                "symbol": symbol,
                "variant_id": variant_state["id"],
                "dir": final_dir,
                "entry_px": current_price,
                "regime": regime,
                "conf": final_conf,
                "mutated_threshold": mutated_threshold,
            }
            trades.append(open_trade)


def run_variant_cycle(timeframe: str = "15m") -> Dict[str, Any]:
    """
    Run one cycle of variant execution for all active variants.
    
    Args:
        timeframe: Timeframe to use (default: "15m")
    
    Returns:
        Dict with summary of execution
    """
    # Load variants
    variants = load_active_variants()
    if not variants:
        return {
            "variants_loaded": 0,
            "variants_executed": 0,
            "summary": "No active variants found",
        }
    
    # Initialize states
    variant_states = initialize_variant_states(variants)
    
    # Execute one step for each variant
    executed = 0
    errors = []
    
    for variant in variants:
        variant_id = variant["id"]
        symbol = variant["symbol"]
        
        try:
            state = variant_states[variant_id]
            simulate_variant_step(state, symbol, timeframe)
            executed += 1
        except Exception as e:
            errors.append(f"{variant_id}: {str(e)}")
    
    # Save updated states
    for variant_id, state in variant_states.items():
        # Save trades log
        trades_path = VARIANT_DIR / f"{variant_id}_trades.jsonl"
        if state["trades"]:
            with trades_path.open("a") as f:
                # Only append new trades (not already saved)
                # For simplicity, we'll append all trades each time
                # In production, you'd track which trades are new
                for trade in state["trades"]:
                    f.write(json.dumps(trade) + "\n")
        
        # Save summary
        summary = {
            "variant_id": variant_id,
            "symbol": state["symbol"],
            "mutations": state["mutations"],
            "position": state["position"],
            "stats": state["stats"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        summary_path = VARIANT_DIR / f"{variant_id}_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2))
    
    return {
        "variants_loaded": len(variants),
        "variants_executed": executed,
        "errors": errors,
        "summary": f"Executed {executed}/{len(variants)} variants",
    }

