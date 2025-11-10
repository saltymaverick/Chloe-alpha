#!/usr/bin/env python3
"""
Sanitize a JSONL file by keeping only lines that parse as JSON
and contain required keys. Rewrites the file in place.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _load_lines(path: Path) -> List[str]:
    try:
        return path.read_text().splitlines()
    except Exception:
        return []


def _parse_line(raw: str) -> Dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


def sanitize(path: Path, required_keys: List[str]) -> tuple[int, int]:
    rows = _load_lines(path)
    kept: List[str] = []
    for line in rows:
        entry = _parse_line(line)
        if entry is None:
            continue
        if required_keys and not all(key in entry for key in required_keys):
            continue
        kept.append(json.dumps(entry))

    if kept:
        path.write_text("\n".join(kept) + "\n")
    else:
        path.write_text("")
    return len(kept), len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sanitize a JSONL file in place.")
    parser.add_argument("jsonl_path", help="Path to the JSONL file to sanitize.")
    parser.add_argument(
        "--required",
        nargs="*",
        default=["ts"],
        help="Keys required to keep a row (default: ts).",
    )
    args = parser.parse_args()

    path = Path(args.jsonl_path).expanduser()
    if not path.exists():
        print(f"{path} not found; nothing to sanitize.")
        return 0

    kept, total = sanitize(path, list(args.required))
    print(f"Sanitized {path} (kept {kept}/{total} valid lines).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

