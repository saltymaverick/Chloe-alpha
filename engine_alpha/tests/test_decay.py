"""
Tests for decay/half-life primitives.
"""

from __future__ import annotations

from datetime import datetime, timezone

try:
    import pytest
except ImportError:
    pytest = None  # Tests can run without pytest if called directly

from engine_alpha.core.decay import (
    age_seconds,
    compute_decays,
    exp_decay,
)
from engine_alpha.core.primitive_state import update_last


def test_exp_decay_zero_age():
    """Test that exp_decay returns original value when age is 0."""
    result = exp_decay(1.0, age_s=0.0, half_life_s=10.0)
    assert result is not None
    assert abs(result - 1.0) < 0.001


def test_exp_decay_half_life():
    """Test that exp_decay returns half value at half-life."""
    result = exp_decay(1.0, age_s=10.0, half_life_s=10.0)
    assert result is not None
    assert abs(result - 0.5) < 0.001


def test_exp_decay_none_inputs():
    """Test that exp_decay handles None inputs safely."""
    assert exp_decay(None, age_s=10.0, half_life_s=10.0) is None
    assert exp_decay(1.0, age_s=None, half_life_s=10.0) is None
    assert exp_decay(1.0, age_s=10.0, half_life_s=0.0) is None
    assert exp_decay(1.0, age_s=10.0, half_life_s=-1.0) is None


def test_age_seconds_correct():
    """Test that age_seconds returns correct seconds."""
    dt1 = datetime.now(timezone.utc)
    dt2 = dt1.replace(second=dt1.second + 30)  # 30 seconds later
    ts1 = dt1.isoformat()
    ts2 = dt2.isoformat()
    
    age = age_seconds(ts1, ts2)
    assert age is not None
    assert abs(age - 30.0) < 1.0  # Allow small tolerance for execution time


def test_age_seconds_none_prev():
    """Test that age_seconds handles None previous timestamp."""
    ts2 = datetime.now(timezone.utc).isoformat()
    age = age_seconds(None, ts2)
    assert age is None


def test_compute_decays_outputs_expected_keys():
    """Test that compute_decays outputs expected keys and updates state."""
    ts1 = datetime.now(timezone.utc).isoformat()
    ts2 = datetime.now(timezone.utc).isoformat()
    
    # Set up previous state
    state = {}
    update_last(state, "pci", ts1, 0.60)
    update_last(state, "confidence", ts1, 0.70)
    
    # Current values
    current = {"pci": 0.62, "confidence": 0.71}
    
    # Decay spec
    spec = {
        "pci": {"half_life_s": 900},
        "confidence": {"half_life_s": 1800},
    }
    
    # Compute decays
    decays, updated_state = compute_decays(ts2, current, state, spec)
    
    # Check expected keys
    assert "pci_age_s" in decays
    assert "pci_half_life_s" in decays
    assert "pci_decayed" in decays
    assert "pci_prev" in decays
    assert "confidence_age_s" in decays
    assert "confidence_half_life_s" in decays
    assert "confidence_decayed" in decays
    assert "confidence_prev" in decays
    
    # Check values
    assert decays["pci_half_life_s"] == 900
    assert decays["confidence_half_life_s"] == 1800
    assert decays["pci_prev"] == 0.60
    assert decays["confidence_prev"] == 0.70
    
    # Check that state was updated
    assert "pci" in updated_state
    assert "confidence" in updated_state
    assert updated_state["pci"]["value"] == 0.62
    assert updated_state["confidence"]["value"] == 0.71


def test_compute_decays_no_previous_state():
    """Test that compute_decays handles missing previous state gracefully."""
    ts = datetime.now(timezone.utc).isoformat()
    current = {"pci": 0.62}
    state = {}  # Empty state
    
    spec = {"pci": {"half_life_s": 900}}
    
    decays, updated_state = compute_decays(ts, current, state, spec)
    
    # Should have keys but decayed should be None
    assert "pci_age_s" in decays
    assert decays["pci_age_s"] is None
    assert decays["pci_decayed"] is None
    assert decays["pci_prev"] is None
    
    # But state should be updated
    assert "pci" in updated_state
    assert updated_state["pci"]["value"] == 0.62

