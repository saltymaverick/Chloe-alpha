"""
Tests for dry-run tuner.
"""

from __future__ import annotations

try:
    import pytest
except ImportError:
    pytest = None

from engine_alpha.reflect.tuner_dryrun import run_tuner_dryrun, load_tuner_config


def test_tuner_dryrun_returns_recommendations_list():
    """Test that tuner returns recommendations list, never applies changes."""
    packet = {
        "ts": "2025-12-14T17:00:00+00:00",
        "primitives": {
            "self_trust": {
                "self_trust_score": 0.40,  # Low
                "overconfidence_ewma": 0.30,  # High
                "n_samples": 20,  # Enough samples
            },
            "invalidation": {
                "invalidation_flags": ["PRICE_AGAINST_POSITION"],
            },
            "opportunity": {
                "density_ewma": 0.05,  # Low
            },
            "compression": {
                "compression_score": 0.75,  # High
            },
            "decay": {
                "confidence_refreshed": False,
                "confidence_decayed": 0.25,  # Low
            },
        },
    }
    
    output = run_tuner_dryrun(packet)
    
    assert "recommendations" in output
    assert isinstance(output["recommendations"], list)
    # Should have at least one recommendation given the test data
    assert len(output["recommendations"]) > 0
    
    # Check recommendation structure
    rec = output["recommendations"][0]
    assert "key" in rec
    assert "current" in rec
    assert "proposed" in rec
    assert "reason" in rec
    assert "confidence" in rec


def test_tuner_dryrun_insufficient_samples():
    """Test that tuner returns empty recommendations when samples < 5."""
    packet = {
        "ts": "2025-12-14T17:00:00+00:00",
        "primitives": {
            "self_trust": {
                "n_samples": 3,  # Insufficient
            },
        },
    }
    
    output = run_tuner_dryrun(packet)
    
    assert output["recommendations"] == []
    assert output["reason"] == "insufficient_samples"


def test_load_tuner_config():
    """Test that tuner config loads with defaults."""
    config = load_tuner_config()
    
    assert "decay" in config
    assert "compression" in config
    assert "opportunity" in config
    assert "self_trust" in config
    
    assert config["decay"]["confidence_half_life_s"] == 1800
    assert config["opportunity"]["min_confidence"] == 0.45

