import json
from datetime import datetime, timezone, timedelta

import engine_alpha.risk.recovery_ramp as rr


def _write_json(path, payload):
    path.write_text(json.dumps(payload))


def _write_trades(path, closes):
    with path.open("w", encoding="utf-8") as f:
        for close in closes:
            f.write(json.dumps(close) + "\n")


def _fresh_pf(now, pf_7d=1.0, pf_30d=0.9):
    return {
        "global": {"pf_7d": pf_7d, "pf_30d": pf_30d},
        "meta": {"generated_at": now.isoformat()},
    }


def _make_closes(now, n):
    closes = []
    for i in range(n):
        closes.append(
            {
                "ts": (now - timedelta(hours=i + 1)).isoformat(),
                "type": "close",
                "pct": 0.01,
                "entry_px": 10,
                "exit_px": 10.1,
            }
        )
    return closes


def _setup_paths(tmp_path, now, capital_mode):
    # Capital protection (sets mode)
    cap_path = tmp_path / "capital_protection.json"
    _write_json(cap_path, {"mode": capital_mode})

    # PF timeseries (fresh)
    pf_path = tmp_path / "pf_timeseries.json"
    _write_json(pf_path, _fresh_pf(now))

    # Empty ancillary data
    for name in (
        "risk/quarantine.json",
        "risk/capital_plan.json",
        "risk/live_candidates.json",
        "research/execution_quality.json",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_json(target, {})

    # Recovery ramp state path
    ramp_state = tmp_path / "risk" / "recovery_ramp.json"
    ramp_state.parent.mkdir(parents=True, exist_ok=True)

    return cap_path, pf_path, ramp_state


def _monkeypatch_paths(monkeypatch, tmp_path, cap_path, pf_path, ramp_state, trades_path):
    monkeypatch.setattr(rr, "CAPITAL_PROTECTION_PATH", cap_path)
    monkeypatch.setattr(rr, "PF_TIMESERIES_PATH", pf_path)
    monkeypatch.setattr(rr, "PF_TIMESERIES_ALT_PATH", pf_path)
    monkeypatch.setattr(rr, "QUARANTINE_PATH", tmp_path / "risk" / "quarantine.json")
    monkeypatch.setattr(rr, "CAPITAL_PLAN_PATH", tmp_path / "risk" / "capital_plan.json")
    monkeypatch.setattr(rr, "LIVE_CANDIDATES_PATH", tmp_path / "risk" / "live_candidates.json")
    monkeypatch.setattr(rr, "EXECUTION_QUALITY_PATH", tmp_path / "research" / "execution_quality.json")
    monkeypatch.setattr(rr, "RECOVERY_RAMP_STATE_PATH", ramp_state)
    monkeypatch.setattr(rr, "TRADES_PATH", trades_path)
    monkeypatch.setattr(rr, "CONFIG", tmp_path)  # ensure no custom recovery_min_clean_closes_24h


def test_derisk_allows_five_clean_closes(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    cap_path, pf_path, ramp_state = _setup_paths(tmp_path, now, capital_mode="de_risk")

    trades_path = tmp_path / "trades.jsonl"
    _write_trades(trades_path, _make_closes(now, n=5))

    _monkeypatch_paths(monkeypatch, tmp_path, cap_path, pf_path, ramp_state, trades_path)

    result = rr.evaluate_recovery_ramp(now_iso=now.isoformat())

    assert result["capital_mode"] == "de_risk"
    assert result["metrics"]["min_clean_closes_base"] == 6
    assert result["metrics"]["min_clean_closes_required"] == 5
    assert result["gates"]["clean_closes_pass"] is True


def test_normal_still_requires_base_clean_closes(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    cap_path, pf_path, ramp_state = _setup_paths(tmp_path, now, capital_mode="normal")

    trades_path = tmp_path / "trades.jsonl"
    _write_trades(trades_path, _make_closes(now, n=5))

    _monkeypatch_paths(monkeypatch, tmp_path, cap_path, pf_path, ramp_state, trades_path)

    result = rr.evaluate_recovery_ramp(now_iso=now.isoformat())

    assert result["capital_mode"] == "normal"
    assert result["metrics"]["min_clean_closes_base"] == 6
    assert result["metrics"]["min_clean_closes_required"] == 6
    assert result["gates"]["clean_closes_pass"] is False

