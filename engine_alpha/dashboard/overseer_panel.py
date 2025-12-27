"""
Dashboard panel for Quant Overseer report.
"""

from __future__ import annotations

from pathlib import Path
import json
import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT_DIR / "reports" / "research" / "overseer_report.json"


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


def _status_badge(global_section: dict) -> str:
    if global_section.get("critical"):
        return "🔴 Critical issues present"
    if global_section.get("warnings"):
        return "🟡 Warnings to review"
    return "🟢 Overseer green"


def render() -> None:
    st.title("Quant Overseer")
    report = _load_json(REPORT_PATH)
    if not report:
        st.warning("No overseer report available yet. Run nightly research or `python3 -m tools.overseer_report`.")
        return

    global_section = report.get("global", {})
    st.subheader("Global Status")
    st.info(global_section.get("phase_comment", ""))
    st.success(_status_badge(global_section))

    col1, col2 = st.columns(2)
    with col1:
        st.write("**Tier 1 Assets**")
        st.write(", ".join(global_section.get("tier1_assets", [])) or "Unknown")
    with col2:
        st.write("**Ready for Paper (advisory)**")
        st.write(", ".join(global_section.get("ready_for_paper_promote", [])) or "None")

    st.write("**Ready for Live (advisory)**")
    st.write(", ".join(global_section.get("ready_for_live_promote", [])) or "None")

    assets = report.get("assets", {})
    if assets:
        st.subheader("Assets Overview")
        rows = []
        for symbol, info in assets.items():
            drift_summary = ", ".join(
                f"{reg}:{entry.get('state', 'unknown')}"
                for reg, entry in (info.get("drift_state") or {}).items()
            )
            red_count = len(info.get("red_flags", {}).get("critical", [])) + len(info.get("red_flags", {}).get("warnings", []))
            rows.append(
                {
                    "Symbol": symbol,
                    "Tier": info.get("tier"),
                    "Trading Enabled": info.get("trading_enabled"),
                    "PF": info.get("pf"),
                    "Trades": info.get("total_trades"),
                    "Drift": drift_summary,
                    "Red Flags": red_count,
                    "Comment": info.get("overseer_comment"),
                }
            )
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No per-asset data found in overseer report.")

