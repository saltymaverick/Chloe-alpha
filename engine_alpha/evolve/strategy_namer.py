"""
Strategy namer - Phase 7
Generates short deterministic names for parameter sets.
"""

from __future__ import annotations

from typing import Dict


def name_from_params(params: Dict[str, float]) -> str:
    entry = params.get("entry_min", 0)
    exit_ = params.get("exit_min", 0)
    flip = params.get("flip_min", 0)

    def fmt(x: float) -> str:
        return f"{x:.2f}".replace(".", "")

    return f"Echo-{fmt(entry)}-{fmt(exit_)}-{fmt(flip)}"
