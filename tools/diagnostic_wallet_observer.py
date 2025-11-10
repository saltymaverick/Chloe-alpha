#!/usr/bin/env python3
"""Diagnostic runner for wallet observer (Phase 34)."""

from __future__ import annotations

import json

from engine_alpha.mirror import wallet_observer


def main() -> int:
    result = wallet_observer.run_once()
    cfg = result.get("config", {}) if isinstance(result, dict) else {}
    snapshot = result.get("snapshot", {}) if isinstance(result, dict) else {}
    behavior = result.get("behavior", {}) if isinstance(result, dict) else {}

    summary = {
        "targets": len(cfg.get("targets", []) if isinstance(cfg.get("targets", []), list) else []),
        "obs_count": snapshot.get("observations", 0),
        "addresses_scored": len(behavior) if isinstance(behavior, dict) else 0,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
