"""
Tests for opportunity density primitives.
"""

from __future__ import annotations

try:
    import pytest
except ImportError:
    pytest = None  # Tests can run without pytest if called directly

from engine_alpha.core.opportunity_density import (
    load_state,
    save_state,
    ewma,
    update_opportunity_state,
    _default_state,
)
from engine_alpha.core.paths import REPORTS
from pathlib import Path
import json


def test_state_initializes_with_expected_keys():
    """Test that state initializes with expected keys."""
    state = _default_state()
    
    assert "global" in state
    assert "by_regime" in state
    assert "ticks" in state["global"]
    assert "eligible" in state["global"]
    assert "eligible_ewma" in state["global"]
    assert "ticks_ewma" in state["global"]
    assert "unknown" in state["by_regime"]


def test_update_increments_ticks_eligible():
    """Test that update increments ticks and eligible counters."""
    state = _default_state()
    
    # Update with eligible=True
    state, metrics = update_opportunity_state(
        state, "2025-12-14T17:00:00+00:00", "trend_up", True
    )
    
    assert state["global"]["ticks"] == 1
    assert state["global"]["eligible"] == 1
    assert state["by_regime"]["trend_up"]["ticks"] == 1
    assert state["by_regime"]["trend_up"]["eligible"] == 1
    
    # Update with eligible=False
    state, metrics = update_opportunity_state(
        state, "2025-12-14T17:01:00+00:00", "trend_up", False
    )
    
    assert state["global"]["ticks"] == 2
    assert state["global"]["eligible"] == 1  # Still 1 (not incremented)
    assert state["by_regime"]["trend_up"]["ticks"] == 2
    assert state["by_regime"]["trend_up"]["eligible"] == 1  # Still 1


def test_ewma_behaves_correctly():
    """Test that EWMA behaves correctly (density increases when eligible=True repeated)."""
    state = _default_state()
    
    # Start with all False
    for i in range(5):
        state, metrics = update_opportunity_state(
            state, f"2025-12-14T17:{i:02d}:00+00:00", "trend_up", False
        )
    
    initial_density = metrics["density_ewma"]
    
    # Then add many eligible ticks
    for i in range(10):
        state, metrics = update_opportunity_state(
            state, f"2025-12-14T17:{i+5:02d}:00+00:00", "trend_up", True
        )
    
    final_density = metrics["density_ewma"]
    
    # Density should increase after many eligible ticks
    assert final_density > initial_density


def test_metrics_fields_exist_and_bounded():
    """Test that metrics fields exist and density values are bounded [0, 1]."""
    state = _default_state()
    
    state, metrics = update_opportunity_state(
        state, "2025-12-14T17:00:00+00:00", "chop", True
    )
    
    # Check required fields exist
    assert "regime" in metrics
    assert "eligible" in metrics
    assert "density_ewma" in metrics
    assert "density_all_time" in metrics
    assert "global_density_ewma" in metrics
    assert "global_density_all_time" in metrics
    
    # Check density values are bounded [0, 1]
    assert 0.0 <= metrics["density_ewma"] <= 1.0
    assert 0.0 <= metrics["density_all_time"] <= 1.0
    assert 0.0 <= metrics["global_density_ewma"] <= 1.0
    assert 0.0 <= metrics["global_density_all_time"] <= 1.0


def test_load_save_state():
    """Test that load_state and save_state work correctly."""
    test_path = REPORTS / "test_opportunity_state.json"
    
    # Clean up if exists
    if test_path.exists():
        test_path.unlink()
    
    # Load should return default
    state1 = load_state(test_path)
    assert state1["global"]["ticks"] == 0
    
    # Update and save
    state1, _ = update_opportunity_state(
        state1, "2025-12-14T17:00:00+00:00", "trend_up", True
    )
    save_state(state1, test_path)
    
    # Load should return saved state
    state2 = load_state(test_path)
    assert state2["global"]["ticks"] == 1
    assert state2["global"]["eligible"] == 1
    
    # Clean up
    if test_path.exists():
        test_path.unlink()

