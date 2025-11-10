#!/usr/bin/env python3
"""Diagnostic runner for wallet hunter (Phase 34.2)."""

from __future__ import annotations

import json

from engine_alpha.mirror import wallet_hunter


def main() -> int:
    result = wallet_hunter.run_once()
    snapshot = result.get("snapshot", {}) if isinstance(result, dict) else {}
    targets = result.get("targets", []) if isinstance(result, dict) else []

    summary = {
        "provider": snapshot.get("provider", "none"),
        "checked": snapshot.get("checked", 0),
        "eligible": snapshot.get("eligible", 0),
        "top_targets": len(targets) if isinstance(targets, list) else 0,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
