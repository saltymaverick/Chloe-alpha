"""
Reflection packet storage.

Handles atomic writes and JSONL appends for reflection packets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from engine_alpha.core.atomic_io import atomic_write_json, atomic_append_jsonl
from engine_alpha.core.paths import REPORTS


LATEST_PACKET_PATH = REPORTS / "reflection_packet.json"
PACKETS_JSONL_PATH = REPORTS / "reflection_packets.jsonl"

# Simple counter for "every N ticks" gating
_tick_counter = 0


def write_latest_packet(packet: Dict[str, Any], path: Path = LATEST_PACKET_PATH) -> None:
    """
    Write latest reflection packet atomically.
    
    Args:
        packet: Reflection packet dict
        path: Path to write to (default: reports/reflection_packet.json)
    """
    atomic_write_json(path, packet)


def append_packet(
    packet: Dict[str, Any],
    path: Path = PACKETS_JSONL_PATH,
    gate_on_samples: bool = True,
    gate_every_n_ticks: int = 20,
) -> None:
    """
    Append reflection packet to JSONL with optional gating.
    
    Args:
        packet: Reflection packet dict
        path: Path to JSONL file (default: reports/reflection_packets.jsonl)
        gate_on_samples: If True, only append when samples_processed > 0
        gate_every_n_ticks: Append every N ticks regardless of other conditions
    """
    global _tick_counter
    _tick_counter += 1
    
    # Check gating conditions
    should_append = False
    
    # Gate 1: samples processed
    if gate_on_samples:
        self_trust = packet.get("primitives", {}).get("self_trust", {})
        if self_trust.get("samples_processed", 0) > 0:
            should_append = True
    
    # Gate 2: action is not UNKNOWN
    decision = packet.get("decision", {})
    if decision.get("action") not in (None, "UNKNOWN"):
        should_append = True
    
    # Gate 3: eligible opportunity
    opportunity = packet.get("primitives", {}).get("opportunity", {})
    if opportunity.get("eligible") is True:
        should_append = True
    
    # Gate 4: every N ticks
    if _tick_counter % gate_every_n_ticks == 0:
        should_append = True
    
    if should_append:
        atomic_append_jsonl(path, packet)

