"""
Test snapshot schema and utilities.
"""

import pytest
from engine_alpha.core.snapshot import new_snapshot, snapshot_set, snapshot_get


def test_new_snapshot_required_keys():
    """Test that new_snapshot returns dict with required top-level keys."""
    snapshot = new_snapshot(
        ts="2024-01-01T00:00:00Z",
        symbol="ETHUSDT",
        timeframe="15m",
        mode="PAPER"
    )
    
    # Check required top-level keys
    assert "ts" in snapshot
    assert "symbol" in snapshot
    assert "timeframe" in snapshot
    assert "mode" in snapshot
    assert "market" in snapshot
    assert "signals" in snapshot
    assert "primitives" in snapshot
    assert "regime" in snapshot
    assert "risk" in snapshot
    assert "decision" in snapshot
    assert "execution" in snapshot
    assert "metrics" in snapshot
    assert "meta" in snapshot
    
    # Check meta structure
    assert "tick_id" in snapshot["meta"]
    assert "version" in snapshot["meta"]
    assert snapshot["meta"]["version"] == "alpha"
    assert isinstance(snapshot["meta"]["notes"], list)


def test_snapshot_set_get_nested():
    """Test snapshot_set/get works for nested paths."""
    snapshot = new_snapshot(
        ts="2024-01-01T00:00:00Z",
        symbol="ETHUSDT",
        timeframe="15m",
        mode="PAPER"
    )
    
    # Test setting nested values
    snapshot_set(snapshot, "signals.pci", 0.75)
    snapshot_set(snapshot, "decision.final.dir", 1)
    snapshot_set(snapshot, "decision.final.conf", 0.85)
    
    # Test getting nested values
    assert snapshot_get(snapshot, "signals.pci") == 0.75
    assert snapshot_get(snapshot, "decision.final.dir") == 1
    assert snapshot_get(snapshot, "decision.final.conf") == 0.85
    
    # Test default value
    assert snapshot_get(snapshot, "signals.nonexistent", default="default") == "default"
    assert snapshot_get(snapshot, "nonexistent.path", default=None) is None
    
    # Verify structure
    assert snapshot["signals"]["pci"] == 0.75
    assert snapshot["decision"]["final"]["dir"] == 1
    assert snapshot["decision"]["final"]["conf"] == 0.85

