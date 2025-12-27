"""
Tests for compression/coil detection primitives.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

try:
    import pytest
except ImportError:
    pytest = None  # Tests can run without pytest if called directly

from engine_alpha.core.compression import (
    bb_width_percent,
    compression_ratio,
    score_compression,
    update_time_in_compression,
    sma,
    stdev,
)


def test_bb_width_percent_constant_returns_zero():
    """Test that BB width % returns ~0 for constant closes."""
    closes = [100.0] * 20
    width = bb_width_percent(closes, n=20)
    
    assert width is not None
    assert abs(width) < 0.001  # Should be essentially zero


def test_compression_ratio_clamps():
    """Test that compression_ratio clamps to [0, 2] and handles None."""
    # Normal case
    ratio1 = compression_ratio(0.5, 1.0)
    assert ratio1 == 0.5
    
    # Clamp high
    ratio2 = compression_ratio(5.0, 1.0)
    assert ratio2 == 2.0
    
    # Clamp low
    ratio3 = compression_ratio(-1.0, 1.0)
    assert ratio3 == 0.0
    
    # None cases
    assert compression_ratio(None, 1.0) is None
    assert compression_ratio(1.0, None) is None
    assert compression_ratio(1.0, 0.0) is None


def test_score_compression_higher_when_ratios_low():
    """Test that score_compression returns higher score when ratios < 1."""
    # Low ratios (more compressed)
    score1 = score_compression(0.5, 0.5)
    assert score1 is not None
    assert score1 > 0.5  # Should be high compression score
    
    # High ratios (less compressed)
    score2 = score_compression(1.5, 1.5)
    assert score2 is not None
    assert score2 < score1  # Should be lower
    
    # None cases
    assert score_compression(None, 0.5) is None
    assert score_compression(0.5, None) is None


def test_update_time_in_compression_entering():
    """Test that entering compression sets entered_ts and time=0."""
    state = {}
    dt1 = datetime.now(timezone.utc)
    ts1 = dt1.isoformat()
    
    # Enter compression
    updated_state, time_s = update_time_in_compression(state, ts1, is_compressed=True, threshold_score=0.6)
    
    assert updated_state["in_compression"] is True
    assert updated_state["entered_ts"] == ts1
    assert time_s == 0.0


def test_update_time_in_compression_staying():
    """Test that staying compressed increases time."""
    dt1 = datetime.now(timezone.utc)
    dt2 = dt1 + timedelta(seconds=100)
    ts1 = dt1.isoformat()
    ts2 = dt2.isoformat()
    
    state = {
        "in_compression": True,
        "entered_ts": ts1,
        "last_ts": ts1,
    }
    
    # Stay compressed
    updated_state, time_s = update_time_in_compression(state, ts2, is_compressed=True, threshold_score=0.6)
    
    assert updated_state["in_compression"] is True
    assert updated_state["entered_ts"] == ts1  # Should not change
    assert time_s is not None
    assert abs(time_s - 100.0) < 1.0  # Should be approximately 100 seconds


def test_update_time_in_compression_leaving():
    """Test that leaving compression resets entered_ts and returns None."""
    dt1 = datetime.now(timezone.utc)
    dt2 = dt1 + timedelta(seconds=50)
    ts1 = dt1.isoformat()
    ts2 = dt2.isoformat()
    
    state = {
        "in_compression": True,
        "entered_ts": ts1,
        "last_ts": ts1,
    }
    
    # Leave compression
    updated_state, time_s = update_time_in_compression(state, ts2, is_compressed=False, threshold_score=0.6)
    
    assert updated_state["in_compression"] is False
    assert updated_state["entered_ts"] is None
    assert time_s is None


def test_sma_basic():
    """Test SMA calculation."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = sma(values, n=5)
    assert result == 3.0
    
    # Insufficient data
    assert sma(values, n=10) is None
    assert sma([], n=5) is None


def test_stdev_basic():
    """Test standard deviation calculation."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = stdev(values, n=5)
    assert result is not None
    assert result > 0
    
    # Insufficient data
    assert stdev(values, n=10) is None
    assert stdev([], n=5) is None

