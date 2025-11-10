#!/usr/bin/env python3
"""Diagnostic runner for wallet observer (Phase 34)."""

from __future__ import annotations

import json

from engine_alpha.mirror import wallet_observer


def main() -> int:
    result = wallet_observer.run_once()
    snapshot = result.get("snapshot", {}) if isinstance(result, dict) else {}
    behavior = result.get("behavior", {}) if isinstance(result, dict) else {}
    provider = snapshot.get("provider") or "none"
    print("== Wallet Observer Diagnostic ==")
    print(json.dumps(
        {
            "provider": provider,
            "targets": snapshot.get("targets", 0),
            "obs_count": snapshot.get("obs_count", 0),
            "addresses_scored": len(behavior) if isinstance(behavior, dict) else 0,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
