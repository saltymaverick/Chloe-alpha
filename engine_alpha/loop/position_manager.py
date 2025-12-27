# engine_alpha/loop/position_manager.py

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.risk.risk_autoscaler import RiskContext, compute_risk_multiplier

# Per-symbol position storage: key = (symbol, timeframe)
_positions: Dict[Tuple[str, str], Dict[str, Any]] = {}
POSITION_STATE_PATH = REPORTS / "position_state.json"

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_positions_payload(
    data: Any,
    default_ts: Optional[str] = None,
) -> Tuple[Dict[str, Dict[str, Any]], str, bool]:
    """
    Normalize any loaded position_state payload to the canonical schema:
      {"positions": {...}, "last_updated": "<iso>"}

    Returns (positions_dict, last_updated, migrated)
    """
    migrated = False
    last_updated = default_ts or _now_iso()
    positions_dict: Dict[str, Dict[str, Any]] = {}

    if isinstance(data, dict):
        # New-format payload
        if isinstance(data.get("positions"), dict):
            raw_positions = data.get("positions") or {}
            for key_str, pos in raw_positions.items():
                if not isinstance(pos, dict):
                    migrated = True
                    continue
                symbol = (pos.get("symbol") or key_str.split("_")[0] or "LEGACY").upper()
                tf = (pos.get("timeframe") or (key_str.split("_")[1] if "_" in key_str else "15m")).lower()
                norm_key = f"{symbol}_{tf}"
                pos_last_ts = pos.get("last_ts") or default_ts or _now_iso()
                positions_dict[norm_key] = {
                    "dir": int(pos.get("dir", 0)),
                    "bars_open": int(pos.get("bars_open", 0)),
                    "entry_px": pos.get("entry_px"),
                    "last_ts": pos_last_ts,
                    "entry_ts": pos.get("entry_ts") or pos_last_ts,
                    "risk_mult": pos.get("risk_mult"),
                    "symbol": symbol,
                    "timeframe": tf,
                    "trade_kind": pos.get("trade_kind", "normal"),
                }
                if pos.get("last_ts"):
                    last_updated = pos_last_ts
            # If last_updated missing, mark migrated so we backfill
            if not data.get("last_updated"):
                migrated = True
        # Legacy single-position format
        elif any(k in data for k in ("dir", "bars_open", "entry_px")):
            migrated = True
            symbol = (data.get("symbol") or "LEGACY").upper()
            tf = (data.get("timeframe") or "15m").lower()
            norm_key = f"{symbol}_{tf}"
            pos_last_ts = data.get("last_ts") or default_ts or _now_iso()
            last_updated = pos_last_ts
            positions_dict[norm_key] = {
                "dir": int(data.get("dir", 0)),
                "bars_open": int(data.get("bars_open", 0)),
                "entry_px": data.get("entry_px"),
                "last_ts": pos_last_ts,
                "symbol": symbol,
                "timeframe": tf,
                "trade_kind": data.get("trade_kind", "normal"),
            }
        else:
            # Unknown payload type – treat as empty
            migrated = True
    else:
        migrated = True

    return positions_dict, last_updated, migrated


def _write_position_state(positions: Dict[str, Dict[str, Any]], last_updated: Optional[str] = None) -> None:
    """Persist canonical position state to disk."""
    payload = {
        "positions": positions,
        "last_updated": last_updated or _now_iso(),
    }
    POSITION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSITION_STATE_PATH.write_text(json.dumps(payload, indent=2))


def load_position_state() -> Dict[str, Any]:
    """
    Load position_state.json and auto-migrate legacy formats to the canonical schema.
    Returns the normalized payload (positions dict + last_updated).
    """
    if not POSITION_STATE_PATH.exists():
        payload = {"positions": {}, "last_updated": _now_iso()}
        _write_position_state(payload["positions"], payload["last_updated"])
        return payload

    try:
        raw = json.loads(POSITION_STATE_PATH.read_text())
    except Exception:
        payload = {"positions": {}, "last_updated": _now_iso()}
        _write_position_state(payload["positions"], payload["last_updated"])
        return payload

    positions_dict, last_updated, migrated = _normalize_positions_payload(raw)

    # Cleanup: drop any recovery_v2 entries (recovery has its own ledger)
    cleaned_positions = {k: v for k, v in positions_dict.items() if v.get("trade_kind") != "recovery_v2"}
    if len(cleaned_positions) != len(positions_dict):
        positions_dict = cleaned_positions
        last_updated = _now_iso()
        migrated = True

    # One-time cleanup: drop recovery_v2 entries from shared position_state (should live in recovery_lane_v2_state.json)
    if migrated:
        _write_position_state(positions_dict, last_updated)

    return {"positions": positions_dict, "last_updated": last_updated}


