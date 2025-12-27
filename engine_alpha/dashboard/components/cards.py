"""
Shared card components for dashboard panels
"""

from __future__ import annotations

import streamlit as st


def metric_row(metrics: list[dict]) -> None:
    """
    Render a row of metric cards.
    
    Each metric: {"label": str, "value": Any, "help": str | None}
    """
    cols = st.columns(len(metrics))
    
    for col, m in zip(cols, metrics):
        with col:
            st.metric(m["label"], m["value"])
            if m.get("help"):
                st.caption(m["help"])


