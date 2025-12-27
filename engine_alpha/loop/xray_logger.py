"""
X-ray Logger - Gate State Telemetry

Writes comprehensive gate state snapshots to reports/xray/latest.jsonl
for real-time introspection of trading decisions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from engine_alpha.core.paths import REPORTS

XRAY_DIR = REPORTS / "xray"
XRAY_PATH = XRAY_DIR / "latest.jsonl"
MAX_XRAY_LINES = 1000  # Keep last 1000 entries


def _ensure_xray_dir():
    """Ensure X-ray directory exists."""
    XRAY_PATH.parent.mkdir(parents=True, exist_ok=True)


def write_xray_snapshot(
    symbol: str,
    timeframe: str,
    bar_ts: str,
    regime: str,
    direction: int,
    confidence: float,
    combined_edge: float,
    regime_pass: bool,
    confidence_pass: bool,
    exploration_pass: bool,
    edge_pass: bool,
    can_open: bool,
    why_blocked: Optional[str] = None,
    gate_stage: Optional[str] = None,
    final_notional: Optional[float] = None,
    size_factor: Optional[float] = None,
    trade_kind: Optional[str] = None,
) -> None:
    """
    Write a comprehensive X-ray snapshot of gate state for a trading decision.
    
    Args:
        symbol: Trading symbol (e.g., ETHUSDT)
        timeframe: Timeframe (e.g., 15m)
        bar_ts: Bar timestamp
        regime: Market regime (trend_up, trend_down, high_vol, chop)
        direction: Trade direction (-1, 0, +1)
        confidence: Signal confidence (0.0-1.0)
        combined_edge: Combined edge estimate
        regime_pass: Whether regime gate passed
        confidence_pass: Whether confidence gate passed
        exploration_pass: Whether exploration mode bypassed confidence
        edge_pass: Whether edge gate passed
        can_open: Final decision (can open trade)
        why_blocked: Reason if blocked (optional)
        gate_stage: Gate stage that blocked (optional)
        final_notional: Final position size (optional)
        size_factor: Size factor applied (optional)
    """
    _ensure_xray_dir()  # Ensure directory exists before writing
    
    snapshot = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_ts": bar_ts,
        "regime": regime,
        "direction": direction,
        "confidence": float(confidence),
        "combined_edge": float(combined_edge),
        "gates": {
            "regime_pass": bool(regime_pass),
            "confidence_pass": bool(confidence_pass),
            "exploration_pass": bool(exploration_pass),
            "edge_pass": bool(edge_pass),
        },
        "can_open": bool(can_open),
        "trade_kind": trade_kind if trade_kind else ("exploration" if exploration_pass else "normal"),
        "logger_version": "xray_v1",  # Version marker
    }
    
    if why_blocked:
        snapshot["why_blocked"] = str(why_blocked)
    if gate_stage:
        snapshot["gate_stage"] = str(gate_stage)
    if final_notional is not None:
        snapshot["final_notional"] = float(final_notional)
    if size_factor is not None:
        snapshot["size_factor"] = float(size_factor)
    
    # Append to X-ray log
    try:
        with XRAY_PATH.open("a") as f:
            f.write(json.dumps(snapshot) + "\n")
        
        # Rotate if file gets too large (keep last N lines)
        try:
            with XRAY_PATH.open("r") as f:
                lines = f.readlines()
            if len(lines) > MAX_XRAY_LINES:
                # Keep last MAX_XRAY_LINES entries
                keep_lines = lines[-MAX_XRAY_LINES:]
                with XRAY_PATH.open("w") as f:
                    f.writelines(keep_lines)
        except Exception:
            pass  # Non-critical: rotation failed, continue
    except Exception:
        pass  # Non-critical: X-ray write failed, don't crash main loop


def load_recent_xray(limit: int = 200) -> list[Dict[str, Any]]:
    """
    Load recent X-ray snapshots for reflection/analysis.
    
    Args:
        limit: Maximum number of entries to return
        
    Returns:
        List of X-ray snapshot dictionaries
    """
    if not XRAY_PATH.exists():
        return []
    
    try:
        with XRAY_PATH.open("r") as f:
            lines = f.readlines()[-limit:]
        
        entries = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries.append(entry)
            except Exception:
                continue
        
        return entries
    except Exception:
        return []

