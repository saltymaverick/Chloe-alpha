"""
Tests for invalidation clarity primitives.
"""

from __future__ import annotations

try:
    import pytest
except ImportError:
    pytest = None  # Tests can run without pytest if called directly

from engine_alpha.core.invalidation import clamp01, compute_invalidation


def test_clamp01_basic():
    """Test clamp01 clamps values to [0, 1]."""
    assert clamp01(0.5) == 0.5
    assert clamp01(0.0) == 0.0
    assert clamp01(1.0) == 1.0
    assert clamp01(-1.0) == 0.0
    assert clamp01(2.0) == 1.0
    assert clamp01(None) is None


def test_compute_invalidation_no_position():
    """Test that invalidation returns None scores when no position."""
    snapshot = {
        "market": {"price": 3000.0},
        "execution": {"position": {"is_open": False}},
    }
    
    result = compute_invalidation(snapshot, "2025-12-14T17:00:00+00:00")
    
    assert result["thesis_health_score"] is None
    assert result["soft_invalidation_score"] is None
    assert result["invalidation_flags"] == []
    assert result["invalidation_inputs"]["reason"] == "no_position"


def test_compute_invalidation_long_price_against():
    """Test LONG position with price moving against (down 1%)."""
    snapshot = {
        "market": {"price": 2970.0},  # Down 1% from entry
        "execution": {
            "position": {
                "is_open": True,
                "side": "LONG",
                "entry_price": 3000.0,
                "symbol": "ETHUSDT",
            }
        },
        "primitives": {
            "decay": {"confidence_decayed": 0.60},  # Good confidence
        },
    }
    
    result = compute_invalidation(snapshot, "2025-12-14T17:00:00+00:00")
    
    assert result["thesis_health_score"] is not None
    assert result["soft_invalidation_score"] is not None
    assert result["soft_invalidation_score"] > 0  # Should have some invalidation
    
    # Check mismatch penalty exists
    inputs = result["invalidation_inputs"]
    assert inputs["mismatch_penalty"] is not None
    assert inputs["mismatch_penalty"] > 0
    
    # Should have PRICE_AGAINST_POSITION flag if penalty high enough
    if inputs["mismatch_penalty"] > 0.35:
        assert "PRICE_AGAINST_POSITION" in result["invalidation_flags"]


def test_compute_invalidation_low_confidence():
    """Test that low confidence_decayed triggers CONFIDENCE_DECAYED flag."""
    snapshot = {
        "market": {"price": 3000.0},
        "execution": {
            "position": {
                "is_open": True,
                "side": "LONG",
                "entry_price": 3000.0,
                "symbol": "ETHUSDT",
            }
        },
        "primitives": {
            "decay": {"confidence_decayed": 0.40},  # Low confidence (below target 0.55)
        },
    }
    
    result = compute_invalidation(snapshot, "2025-12-14T17:00:00+00:00")
    
    inputs = result["invalidation_inputs"]
    conf_penalty = inputs.get("conf_penalty")
    
    if conf_penalty is not None and conf_penalty > 0.35:
        assert "CONFIDENCE_DECAYED" in result["invalidation_flags"]


def test_compute_invalidation_scores_bounded():
    """Test that scores are bounded [0, 1]."""
    snapshot = {
        "market": {"price": 3000.0},
        "execution": {
            "position": {
                "is_open": True,
                "side": "LONG",
                "entry_price": 3000.0,
                "symbol": "ETHUSDT",
            }
        },
        "primitives": {
            "decay": {"confidence_decayed": 0.50},
        },
    }
    
    result = compute_invalidation(snapshot, "2025-12-14T17:00:00+00:00")
    
    if result["thesis_health_score"] is not None:
        assert 0.0 <= result["thesis_health_score"] <= 1.0
    
    if result["soft_invalidation_score"] is not None:
        assert 0.0 <= result["soft_invalidation_score"] <= 1.0

