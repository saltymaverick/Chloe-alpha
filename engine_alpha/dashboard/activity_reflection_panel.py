from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

REFLECTION_LOG = Path("reports/research/activity_reflections.jsonl")


def _load_latest_reflection() -> dict:
    if not REFLECTION_LOG.exists():
        return {}
    try:
        lines = REFLECTION_LOG.read_text().splitlines()
    except Exception:
        return {}
    if not lines:
        return {}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {}


def render() -> None:
    st.header("Activity & Staleness Reflection")

    record = _load_latest_reflection()
    if not record:
        st.info("No activity reflections yet. Run: `python3 -m tools.activity_reflection`.")
        return

    st.markdown(f"**Timestamp:** {record.get('ts', 'unknown')}")
    st.markdown(f"**Phase:** {record.get('phase', 'unknown')}")
    enabled = record.get("enabled_assets", [])
    st.markdown(f"**Enabled assets:** {', '.join(enabled) if enabled else 'None'}")

    st.subheader("Reflection")
    st.write(record.get("reflection", ""))

    raw_context = record.get("raw_context", {})
    st.subheader("Staleness snapshot")
    st.json(raw_context.get("staleness", {}))

