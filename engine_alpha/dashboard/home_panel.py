"""
Home Panel — Overview metrics and SWARM status
"""

from __future__ import annotations

from pathlib import Path
import json
import streamlit as st

from engine_alpha.dashboard.components.cards import metric_row

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {}


def render():
    st.title("Chloe — Overview")
    
    pf_path = REPORTS_DIR / "pf_local.json"
    loop_health_path = REPORTS_DIR / "loop_health.json"
    sentinel_path = RESEARCH_DIR / "swarm_sentinel_report.json"
    
    pf = _load_json(pf_path)
    loop_health = _load_json(loop_health_path)
    sentinel = _load_json(sentinel_path)
    
    pf_val = pf.get("pf", pf.get("pf_local", 1.0))
    dd = pf.get("drawdown", 0.0)
    avg_edge = loop_health.get("avg_edge", 0.0)
    blind_spots = loop_health.get("blind_spots", 0)
    
    metric_row(
        [
            {"label": "PF Local", "value": f"{pf_val:.3f}", "help": "Current profit factor"},
            {"label": "Drawdown", "value": f"{dd:.1%}", "help": "Equity drawdown"},
            {"label": "Avg Edge", "value": f"{avg_edge:.5f}", "help": "Weighted expected return"},
            {"label": "Blind Spots", "value": blind_spots, "help": "Open blind-spot alerts"},
        ]
    )
    
    st.subheader("Sentinel Snapshot")
    if sentinel:
        st.json(sentinel)
    else:
        st.info("No sentinel snapshot yet. Run nightly research or sentinel manually.")
    
    st.subheader("Loop Health")
    if loop_health:
        st.json(loop_health)
    else:
        st.info("loop_health.json missing or empty - run nightly research.")

