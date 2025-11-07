import json
from pathlib import Path

import pytest

import engine_alpha.loop.portfolio as portfolio


@pytest.fixture
def patched_portfolio(monkeypatch, tmp_path):
    def fake_assets():
        return {
            "symbols": ["SYM1", "SYM2", "SYM3"],
            "correlation": {
                "SYM1": {"SYM2": 1.0, "SYM3": 1.0},
                "SYM2": {"SYM1": 1.0, "SYM3": 1.0},
                "SYM3": {"SYM1": 1.0, "SYM2": 1.0},
            },
            "guard": {"corr_threshold": 0.2, "net_exposure_cap": 1},
        }

    def fake_dir():
        base = tmp_path / "portfolio"
        base.mkdir(parents=True, exist_ok=True)
        return base

    decisions = {
        "final": {"dir": 1, "conf": 0.9},
        "gates": {
            "entry_min_conf": 0.5,
            "exit_min_conf": 0.1,
            "reverse_min_conf": 0.8,
        },
    }

    monkeypatch.setattr(portfolio, "_load_assets", fake_assets)
    monkeypatch.setattr(portfolio, "_portfolio_dir", fake_dir)
    monkeypatch.setattr(portfolio, "get_signal_vector", lambda: {"raw_registry": {}, "signal_vector": []})
    monkeypatch.setattr(portfolio, "decide", lambda *args: decisions)
    return tmp_path


def test_guard_blocks_and_exposure_cap(patched_portfolio):
    result = portfolio.run_portfolio(steps=5)
    assert result["portfolio_pf"] is not None
    health = Path(patched_portfolio / "portfolio" / "portfolio_health.json")
    assert health.exists()
    data = json.loads(health.read_text())
    blocks = data["corr_blocks"] + data["exposure_blocks"]
    assert blocks > 0
    net_exposure = sum(data["open_positions"].values())
    assert abs(net_exposure) <= 1
