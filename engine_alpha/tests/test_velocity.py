"""
Tests for velocity computation primitives.
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    import pytest
except ImportError:
    pytest = None  # Tests can run without pytest if called directly

from engine_alpha.core.primitive_state import (
    compute_velocity,
    load_state,
    save_state,
    update_last,
)
from engine_alpha.core.velocity import compute_velocities


def test_velocity_none_when_no_previous_state():
    """Test that velocity is None when no previous state exists."""
    ts1 = datetime.now(timezone.utc).isoformat()
    current = {"pci": 0.62, "confidence": 0.71}
    state = {}  # Empty state
    
    velocities, _ = compute_velocities(ts1, current, state, ["pci", "confidence"])
    
    assert velocities["pci_per_s"] is None
    assert velocities["confidence_per_s"] is None


def test_velocity_correct_calculation():
    """Test that velocity is computed correctly with valid previous state."""
    # Create timestamps 10 seconds apart
    dt1 = datetime.now(timezone.utc)
    dt2 = dt1.replace(second=dt1.second + 10)
    ts1 = dt1.isoformat()
    ts2 = dt2.isoformat()
    
    # Previous values
    prev_pci = 0.60
    prev_conf = 0.70
    
    # Current values (delta = 0.2 for pci, -0.1 for confidence)
    current = {"pci": 0.80, "confidence": 0.60}
    
    # Set up state
    state = {}
    update_last(state, "pci", ts1, prev_pci)
    update_last(state, "confidence", ts1, prev_conf)
    
    # Compute velocity
    velocity = compute_velocity(ts1, prev_pci, ts2, current["pci"])
    
    # Should be approximately 0.02 per second (0.2 / 10)
    assert velocity is not None
    assert abs(velocity - 0.02) < 0.001


def test_velocity_handles_none_values():
    """Test that velocity computation handles None values safely."""
    ts1 = datetime.now(timezone.utc).isoformat()
    ts2 = datetime.now(timezone.utc).isoformat()
    
    # Test with None previous value
    velocity1 = compute_velocity(None, 0.5, ts2, 0.6)
    assert velocity1 is None
    
    # Test with None current value
    velocity2 = compute_velocity(ts1, 0.5, ts2, None)
    assert velocity2 is None
    
    # Test with None previous timestamp
    velocity3 = compute_velocity(None, 0.5, ts2, 0.6)
    assert velocity3 is None


def test_compute_velocities_updates_state():
    """Test that compute_velocities updates state even when velocity is None."""
    ts1 = datetime.now(timezone.utc).isoformat()
    current = {"pci": 0.62}
    state = {}
    
    velocities, updated_state = compute_velocities(ts1, current, state, ["pci"])
    
    # Velocity should be None (no previous state)
    assert velocities["pci_per_s"] is None
    
    # But state should be updated
    assert "pci" in updated_state
    assert updated_state["pci"]["ts"] == ts1
    assert updated_state["pci"]["value"] == 0.62


def test_compute_velocities_second_run_has_velocity():
    """Test that second run produces velocity values."""
    ts1 = datetime.now(timezone.utc).isoformat()
    
    # First run: no previous state
    current1 = {"pci": 0.60}
    state1 = {}
    velocities1, updated_state1 = compute_velocities(ts1, current1, state1, ["pci"])
    assert velocities1["pci_per_s"] is None
    
    # Second run: should have velocity
    # Create ts2 that's 5 seconds later
    dt1 = datetime.fromisoformat(ts1.replace("Z", "+00:00"))
    dt2 = dt1.replace(second=dt1.second + 5)
    ts2 = dt2.isoformat()
    
    current2 = {"pci": 0.65}  # Delta of 0.05 over 5 seconds = 0.01 per second
    velocities2, updated_state2 = compute_velocities(ts2, current2, updated_state1, ["pci"])
    
    assert velocities2["pci_per_s"] is not None
    assert abs(velocities2["pci_per_s"] - 0.01) < 0.001

