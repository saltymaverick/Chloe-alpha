"""
MATIC Decisions Panel - Streamlit dashboard for viewing MATIC decision log.
"""

from __future__ import annotations

import streamlit as st
from pathlib import Path
from typing import List, Dict, Any
import re

ROOT_DIR = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT_DIR / "logs" / "matic_decisions.log"


def parse_log_line(line: str) -> Dict[str, Any]:
    """
    Parse a log line into structured fields.
    
    Expected format:
    2025-11-28 02:15:00,123 | symbol=MATICUSDT ts=2025-11-28T02:15:00Z regime=chop dir=0 conf=0.43 edge=-0.000312 decision=BLOCK reason=CHOP_BLOCK
    """
    parts = line.split(" | ", 1)
    if len(parts) != 2:
        return {}
    
    timestamp_str, message = parts
    
    # Parse key=value pairs from message
    fields = {"timestamp": timestamp_str.strip()}
    
    # Extract key=value pairs
    pattern = r'(\w+)=([^\s]+)'
    matches = re.findall(pattern, message)
    
    for key, value in matches:
        # Try to convert numeric values
        if key in ("dir", "conf", "edge"):
            try:
                if "." in value:
                    fields[key] = float(value)
                else:
                    fields[key] = int(value)
            except ValueError:
                fields[key] = value
        else:
            fields[key] = value
    
    return fields


def render() -> None:
    """Render the MATIC Decisions panel."""
    st.header("MATIC Decisions Log")
    st.caption("Every bar evaluation for MATICUSDT, including blocked trades")
    
    if not LOG_PATH.exists():
        st.info("No MATIC decisions logged yet. The log will appear here once Chloe processes MATICUSDT bars.")
        return
    
    # Read log file
    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        st.error(f"Error reading log file: {e}")
        return
    
    if not lines:
        st.info("Log file exists but is empty.")
        return
    
    # Parse lines
    parsed = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parsed_line = parse_log_line(line)
        if parsed_line:
            parsed.append(parsed_line)
    
    if not parsed:
        st.info("No parsable MATIC decisions found in log.")
        return
    
    # Display stats
    total = len(parsed)
    allowed = sum(1 for p in parsed if p.get("decision") == "ALLOW")
    blocked = sum(1 for p in parsed if p.get("decision") == "BLOCK")
    pending = sum(1 for p in parsed if p.get("decision") == "PENDING")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Evaluations", total)
    with col2:
        st.metric("Allowed", allowed)
    with col3:
        st.metric("Blocked", blocked)
    with col4:
        st.metric("Pending", pending)
    
    # Filter options
    st.subheader("Filters")
    col1, col2 = st.columns(2)
    with col1:
        decision_filter = st.selectbox(
            "Decision",
            ["All", "ALLOW", "BLOCK", "PENDING"],
            index=0
        )
    with col2:
        regime_filter = st.selectbox(
            "Regime",
            ["All", "chop", "trend_down", "trend_up", "high_vol", "panic_down"],
            index=0
        )
    
    # Apply filters
    filtered = parsed
    if decision_filter != "All":
        filtered = [p for p in filtered if p.get("decision") == decision_filter]
    if regime_filter != "All":
        filtered = [p for p in filtered if p.get("regime") == regime_filter]
    
    # Display number of lines to show
    num_lines = st.slider("Show last N entries", min_value=10, max_value=min(500, len(filtered)), value=min(100, len(filtered)))
    
    # Show last N entries
    display_lines = filtered[-num_lines:]
    
    if not display_lines:
        st.info("No entries match the selected filters.")
        return
    
    # Create DataFrame for display
    import pandas as pd
    
    df_data = []
    for entry in display_lines:
        df_data.append({
            "Timestamp": entry.get("timestamp", ""),
            "Regime": entry.get("regime", ""),
            "Direction": entry.get("dir", 0),
            "Confidence": entry.get("conf", 0.0),
            "Edge": entry.get("edge", 0.0),
            "Decision": entry.get("decision", ""),
            "Reason": entry.get("reason", ""),
        })
    
    df = pd.DataFrame(df_data)
    
    # Format direction
    if "Direction" in df.columns:
        df["Direction"] = df["Direction"].apply(lambda x: "LONG" if x == 1 else "SHORT" if x == -1 else "FLAT")
    
    # Display table
    st.subheader(f"Recent Decisions (showing {len(display_lines)} of {len(filtered)} filtered)")
    st.dataframe(df, use_container_width=True, hide_index=True)
    
    # Summary by reason
    st.subheader("Block Reasons Summary")
    if blocked > 0:
        reason_counts = {}
        for entry in parsed:
            if entry.get("decision") == "BLOCK":
                reason = entry.get("reason", "UNKNOWN")
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        
        if reason_counts:
            reason_df = pd.DataFrame([
                {"Reason": reason, "Count": count}
                for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1])
            ])
            st.bar_chart(reason_df.set_index("Reason"))
    
    # Download button
    st.download_button(
        "Download Full Log",
        data="\n".join(lines),
        file_name="matic_decisions.log",
        mime="text/plain"
    )

