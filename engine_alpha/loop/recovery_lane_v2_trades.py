"""
Recovery Lane V2 Trade Logging (Phase 5H.2)
--------------------------------------------

Dedicated trade log for recovery lane v2 with open/close records and realized PnL.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from engine_alpha.core.paths import REPORTS

RECOVERY_TRADES_PATH = REPORTS / "loop" / "recovery_lane_v2_trades.jsonl"
GLOBAL_TRADES_PATH = REPORTS / "trades.jsonl"


def log_open(
    trade_id: str,
    ts: str,
    symbol: str,
    direction: int,
    confidence: float,
    notional_usd: float,
    entry_px: float,
    regime: str,
    reason: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log a recovery lane v2 trade open event.
    
    Args:
        trade_id: Unique trade identifier (UUID hex)
        ts: ISO timestamp
        symbol: Trading symbol
        direction: Direction (-1=SHORT, +1=LONG)
        confidence: Entry confidence
        notional_usd: Notional size in USD
        entry_px: Entry price
        regime: Market regime
        reason: Entry reason
        meta: Optional metadata
    """
    if meta is None:
        meta = {}
    
    event = {
        "ts": ts,
        "lane": "recovery_v2",
        "trade_id": trade_id,
        "action": "open",
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "notional_usd": notional_usd,
        "entry_px": entry_px,
        "regime": regime,
        "reason": reason,
        "meta": meta,
    }
    
    # Ensure directory exists
    RECOVERY_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Append to JSONL file
    with RECOVERY_TRADES_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    # NOTE: Do NOT mirror opens into the global trades log to avoid duplicate open entries.
    # The lane’s existing open writer is the single source of truth for opens.
    # (Explicitly no-op for global mirroring.)


def log_close(
    trade_id: str,
    ts: str,
    symbol: str,
    direction: int,
    confidence: float,
    notional_usd: float,
    entry_px: float,
    exit_px: float,
    pnl_pct: float,
    pnl_usd: float,
    exit_reason: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log a recovery lane v2 trade close event.
    
    Args:
        trade_id: Unique trade identifier (UUID hex)
        ts: ISO timestamp
        symbol: Trading symbol
        direction: Direction (-1=SHORT, +1=LONG)
        confidence: Exit confidence
        notional_usd: Notional size in USD
        entry_px: Entry price
        exit_px: Exit price
        pnl_pct: Realized PnL percentage
        pnl_usd: Realized PnL in USD
        exit_reason: Exit reason (tp/sl/timeout/confidence_drop/direction_flip)
        meta: Optional metadata
    """
    if meta is None:
        meta = {}
    
    event = {
        "ts": ts,
        "lane": "recovery_v2",
        "trade_id": trade_id,
        "action": "close",
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "notional_usd": notional_usd,
        "entry_px": entry_px,
        "exit_px": exit_px,
        "pnl_pct": pnl_pct,
        "pnl_usd": pnl_usd,
        "exit_reason": exit_reason,
        "meta": meta,
    }
    
    # Ensure directory exists
    RECOVERY_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Append to JSONL file
    with RECOVERY_TRADES_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

    # Mirror into global trades log for PF/analytics consistency
    try:
        close_event = {
            "ts": ts,
            "type": "close",
            "symbol": symbol,
            "strategy": "recovery_v2",
            "trade_kind": "recovery_v2",
            "direction": direction,
            "pct": pnl_pct,
            "entry_px": entry_px,
            "exit_px": exit_px,
            "exit_reason": exit_reason,
            "exit_label": exit_reason,
            "exit_px_source": meta.get("exit_px_source"),
            "logger_version": "trades_v2",
        }
        GLOBAL_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with GLOBAL_TRADES_PATH.open("a", encoding="utf-8") as gf:
            gf.write(json.dumps(close_event) + "\n")
    except Exception:
        # Never crash the lane on logging errors
        pass


def generate_trade_id() -> str:
    """Generate a unique trade ID (UUID4 hex)."""
    return uuid.uuid4().hex


__all__ = ["log_open", "log_close", "generate_trade_id", "RECOVERY_TRADES_PATH"]

