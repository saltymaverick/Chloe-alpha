from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

META_LOG = Path("reports/research/activity_meta_reflections.jsonl")


def _load_latest_meta() -> dict:
    if not META_LOG.exists():
        return {}
    try:
        lines = META_LOG.read_text().splitlines()
    except Exception:
        return {}
    if not lines:
        return {}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {}


def render() -> None:
    st.header("Meta Activity Reflection")

    record = _load_latest_meta()
    if not record:
        st.info("No meta reflections yet. Run: `python3 -m tools.activity_meta_reflection`.")
        return

    st.markdown(f"**Timestamp:** {record.get('ts', 'unknown')}")
    st.markdown(f"**Phase:** {record.get('phase', 'unknown')}")

    st.subheader("Reflection")
    st.write(record.get("reflection", ""))

    raw_summary = record.get("raw_context_summary", {})
    if raw_summary:
        st.subheader("Context summary")
        st.json(raw_summary)

