import json
from datetime import datetime, timezone, timedelta

import pytest

import engine_alpha.risk.recovery_ramp as rr


def _write_trades(path, trades):
    with open(path, "w", encoding="utf-8") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")


def test_clean_closes_counts_valid_closes(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    # Build mixed closes within 24h
    trades = [
        # valid win
        {"ts": (now - timedelta(hours=1)).isoformat(), "type": "close", "pct": 0.002, "entry_px": 10, "exit_px": 10.02},
        # valid scratch
        {"ts": (now - timedelta(hours=2)).isoformat(), "type": "close", "pct": 0.0, "entry_px": 10, "exit_px": 10.0},
        # valid loss (should count as clean and loss)
        {"ts": (now - timedelta(hours=3)).isoformat(), "type": "close", "pct": -0.003, "entry_px": 10, "exit_px": 9.97},
        # valid near-zero (clean)
        {"ts": (now - timedelta(hours=4)).isoformat(), "type": "close", "pct": 0.0005, "entry_px": 5, "exit_px": 5.0025},
        # corrupt entry (missing exit_px) should be ignored
        {"ts": (now - timedelta(hours=5)).isoformat(), "type": "close", "pct": 0.01, "entry_px": 5},
        # invalid entry_px sentinel should be ignored
        {"ts": (now - timedelta(hours=6)).isoformat(), "type": "close", "pct": 0.01, "entry_px": 1.0, "exit_px": 1.01},
        # valid scratch
        {"ts": (now - timedelta(hours=7)).isoformat(), "type": "close", "pct": 0.0, "entry_px": 7, "exit_px": 7.0},
        # valid loss
        {"ts": (now - timedelta(hours=8)).isoformat(), "type": "close", "pct": -0.002, "entry_px": 8, "exit_px": 7.984},
    ]

    trades_path = tmp_path / "trades.jsonl"
    _write_trades(trades_path, trades)

    monkeypatch.setattr(rr, "TRADES_PATH", trades_path)

    clean, losses, last_ts = rr._load_recent_closes(now, window_hours=24)

    # Clean should include wins, scratches, losses (valid data only)
    assert clean == 6  # two losses + three non-loss valids + one scratch near-zero
    assert losses == 2
    # last_close_ts should be most recent valid close
    assert last_ts is not None
    assert rr._parse_timestamp(last_ts) >= now - timedelta(hours=1, minutes=1)


def test_min_clean_closes_configurable(monkeypatch, tmp_path):
    # Ensure min_clean_closes pulls from config when present
    cfg_path = tmp_path / "engine_config.json"
    cfg_path.write_text(json.dumps({"recovery_min_clean_closes_24h": 4}))
    monkeypatch.setattr(rr, "CONFIG", tmp_path)
    val = rr._load_engine_config().get("recovery_min_clean_closes_24h")
    assert val == 4

