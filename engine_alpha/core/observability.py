"""
Observability module for Phase A bulletproof core.

Provides health heartbeat, snapshot persistence, and incident logging.
"""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from engine_alpha.core.atomic_io import atomic_write_json, atomic_append_jsonl
from engine_alpha.core.paths import REPORTS


def write_loop_health(reports_dir: str | Path, data: Dict[str, Any]) -> None:
    """
    Write loop health status atomically.
    
    Args:
        reports_dir: Reports directory path
        data: Health data dict (should include last_tick_ts, last_tick_ok, etc.)
    """
    reports_path = Path(reports_dir)
    health_path = reports_path / "loop_health.json"
    loop_dir = reports_path / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    loop_health_path = loop_dir / "loop_health.json"

    atomic_write_json(health_path, data)
    atomic_write_json(loop_health_path, data)


def write_latest_snapshot(reports_dir: str | Path, snapshot: Dict[str, Any]) -> None:
    """
    Write latest snapshot atomically.
    
    Args:
        reports_dir: Reports directory path
        snapshot: Snapshot dict to write
    """
    reports_path = Path(reports_dir)
    snapshot_path = reports_path / "latest_snapshot.json"
    
    atomic_write_json(snapshot_path, snapshot)


def log_incident(
    reports_dir: str | Path,
    incident: Dict[str, Any],
) -> None:
    """
    Log an incident to incidents.jsonl.
    
    Args:
        reports_dir: Reports directory path (will write to reports/incidents.jsonl)
        incident: Incident dict with ts, level, where, error_type, error, traceback, context, etc.
    """
    reports_path = Path(reports_dir)
    incidents_path = reports_path / "incidents.jsonl"
    
    atomic_append_jsonl(incidents_path, incident)


def create_incident(
    where: str,
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    tick_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create an incident dict from an exception.
    
    Args:
        where: Location identifier (e.g., "autonomous_trader.tick")
        error: Exception object
        context: Optional context dict (e.g., last decision, last primitives)
        symbol: Optional symbol
        timeframe: Optional timeframe
        tick_id: Optional tick_id from snapshot
    
    Returns:
        Incident dict ready for log_incident()
    """
    now = datetime.now(timezone.utc)
    
    # Extract error info
    error_type = type(error).__name__
    error_msg = str(error)
    error_traceback = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    
    incident = {
        "ts": now.isoformat(),
        "level": "ERROR",
        "where": where,
        "error_type": error_type,
        "error": error_msg,
        "traceback": error_traceback,
        "context": context or {},
    }
    
    # Add optional fields if provided
    if symbol:
        incident["symbol"] = symbol
    if timeframe:
        incident["timeframe"] = timeframe
    if tick_id:
        incident["tick_id"] = tick_id
    
    return incident

