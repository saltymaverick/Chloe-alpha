"""
Atomic I/O utilities for Phase A bulletproof core.

Provides atomic file writes to prevent corruption during crashes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any


def atomic_write_json(path: str | Path, obj: Dict[str, Any]) -> None:
    """
    Write JSON file atomically using temp file + os.replace.
    
    Ensures parent directory exists.
    
    Args:
        path: Target file path
        obj: Dict to serialize as JSON
    """
    path_obj = Path(path)
    
    # Ensure parent directory exists
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to temp file first
    temp_path = path_obj.with_suffix(path_obj.suffix + ".tmp")
    
    try:
        # Write JSON with indentation for readability
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        
        # Atomic replace
        os.replace(str(temp_path), str(path_obj))
    except Exception:
        # Clean up temp file on error
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise


def atomic_append_jsonl(path: str | Path, obj: Dict[str, Any]) -> None:
    """
    Append a single-line JSON object to a JSONL file.
    
    Note: Per-line append is not fully atomic, but we use best practices:
    - Open with append mode
    - Flush immediately
    - Keep entries as single-line JSON
    
    Args:
        path: Target JSONL file path
        obj: Dict to serialize as single-line JSON
    """
    path_obj = Path(path)
    
    # Ensure parent directory exists
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Append single-line JSON
    with path_obj.open("a", encoding="utf-8") as f:
        json_line = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        f.write(json_line + "\n")
        f.flush()
        os.fsync(f.fileno())  # Force write to disk

