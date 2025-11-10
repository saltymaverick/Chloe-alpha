#!/usr/bin/env python3
"""Mirror diagnostic - Phase 34 (paper-only)."""

from __future__ import annotations

import json

from engine_alpha.mirror.mirror_manager import get_candidates, run_shadow


def main() -> int:
    snapshot = run_shadow()
    candidates = get_candidates()
    summary = {
        "ts": snapshot.get("ts"),
        "candidates": len(snapshot.get("candidates", [])),
        "eligible": len(candidates),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
