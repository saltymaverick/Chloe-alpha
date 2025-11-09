#!/usr/bin/env python3
"""
Runs policy orchestrator cycle (Phase 22).
"""

from __future__ import annotations

from engine_alpha.loop.orchestrator import cycle


def main() -> None:
    payload = cycle()
    inputs = payload.get("inputs", {})
    policy = payload.get("policy", {})
    print(
        "ORCH: rec={rec} band={band} allow_opens={opens} allow_pa={pa}".format(
            rec=inputs.get("rec"),
            band=inputs.get("risk_band"),
            opens=policy.get("allow_opens"),
            pa=policy.get("allow_pa"),
        )
    )


if __name__ == "__main__":
    main()
