"""
Research Memory Layer - Phase 2
Persistent GPT memory for Reflection/Tuner/Dream cycles.

Takes snapshots of GPT outputs and research data, storing them in a bounded JSONL log.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS

RESEARCH_DIR = REPORTS / "research"
MEMORY_PATH = RESEARCH_DIR / "research_memory.jsonl"

# Paths to snapshot files
REFLECTION_OUTPUT_PATH = REPORTS / "gpt" / "reflection_output.json"
TUNER_OUTPUT_PATH = REPORTS / "gpt" / "tuner_output.json"
DREAM_OUTPUT_PATH = REPORTS / "gpt" / "dream_output.json"
QUALITY_SCORES_PATH = REPORTS / "gpt" / "quality_scores.json"
DRIFT_REPORT_PATH = RESEARCH_DIR / "regime_drift_report.json"
ARE_SNAPSHOT_PATH = RESEARCH_DIR / "are_snapshot.json"


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """Read JSON file, return None if missing or invalid."""
    if not path.exists():
        return None
    try:
        content = path.read_text().strip()
        if not content:
            return None
        return json.loads(content)
    except Exception:
        return None


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


def _write_jsonl(path: Path, entry: Dict[str, Any]) -> None:
    """Append entry to JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def take_snapshot() -> Dict[str, Any]:
    """
    Take a snapshot of current GPT outputs and research data.
    
    Returns:
        Dictionary containing snapshot data with timestamp.
    """
    now = datetime.now(timezone.utc).isoformat()
    
    snapshot = {
        "ts": now,
        "reflection": _read_json(REFLECTION_OUTPUT_PATH),
        "tuner": _read_json(TUNER_OUTPUT_PATH),
        "dream": _read_json(DREAM_OUTPUT_PATH),
        "quality_scores": _read_json(QUALITY_SCORES_PATH),
        "drift": _read_json(DRIFT_REPORT_PATH),
        "are": _read_json(ARE_SNAPSHOT_PATH),
    }
    
    # Write to memory log
    _write_jsonl(MEMORY_PATH, snapshot)
    
    return snapshot


def load_recent_memory(n: int = 3) -> List[Dict[str, Any]]:
    """
    Load last N memory entries from research_memory.jsonl.
    
    Args:
        n: Number of recent entries to return (default: 3)
    
    Returns:
        List of memory entries, most recent first.
    """
    entries = _read_jsonl(MEMORY_PATH)
    
    # Return last N entries (most recent first)
    return entries[-n:] if len(entries) > n else entries


def get_memory_count() -> int:
    """Get total number of memory entries."""
    entries = _read_jsonl(MEMORY_PATH)
    return len(entries)


def clear_memory() -> None:
    """Clear all memory entries (use with caution)."""
    if MEMORY_PATH.exists():
        MEMORY_PATH.unlink()

