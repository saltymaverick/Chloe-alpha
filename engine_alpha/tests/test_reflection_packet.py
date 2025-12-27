"""
Tests for reflection packet builder.
"""

from __future__ import annotations

try:
    import pytest
except ImportError:
    pytest = None

from engine_alpha.reflect.reflection_packet import build_reflection_packet, summarize_issues


def test_build_reflection_packet_with_minimal_snapshot():
    """Test that packet builds with required keys even if snapshot missing many fields."""
    snapshot = {
        "ts": "2025-12-14T17:00:00+00:00",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "mode": "PAPER",
        "meta": {"tick_id": "test_123"},
        "market": {},
        "decision": {},
        "execution": {},
        "primitives": {},
    }
    
    packet = build_reflection_packet(snapshot)
    
    # Check required keys exist
    assert "ts" in packet
    assert "symbol" in packet
    assert "timeframe" in packet
    assert "primitives" in packet
    assert "meta" in packet
    assert "issues" in packet["meta"]


def test_opportunity_fallback_hydrates_from_opportunity_snapshot(tmp_path, monkeypatch):
    """
    If a writer builds a packet from a snapshot that does not include the
    observer-only opportunity instrumentation, the packet builder should
    hydrate missing fields from reports/opportunity_snapshot.json.
    """
    import json
    import engine_alpha.reflect.reflection_packet as rp

    # Point REPORTS to a temp dir for this test
    monkeypatch.setattr(rp, "REPORTS", tmp_path)

    # Provide an opportunity snapshot with instrumentation
    (tmp_path / "opportunity_snapshot.json").write_text(
        json.dumps(
            {
                "regime": "chop",
                "eligible": False,
                "density_floor": 0.12,
                "events_seen_24h": 123,
                "candidates_seen_24h": 7,
                "eligible_seen_24h": 3,
                "reasons_top": ["execql_hostile"],
                "density_by_regime": {"chop": 0.05},
            }
        )
    )

    # Snapshot is missing most opportunity fields
    snapshot = {
        "ts": "2025-12-14T17:00:00+00:00",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "mode": "PAPER",
        "meta": {"tick_id": "test_opp_fallback"},
        "market": {"ohlcv_is_stale": False},
        "decision": {"action": "HOLD", "confidence": 0.65},
        "execution": {"position": {"is_open": False}},
        "primitives": {
            "opportunity": {
                # Intentionally incomplete
                "eligible": None,
                "regime": "unknown",
            }
        },
    }

    packet = rp.build_reflection_packet(snapshot)
    opp = (packet.get("primitives") or {}).get("opportunity") or {}

    assert opp.get("regime") == "chop"
    assert opp.get("eligible") is False
    assert opp.get("density_floor") == 0.12
    assert opp.get("events_seen_24h") == 123
    assert opp.get("candidates_seen_24h") == 7
    assert opp.get("eligible_seen_24h") == 3
    assert opp.get("reasons_top") == ["execql_hostile"]
    assert opp.get("density_by_regime") == {"chop": 0.05}


def test_build_reflection_packet_with_full_primitives():
    """Test packet includes all B1-B6 primitives when present."""
    snapshot = {
        "ts": "2025-12-14T17:00:00+00:00",
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "mode": "PAPER",
        "meta": {"tick_id": "test_123"},
        "market": {"price": 3000.0, "ohlcv_is_stale": False},
        "decision": {"action": "HOLD", "confidence": 0.65},
        "execution": {"position": {"is_open": False}},
        "primitives": {
            "velocity": {"pci_per_s": 0.001, "confidence_per_s": 0.0005},
            "decay": {"confidence_decayed": 0.60, "confidence_refreshed": True},
            "compression": {"compression_score": 0.5, "is_compressed": False},
            "invalidation": {"thesis_health_score": 0.8, "invalidation_flags": []},
            "opportunity": {"regime": "chop", "eligible": True, "density_ewma": 0.3},
            "self_trust": {"self_trust_score": 0.75, "n_samples": 10},
        },
    }
    
    packet = build_reflection_packet(snapshot)
    
    # Check primitives are included
    assert packet["primitives"]["velocity"]["pci_per_s"] == 0.001
    assert packet["primitives"]["decay"]["confidence_decayed"] == 0.60
    assert packet["primitives"]["compression"]["compression_score"] == 0.5
    assert packet["primitives"]["invalidation"]["thesis_health_score"] == 0.8
    assert packet["primitives"]["opportunity"]["regime"] == "chop"
    assert packet["primitives"]["self_trust"]["self_trust_score"] == 0.75


def test_summarize_issues():
    """Test issue summarization."""
    packet = {
        "market": {"ohlcv_is_stale": True},
        "decision": {"confidence": None},
        "primitives": {
            "opportunity": {"regime": "unknown"},
            "compression": {"compression_score": None},
            "self_trust": {"n_samples": 0},
        },
    }
    
    issues = summarize_issues(packet)
    
    assert "FEED_STALE" in issues
    assert "CONFIDENCE_MISSING" in issues
    assert "REGIME_UNKNOWN" in issues
    assert "COMPRESSION_NULL" in issues
    assert "SELF_TRUST_UNAVAILABLE" in issues

