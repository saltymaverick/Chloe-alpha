"""
Self-trust / meta-confidence primitives.

Measures calibration of confidence predictions by tracking
confidence vs outcome correlation, Brier score, and overconfidence rate.
Uses trade log as source of truth (log-driven, no runtime coupling).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from engine_alpha.core.atomic_io import atomic_write_json
from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.trade_sanity import is_corrupted_trade_event


STATE_PATH = REPORTS / "self_trust_state.json"
TRADE_LOG_PATH = REPORTS / "trades.jsonl"


def _default_state() -> Dict[str, Any]:
    """Return default state structure."""
    return {
        "n": 0,
        "brier_ewma": 0.0,
        "overconfidence_ewma": 0.0,
        "last_sample_ts": None,
        "alpha": 0.05,
        "trade_log_path": str(TRADE_LOG_PATH),
        "last_byte_offset": 0,
        "open_confidence_cache": {},  # Track last open confidence per symbol+timeframe
    }


def load_state(path: Path = STATE_PATH) -> Dict[str, Any]:
    """
    Loads the self-trust state from a JSON file.
    Returns default structure if the file is missing or invalid.
    """
    if not path.exists():
        return _default_state()
    
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        if not isinstance(data, dict):
            return _default_state()
        
        # Ensure required keys exist
        default = _default_state()
        for key in default:
            if key not in data:
                data[key] = default[key]
        
        # Ensure trade_log_path is set (may be missing in old state)
        if "trade_log_path" not in data:
            data["trade_log_path"] = str(TRADE_LOG_PATH)
        if "last_byte_offset" not in data:
            data["last_byte_offset"] = 0
        
        return data
    except (json.JSONDecodeError, FileNotFoundError, TypeError, KeyError):
        return _default_state()
    except Exception:
        return _default_state()


def save_state(state: Dict[str, Any], path: Path = STATE_PATH) -> None:
    """
    Saves the self-trust state to a JSON file atomically.
    """
    atomic_write_json(path, state)


def clamp01(x: float | None) -> float | None:
    """
    Clamp value to [0, 1] range.
    
    Args:
        x: Value to clamp (or None)
        
    Returns:
        Clamped value in [0, 1], or None if input is None
    """
    if x is None:
        return None
    return max(0.0, min(1.0, float(x)))


def ewma(prev: float, x: float, alpha: float) -> float:
    """
    Exponential Weighted Moving Average.
    
    Args:
        prev: Previous EWMA value
        x: New observation
        alpha: Smoothing factor (0 < alpha <= 1)
        
    Returns:
        Updated EWMA value
    """
    return alpha * x + (1.0 - alpha) * prev


def safe_float(x: Any) -> float | None:
    """
    Safely convert value to float.
    
    Args:
        x: Value to convert
        
    Returns:
        Float value or None if conversion fails
    """
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def read_new_trade_lines(path: Path | str, last_byte_offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """
    Read new trade log lines since last byte offset.
    
    Args:
        path: Path to trade log file
        last_byte_offset: Last byte offset processed
        
    Returns:
        Tuple of (parsed_trades, new_byte_offset)
    """
    path_obj = Path(path) if isinstance(path, str) else path
    
    if not path_obj.exists():
        return [], last_byte_offset
    
    try:
        with path_obj.open("rb") as f:
            # Seek to last processed position
            f.seek(last_byte_offset)
            
            # Read remaining bytes
            remaining_bytes = f.read()
            
            if not remaining_bytes:
                return [], last_byte_offset
            
            # Decode and split lines
            text = remaining_bytes.decode("utf-8", errors="ignore")
            lines = text.splitlines()
            
            # Parse JSON from each line
            trades = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    if isinstance(trade, dict):
                        trades.append(trade)
                except json.JSONDecodeError:
                    continue  # Skip invalid lines
            
            # Update byte offset to end of file
            new_offset = last_byte_offset + len(remaining_bytes)
            
            return trades, new_offset
    except (FileNotFoundError, IOError, OSError):
        return [], last_byte_offset
    except Exception:
        return [], last_byte_offset


def extract_close_samples(
    trades: List[Dict[str, Any]],
    open_confidence_cache: Dict[str, float] | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """
    Extract close trade samples from trade log entries.
    Also tracks open events to build confidence cache for matching closes.
    
    Args:
        trades: List of trade dicts from log
        open_confidence_cache: Dict mapping "symbol:timeframe" -> last open confidence
        
    Returns:
        Tuple of (samples_list, updated_cache)
    """
    if open_confidence_cache is None:
        open_confidence_cache = {}
    
    samples = []
    skip_corrupt = 0
    skip_missing = 0
    processed = 0
    
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        
        action = trade.get("action") or trade.get("event") or trade.get("type")
        action_lower = str(action).lower() if action else ""
        
        # Only check corruption on OPEN events (CLOSE events don't have entry_px)
        if action_lower == "open":
            # Check for corrupted OPEN events only
            if is_corrupted_trade_event(trade):
                skip_corrupt += 1
                continue
        
        symbol = trade.get("symbol") or "UNKNOWN"
        timeframe = trade.get("timeframe") or "15m"
        cache_key = f"{symbol}:{timeframe}"
        
        # Track open events to cache entry confidence
        if action_lower == "open":
            # Extract confidence from open event
            conf = None
            for key in ["confidence", "conf", "entry_confidence", "entry_conf"]:
                val = trade.get(key)
                if val is not None:
                    conf = safe_float(val)
                    if conf is not None:
                        open_confidence_cache[cache_key] = conf
                        break
            continue  # Skip open events (we just cache them)
        
        # Process close events
        if not action or str(action).lower() != "close":
            continue
        
        # Extract pnl_pct (try multiple field names)
        pnl_pct = None
        for key in ["pnl_pct", "pnl_percent", "pnl", "pct", "pnl_percent_total"]:
            val = trade.get(key)
            if val is not None:
                pnl_pct = safe_float(val)
                if pnl_pct is not None:
                    break
        
        # Extract entry confidence (prefer from cache, fallback to close event fields)
        confidence = None
        
        # First try: get from open confidence cache
        if cache_key in open_confidence_cache:
            confidence = open_confidence_cache[cache_key]
            # Clear cache entry after use (one close per open)
            del open_confidence_cache[cache_key]
        
        # Fallback: try fields in close event (including exit_conf as last resort)
        if confidence is None:
            for key in ["entry_confidence", "entry_conf", "confidence", "conf", "exit_conf"]:
                val = trade.get(key)
                if val is not None:
                    confidence = safe_float(val)
                    if confidence is not None:
                        break
        
        # Skip if required fields missing (but don't count as corrupted)
        # Log which field is missing for debugging
        if pnl_pct is None:
            skip_missing += 1
            continue
        if confidence is None:
            skip_missing += 1
            continue
        
        # Extract timestamp
        ts = trade.get("ts") or trade.get("timestamp") or trade.get("time")
        
        samples.append({
            "ts": ts,
            "symbol": symbol,
            "pnl_pct": pnl_pct,
            "confidence": confidence,
        })
        processed += 1
    
    # Store skip counts in cache for debugging (will be included in metrics)
    open_confidence_cache["_debug_skip_corrupt"] = skip_corrupt
    open_confidence_cache["_debug_skip_missing"] = skip_missing
    open_confidence_cache["_debug_processed"] = processed
    
    return samples, open_confidence_cache


def update_state_with_samples(
    state: Dict[str, Any],
    samples: List[Dict[str, Any]],
    now_ts_iso: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Update self-trust state with new samples.
    
    Args:
        state: Current state dict
        samples: List of sample dicts with ts, pnl_pct, confidence
        now_ts_iso: Current ISO timestamp (fallback for missing ts)
        
    Returns:
        Tuple of (updated_state, metrics_dict)
    """
    alpha = state.get("alpha", 0.05)
    
    samples_processed = 0
    
    for sample in samples:
        confidence = clamp01(sample.get("confidence"))
        pnl_pct = sample.get("pnl_pct")
        
        if confidence is None or pnl_pct is None:
            continue
        
        # Outcome: 1 if win (pnl > 0), else 0
        y = 1.0 if pnl_pct > 0 else 0.0
        
        # Brier score: (confidence - outcome)^2
        brier = (confidence - y) ** 2
        
        # Overconfidence indicator: 1 if high confidence but loss, else 0
        overconf = 1.0 if (confidence >= 0.60 and y == 0.0) else 0.0
        
        # Update EWMA fields
        state["brier_ewma"] = ewma(state["brier_ewma"], brier, alpha)
        state["overconfidence_ewma"] = ewma(state["overconfidence_ewma"], overconf, alpha)
        
        # Increment sample count
        state["n"] = state.get("n", 0) + 1
        samples_processed += 1
        
        # Update last sample timestamp
        sample_ts = sample.get("ts") or now_ts_iso
        state["last_sample_ts"] = sample_ts
    
    # Compute metrics (even if no new samples this tick)
    # If n_samples == 0, output null values for clarity (even though state has 0.0)
    if state["n"] > 0:
        rmse = math.sqrt(state["brier_ewma"]) if state["brier_ewma"] >= 0 else 0.0
        
        # Self-trust score: 1 - RMSE - 0.5 * overconfidence_ewma
        # Higher score = more trustworthy
        self_trust_score = clamp01(1.0 - rmse - 0.5 * state["overconfidence_ewma"])
        
        metrics = {
            "self_trust_score": self_trust_score,
            "brier_ewma": state["brier_ewma"],
            "rmse_ewma": rmse,
            "overconfidence_ewma": state["overconfidence_ewma"],
            "n_samples": state["n"],
            "last_sample_ts": state["last_sample_ts"],
            "samples_processed": samples_processed,
        }
    else:
        # No samples yet - output null for clarity
        metrics = {
            "self_trust_score": None,
            "brier_ewma": None,
            "rmse_ewma": None,
            "overconfidence_ewma": None,
            "n_samples": 0,
            "last_sample_ts": None,
            "samples_processed": samples_processed,
        }
    
    return state, metrics


