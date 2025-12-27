"""
SWARM Red Flag dashboard panel.
"""

from __future__ import annotations

import json
from pathlib import Path
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
RESEARCH_DIR = ROOT_DIR / "reports" / "research"
RED_FLAG_PATH = RESEARCH_DIR / "swarm_red_flags.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        if not data:
            return {}
        return json.loads(data)
    except Exception:
        return {}


def render() -> None:
    st.title("SWARM Red Flags")
    st.caption("Aggregated health signals from scorecards, drift monitor, and SWARM checks.")

    data = _load_json(RED_FLAG_PATH)
    if not data:
        st.warning("Red-flag data not available yet. Run nightly research to populate this view.")
        return

    has_critical = data.get("has_critical", False)
    warnings = data.get("warnings", [])
    critical = data.get("critical", [])
    info = data.get("info", [])

    if has_critical:
        st.error("🔴 Critical issues detected. See details below.")
    elif warnings:
        st.warning("🟡 Warnings present. Review the items below.")
    else:
        st.success("🟢 All systems nominal.")

    if critical:
        st.subheader("Critical")
        for item in critical:
            st.markdown(f"- {item}")
    if warnings:
        st.subheader("Warnings")
        for item in warnings:
            st.markdown(f"- {item}")
    if info:
        st.subheader("Info")
        for item in info:
            st.markdown(f"- {item}")

