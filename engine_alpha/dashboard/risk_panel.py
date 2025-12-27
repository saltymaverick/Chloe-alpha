"""
Risk Panel — PF, drawdown, exposure, risk multipliers
"""

from __future__ import annotations

from pathlib import Path
import json
import streamlit as st
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
CONFIG_DIR = ROOT_DIR / "config"


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
    st.title("Risk & Exposure")
    
    pf_path = REPORTS_DIR / "pf_local.json"
    loop_health_path = REPORTS_DIR / "loop_health.json"
    gates_path = CONFIG_DIR / "gates.yaml"
    
    pf = _load_json(pf_path)
    loop = _load_json(loop_health_path)
    
    # Try YAML first, then JSON
    gates = {}
    if gates_path.exists():
        try:
            import yaml
            gates = yaml.safe_load(gates_path.read_text()) or {}
        except Exception:
            pass
    
    st.subheader("Core Risk Metrics")
    col1, col2, col3, col4 = st.columns(4)
    
    pf_val = pf.get("pf", pf.get("pf_local", 1.0))
    dd = pf.get("drawdown", 0.0)
    avg_edge = loop.get("avg_edge", 0.0)
    blind_spots = loop.get("blind_spots", 0)
    
    col1.metric("PF Local", f"{pf_val:.3f}")
    col2.metric("Drawdown", f"{dd:.1%}")
    col3.metric("Avg Edge", f"{avg_edge:.5f}")
    col4.metric("Blind Spots", blind_spots)
    
    st.subheader("Profit Amplifier Config")
    pa = gates.get("profit_amplifier", {}) if gates else {}
    if pa:
        st.json(pa)
    else:
        st.info("No Profit Amplifier config in gates.yaml.")
    
    # Optional: exposure summary if you track it
    exposure_path = REPORTS_DIR / "exposure.json"
    st.subheader("Exposure Snapshot")
    if exposure_path.exists():
        exp = _load_json(exposure_path)
        st.json(exp)
    else:
        st.info("No exposure.json found. If desired, log exposure there.")