def compute_self_trust_from_trade_log(now_ts_iso: str) -> Dict[str, Any]:
    """
    Compute self-trust metrics from trade log (public API for wrapper).
    
    Args:
        now_ts_iso: Current ISO timestamp
        
    Returns:
        Metrics dict with self_trust_score, brier_ewma, etc.
    """
    # Load state
    state = load_state()
    
    # Get trade log path
    trade_log_path = state.get("trade_log_path", str(TRADE_LOG_PATH))
    trade_log_path_obj = Path(trade_log_path)
    
    # Read new trade lines since last offset
    last_offset = state.get("last_byte_offset", 0)
    trades, new_offset = read_new_trade_lines(trade_log_path_obj, last_offset)
    
    # Extract close samples (and update open confidence cache)
    open_cache = state.get("open_confidence_cache", {})
    samples, updated_cache = extract_close_samples(trades, open_cache)
    state["open_confidence_cache"] = updated_cache
    
    # Update state with samples
    state, metrics = update_state_with_samples(state, samples, now_ts_iso)
    
    # Add debug skip counts to metrics
    metrics["skip_corrupt"] = updated_cache.get("_debug_skip_corrupt", 0)
    metrics["skip_missing"] = updated_cache.get("_debug_skip_missing", 0)
    metrics["processed_this_run"] = updated_cache.get("_debug_processed", 0)
    
    # Clean debug keys from cache
    updated_cache.pop("_debug_skip_corrupt", None)
    updated_cache.pop("_debug_skip_missing", None)
    updated_cache.pop("_debug_processed", None)
    
    # Update byte offset
    state["last_byte_offset"] = new_offset
    
    # Save state
    save_state(state)
    
    return metrics