def get_open_position(symbol: Optional[str] = None, timeframe: Optional[str] = None):
    """
    Get open position for a specific symbol+timeframe.
    If symbol/timeframe not provided, returns None (legacy single-symbol mode deprecated).
    """
    if symbol is None or timeframe is None:
        # Legacy mode: return None (we require symbol+timeframe now)
        return None
    
    key = (symbol.upper(), timeframe.lower())
    pos = _positions.get(key)
    if pos and pos.get("dir", 0) != 0:
        return dict(pos)
    return None


def set_position(p: Dict[str, Any], symbol: Optional[str] = None, timeframe: Optional[str] = None):
    """
    Set position for a specific symbol+timeframe.
    If symbol/timeframe not provided, tries to extract from position dict or uses legacy mode.
    """
    # Try to extract symbol/timeframe from position dict if not provided
    if symbol is None:
        symbol = p.get("symbol")
    if timeframe is None:
        timeframe = p.get("timeframe", "15m")

    if symbol is None or timeframe is None:
        # Legacy mode: log warning but don't fail
        logger.warning("set_position called without symbol/timeframe - using legacy single-position mode")
        # Store in a default key for backward compatibility (but this is deprecated)
        key = ("LEGACY", "15m")
    else:
        key = (symbol.upper(), timeframe.lower())

    print(f"SET_POSITION: {key} risk_mult={p.get('risk_mult')}")
    _positions[key] = dict(p)
    # Also store symbol/timeframe in the position dict for defensive checks
    _positions[key]["symbol"] = symbol.upper() if symbol else "LEGACY"
    _positions[key]["timeframe"] = timeframe.lower() if timeframe else "15m"


def clear_position(symbol: Optional[str] = None, timeframe: Optional[str] = None):
    """
    Clear position for a specific symbol+timeframe.
    If symbol/timeframe not provided, clears legacy position.
    """
    if symbol is None or timeframe is None:
        # Legacy mode: clear default key
        key = ("LEGACY", "15m")
    else:
        key = (symbol.upper(), timeframe.lower())
    
    if key in _positions:
        del _positions[key]


def count_open_positions(
    mode: Optional[str] = None,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    trade_kind: Optional[str] = None,
) -> int:
    """
    Count open positions matching the given filters.
    
    Args:
        mode: Filter by mode (PAPER/LIVE) - currently not stored, so this is ignored
        symbol: Filter by symbol (case-insensitive)
        timeframe: Filter by timeframe (case-insensitive)
        trade_kind: Filter by trade_kind ("exploration" or "normal")
    
    Returns:
        Number of open positions matching all specified filters
    """
    count = 0
    
    # Check in-memory positions
    for key, pos in _positions.items():
        if pos.get("dir", 0) == 0:
            continue  # Skip closed positions
        
        # Filter by symbol
        if symbol is not None:
            pos_symbol = pos.get("symbol", "")
            if pos_symbol.upper() != symbol.upper():
                continue
        
        # Filter by timeframe
        if timeframe is not None:
            pos_timeframe = pos.get("timeframe", "")
            if pos_timeframe.lower() != timeframe.lower():
                continue
        
        # Filter by trade_kind
        pos_trade_kind = pos.get("trade_kind", "normal")
        if trade_kind is not None and pos_trade_kind != trade_kind:
            continue
        
        count += 1
    
    # Also check persistent storage (normalized)
    try:
        persisted = load_position_state()
        positions_dict = persisted.get("positions", {})
        for key_str, pos_data in positions_dict.items():
            if not isinstance(pos_data, dict):
                continue

            dir_val = pos_data.get("dir", 0)
            if dir_val == 0:
                continue  # Skip closed positions

            # Filter by symbol
            if symbol is not None:
                pos_symbol = pos_data.get("symbol", "")
                if pos_symbol.upper() != symbol.upper():
                    continue

            # Filter by timeframe
            if timeframe is not None:
                pos_timeframe = pos_data.get("timeframe", "")
                if pos_timeframe.lower() != timeframe.lower():
                    continue

            # Filter by trade_kind
            pos_trade_kind = pos_data.get("trade_kind", "normal")
            if trade_kind is not None and pos_trade_kind != trade_kind:
                continue

            # Check if this position is already counted in _positions
            pos_symbol_val = pos_data.get("symbol", "")
            pos_timeframe_val = pos_data.get("timeframe", "15m")
            cache_key = (pos_symbol_val.upper(), pos_timeframe_val.lower())
            if cache_key not in _positions:
                count += 1
    except Exception:
        pass
    
    return count


