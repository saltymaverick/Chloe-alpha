"""
Cadence Utilities
-----------------

Helper functions for checking report staleness and timestamps.
Used by policy_refresh and other tools to gate expensive recomputations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


def read_generated_at(path: Path) -> Optional[datetime]:
    """
    Read the 'generated_at' timestamp from a JSON report file.
    
    Returns:
        datetime object if found, None otherwise.
    """
    if not path.exists():
        return None
    
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Try meta.generated_at first (common format)
        meta = data.get("meta", {})
        if isinstance(meta, dict):
            gen_at = meta.get("generated_at")
            if gen_at:
                try:
                    # Parse ISO8601 timestamp
                    if isinstance(gen_at, str):
                        # Handle both with and without timezone
                        if gen_at.endswith("Z"):
                            gen_at = gen_at[:-1] + "+00:00"
                        return datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
                except Exception:
                    pass
        
        # Try top-level generated_at
        gen_at = data.get("generated_at")
        if gen_at:
            try:
                if isinstance(gen_at, str):
                    if gen_at.endswith("Z"):
                        gen_at = gen_at[:-1] + "+00:00"
                    return datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
            except Exception:
                pass
        
        return None
    except Exception:
        return None


def is_stale(path: Path, max_age_minutes: int) -> bool:
    """
    Check if a report file is stale (older than max_age_minutes).
    
    Args:
        path: Path to the JSON report file
        max_age_minutes: Maximum age in minutes before considered stale
    
    Returns:
        True if file is missing, doesn't have generated_at, or is older than max_age_minutes.
        False if file is fresh.
    """
    gen_at = read_generated_at(path)
    if gen_at is None:
        return True
    
    now = datetime.now(timezone.utc)
    age = now - gen_at
    
    # Ensure gen_at is timezone-aware
    if gen_at.tzinfo is None:
        gen_at = gen_at.replace(tzinfo=timezone.utc)
    
    age_minutes = age.total_seconds() / 60.0
    return age_minutes > max_age_minutes


__all__ = ["is_stale", "read_generated_at"]
