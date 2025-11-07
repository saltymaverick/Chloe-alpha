import json
from pathlib import Path

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.trade_analysis import update_pf_reports


def test_update_pf_reports_tmp(tmp_path: Path):
    trades_path = tmp_path / "trades.jsonl"
    trades_path.write_text(
        """
{"event":"OPEN","dir":1}
{"event":"CLOSE","dir":1,"pct":0.02}
{"event":"OPEN","dir":-1}
{"event":"CLOSE","dir":-1,"pct":-0.01}
""".strip()
    )

    pf_local = tmp_path / "pf_local.json"
    pf_live = tmp_path / "pf_live.json"

    update_pf_reports(trades_path, pf_local, pf_live)

    for path in (pf_local, pf_live):
        assert path.exists(), f"Missing report: {path}"
        data = json.loads(path.read_text())
        assert "pf" in data and isinstance(data["pf"], (int, float)), "PF not numeric"