def count_open_positions_filtered(
    exclude_trade_kinds: Optional[set[str]] = None,
    mode: Optional[str] = None,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    trade_kind: Optional[str] = None,
) -> int:
    """
    Count open positions with optional exclusion by trade_kind.
    """
    if exclude_trade_kinds is None:
        exclude_trade_kinds = set()

    count = 0

    # In-memory positions
    for key, pos in _positions.items():
        if pos.get("dir", 0) == 0:
            continue

        pos_trade_kind = pos.get("trade_kind", "normal")
        if pos_trade_kind in exclude_trade_kinds:
            continue
        if trade_kind is not None and pos_trade_kind != trade_kind:
            continue

        if symbol is not None:
            pos_symbol = pos.get("symbol", "")
            if pos_symbol.upper() != symbol.upper():
                continue

        if timeframe is not None:
            pos_timeframe = pos.get("timeframe", "")
            if pos_timeframe.lower() != timeframe.lower():
                continue

        count += 1

    # Persisted positions
    try:
        persisted = load_position_state()
        positions_dict = persisted.get("positions", {})
        for key_str, pos_data in positions_dict.items():
            if not isinstance(pos_data, dict):
                continue

            dir_val = pos_data.get("dir", 0)
            if dir_val == 0:
                continue

            pos_trade_kind = pos_data.get("trade_kind", "normal")
            if pos_trade_kind in exclude_trade_kinds:
                continue
            if trade_kind is not None and pos_trade_kind != trade_kind:
                continue

            if symbol is not None:
                pos_symbol = pos_data.get("symbol", "")
                if pos_symbol.upper() != symbol.upper():
                    continue

            if timeframe is not None:
                pos_timeframe = pos_data.get("timeframe", "")
                if pos_timeframe.lower() != timeframe.lower():
                    continue

            cache_key = (pos_data.get("symbol", "").upper(), pos_data.get("timeframe", "15m").lower())
            if cache_key not in _positions:
                count += 1
    except Exception:
        pass

    return count


