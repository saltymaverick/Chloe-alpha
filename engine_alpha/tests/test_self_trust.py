"""
Tests for self-trust / meta-confidence primitives.
"""

from __future__ import annotations

try:
    import pytest
except ImportError:
    pytest = None  # Tests can run without pytest if called directly

from engine_alpha.core.self_trust import (
    load_state,
    save_state,
    ewma,
    clamp01,
    update_state_with_samples,
    extract_close_samples,
    _default_state,
)
from engine_alpha.core.paths import REPORTS
from pathlib import Path
import math


def test_clamp01_basic():
    """Test clamp01 clamps values to [0, 1]."""
    assert clamp01(0.5) == 0.5
    assert clamp01(0.0) == 0.0
    assert clamp01(1.0) == 1.0
    assert clamp01(-1.0) == 0.0
    assert clamp01(2.0) == 1.0
    assert clamp01(None) is None


def test_update_state_with_samples_win_at_high_confidence():
    """Test first update with win at p=0.7 → brier = (0.7-1)^2 = 0.09; score > 0."""
    state = _default_state()
    
    samples = [{
        "ts": "2025-12-14T17:00:00+00:00",
        "symbol": "ETHUSDT",
        "pnl_pct": 0.05,  # Win
        "confidence": 0.7,
    }]
    
    state, metrics = update_state_with_samples(state, samples, "2025-12-14T17:00:00+00:00")
    
    # Brier = (0.7 - 1)^2 = 0.09
    expected_brier = (0.7 - 1.0) ** 2
    assert abs(state["brier_ewma"] - expected_brier) < 0.01  # Close to 0.09 (with EWMA smoothing)
    assert state["n"] == 1
    assert metrics["self_trust_score"] is not None
    assert metrics["self_trust_score"] > 0
    assert metrics["samples_processed"] == 1


def test_update_state_with_samples_repeated_losses_increase_overconfidence():
    """Test repeated losses at high confidence increases overconfidence_ewma and lowers self_trust_score."""
    state = _default_state()
    
    # First: win at high confidence
    samples1 = [{
        "ts": "2025-12-14T17:00:00+00:00",
        "symbol": "ETHUSDT",
        "pnl_pct": 0.02,  # Win
        "confidence": 0.75,
    }]
    state, metrics1 = update_state_with_samples(state, samples1, "2025-12-14T17:00:00+00:00")
    initial_score = metrics1["self_trust_score"]
    
    # Then: repeated losses at high confidence
    samples2 = [
        {
            "ts": f"2025-12-14T17:{i+1:02d}:00+00:00",
            "symbol": "ETHUSDT",
            "pnl_pct": -0.01,  # Loss
            "confidence": 0.75,
        }
        for i in range(5)
    ]
    state, metrics2 = update_state_with_samples(state, samples2, "2025-12-14T17:06:00+00:00")
    
    # Overconfidence should increase
    assert state["overconfidence_ewma"] > 0
    # Self-trust score should decrease
    assert metrics2["self_trust_score"] < initial_score


def test_self_trust_score_bounded():
    """Test that self_trust_score is bounded [0, 1]."""
    state = _default_state()
    
    # Test with various scenarios
    samples1 = [{"ts": "2025-12-14T17:00:00+00:00", "symbol": "ETHUSDT", "pnl_pct": 0.01, "confidence": 0.5}]
    state, metrics1 = update_state_with_samples(state, samples1, "2025-12-14T17:00:00+00:00")
    assert 0.0 <= metrics1["self_trust_score"] <= 1.0
    
    samples2 = [{"ts": "2025-12-14T17:01:00+00:00", "symbol": "ETHUSDT", "pnl_pct": -0.05, "confidence": 0.9}]
    state, metrics2 = update_state_with_samples(state, samples2, "2025-12-14T17:01:00+00:00")
    assert 0.0 <= metrics2["self_trust_score"] <= 1.0
    
    samples3 = [{"ts": "2025-12-14T17:02:00+00:00", "symbol": "ETHUSDT", "pnl_pct": 0.01, "confidence": 0.1}]
    state, metrics3 = update_state_with_samples(state, samples3, "2025-12-14T17:02:00+00:00")
    assert 0.0 <= metrics3["self_trust_score"] <= 1.0


def test_extract_close_samples():
    """Test extract_close_samples filters and extracts correctly."""
    trades = [
        {"action": "OPEN", "confidence": 0.7, "pnl_pct": 0.0},
        {"action": "CLOSE", "confidence": 0.7, "pnl_pct": 0.05, "ts": "2025-12-14T17:00:00+00:00", "symbol": "ETHUSDT"},
        {"event": "CLOSE", "entry_confidence": 0.8, "pct": -0.02, "ts": "2025-12-14T17:01:00+00:00", "symbol": "BTCUSDT"},
        {"type": "close", "conf": 0.6, "pnl": 0.01, "ts": "2025-12-14T17:02:00+00:00"},
    ]
    
    samples = extract_close_samples(trades)
    
    assert len(samples) == 3  # Three close events
    assert samples[0]["confidence"] == 0.7
    assert samples[0]["pnl_pct"] == 0.05
    assert samples[1]["confidence"] == 0.8
    assert samples[1]["pnl_pct"] == -0.02


def test_load_save_state():
    """Test that load_state and save_state work correctly."""
    test_path = REPORTS / "test_self_trust_state.json"
    
    # Clean up if exists
    if test_path.exists():
        test_path.unlink()
    
    # Load should return default
    state1 = load_state(test_path)
    assert state1["n"] == 0
    
    # Update and save
    samples = [{"ts": "2025-12-14T17:00:00+00:00", "symbol": "ETHUSDT", "pnl_pct": 0.02, "confidence": 0.7}]
    state1, _ = update_state_with_samples(state1, samples, "2025-12-14T17:00:00+00:00")
    save_state(state1, test_path)
    
    # Load should return saved state
    state2 = load_state(test_path)
    assert state2["n"] == 1
    assert state2["brier_ewma"] > 0
    
    # Clean up
    if test_path.exists():
        test_path.unlink()