def get_open_positions_filtered(
    exclude_trade_kinds: Optional[set[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Return a dict of open positions (dir != 0), optionally excluding trade_kinds.
    """
    if exclude_trade_kinds is None:
        exclude_trade_kinds = set()

    out: Dict[str, Dict[str, Any]] = {}
    state = load_position_state()
    positions = state.get("positions", {})
    for key, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        if (pos.get("dir") or 0) == 0:
            continue
        if pos.get("trade_kind") in exclude_trade_kinds:
            continue
        out[key] = pos
    return out


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r") as f:
        return json.load(f)


def _lookup_expected_edge(confidence: float) -> float:
    """
    Use confidence_map.json to approximate expected return for this confidence.
    """
    conf_map_path = CONFIG / "confidence_map.json"
    conf_map = _load_json(conf_map_path)
    if not conf_map:
        return 0.0

    bucket = int(min(9, max(0, int(confidence * 10))))
    info = conf_map.get(str(bucket), {})
    return float(info.get("expected_return", 0.0))


def _lookup_regime_edge(regime: str) -> float:
    strengths_path = REPORTS / "research" / "strategy_strength.json"
    strengths = _load_json(strengths_path)
    info = strengths.get(regime, {})
    return float(info.get("edge", 0.0))


def compute_quant_position_size(
    base_notional: float,
    regime: str,
    confidence: float,
    volatility_norm: float,
) -> float:
    """
    Quant-aware position sizing:

    - Reads pf_local.json
    - Uses confidence_map + strategy_strength edge
    - Passes through RiskContext to compute_risk_multiplier
    """
    pf_data_path = REPORTS / "pf_local.json"
    pf_data = _load_json(pf_data_path)
    pf = float(pf_data.get("pf", 1.0))
    dd = float(pf_data.get("drawdown", 0.0))

    conf_edge = _lookup_expected_edge(confidence)
    reg_edge = _lookup_regime_edge(regime)
    edge = (conf_edge + reg_edge) / 2.0

    ctx = RiskContext(
        pf_local=pf,
        drawdown=dd,
        edge=edge,
        volatility=volatility_norm,
        confidence=confidence,
    )

    m = compute_risk_multiplier(ctx)
    return base_notional * m


def get_live_position(symbol: Optional[str] = None, timeframe: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get live position from persistent storage for a specific symbol+timeframe.
    If symbol/timeframe not provided, returns None (legacy mode deprecated).
    """
    if symbol is None or timeframe is None:
        # Require explicit symbol/timeframe for correctness
        return None

    payload = load_position_state()
    positions_dict = payload.get("positions") or {}
    
    key = f"{symbol.upper()}_{timeframe.lower()}"
    pos_data = positions_dict.get(key)
    
    if not isinstance(pos_data, dict):
        return None
    
    dir_val = pos_data.get("dir")
    bars_open = pos_data.get("bars_open")
    if not isinstance(dir_val, (int, float)) or dir_val == 0:
        return None
    
    try:
        bars = int(bars_open)
    except (TypeError, ValueError):
        bars = 0
    
    entry_px = pos_data.get("entry_px")
    try:
        entry_px = float(entry_px) if entry_px is not None else None
    except (TypeError, ValueError):
        entry_px = None
    
    # Defensive check: ensure symbol matches
    stored_symbol = pos_data.get("symbol")
    if stored_symbol and stored_symbol.upper() != symbol.upper():
        logger.warning(
            f"CROSS-SYMBOL MISMATCH: requested_symbol={symbol}, stored_symbol={stored_symbol}, entry_px={entry_px}"
        )
        return None
    
    return {
        "dir": int(dir_val),
        "bars_open": max(0, bars),
        "entry_px": entry_px,
        "last_ts": pos_data.get("last_ts"),
        "entry_ts": pos_data.get("entry_ts"),
        "risk_mult": pos_data.get("risk_mult"),
        "symbol": symbol.upper(),
        "timeframe": timeframe.lower(),
        "trade_kind": pos_data.get("trade_kind", "normal"),  # Preserve trade_kind
    }


def set_live_position(position: Dict[str, Any], symbol: Optional[str] = None, timeframe: Optional[str] = None) -> None:
    """
    Set live position in persistent storage for a specific symbol+timeframe.
    If symbol/timeframe not provided, tries to extract from position dict.
    """
    # Try to extract symbol/timeframe from position dict if not provided
    if symbol is None:
        symbol = position.get("symbol")
    if timeframe is None:
        timeframe = position.get("timeframe", "15m")
    
    if symbol is None or timeframe is None:
        logger.warning("set_live_position called without symbol/timeframe - cannot store position")
        return
    
    symbol = symbol.upper()
    timeframe = timeframe.lower()
    key = f"{symbol}_{timeframe}"
    
    # Load existing positions (normalized)
    payload = load_position_state()
    positions_dict = payload.get("positions", {})
    last_ts = position.get("last_ts") or _now_iso()
    entry_ts = position.get("entry_ts") or last_ts

    # Store new position
    positions_dict[key] = {
        "dir": int(position.get("dir", 0)),
        "bars_open": int(position.get("bars_open", 0)),
        "entry_px": position.get("entry_px"),
        "last_ts": last_ts,
        "entry_ts": entry_ts,
        "risk_mult": position.get("risk_mult"),
        "symbol": symbol,
        "timeframe": timeframe,
        "trade_kind": position.get("trade_kind", "normal"),  # Store trade_kind
    }

    # Write back with canonical schema
    _write_position_state(positions_dict, last_ts)
    
    # Also update in-memory cache
    _positions[(symbol, timeframe)] = {
        "dir": int(position.get("dir", 0)),
        "bars_open": int(position.get("bars_open", 0)),
        "entry_px": position.get("entry_px"),
        "last_ts": last_ts,
        "entry_ts": entry_ts,
        "risk_mult": position.get("risk_mult"),
        "symbol": symbol,
        "timeframe": timeframe,
        "trade_kind": position.get("trade_kind", "normal"),  # Store trade_kind in cache
    }


def clear_live_position(symbol: Optional[str] = None, timeframe: Optional[str] = None) -> None:
    """
    Clear live position from persistent storage for a specific symbol+timeframe.
    If symbol/timeframe not provided, clears all positions (use with caution).
    """
    if symbol is None or timeframe is None:
        # Clear all positions (use with caution)
        logger.warning("clear_live_position called without symbol/timeframe - clearing all positions")
        _write_position_state({}, _now_iso())
        _positions.clear()
        return
    
    symbol = symbol.upper()
    timeframe = timeframe.lower()
    key = f"{symbol}_{timeframe}"
    
    # Load existing positions (normalized)
    payload = load_position_state()
    positions_dict = payload.get("positions", {})
    
    # Remove this position
    if key in positions_dict:
        del positions_dict[key]
    
    # Write back with canonical schema
    _write_position_state(positions_dict, _now_iso())
    
    # Also clear from in-memory cache
    cache_key = (symbol, timeframe)
    if cache_key in _positions:
        del _positions[cache_key]
