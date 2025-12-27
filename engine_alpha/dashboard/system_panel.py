"""
System Panel — File freshness and log monitoring
"""

from __future__ import annotations

from pathlib import Path
import os
import time
import streamlit as st
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
LOGS_DIR = ROOT_DIR / "logs"


def _mtime(path: Path) -> str:
    if not path.exists():
        return "missing"
    t = path.stat().st_mtime
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))


def render():
    st.title("System / Files")
    
    st.subheader("Key File Freshness")
    files = {
        "pf_local.json": REPORTS_DIR / "pf_local.json",
        "loop_health.json": REPORTS_DIR / "loop_health.json",
        "hybrid_research_dataset.parquet": RESEARCH_DIR / "hybrid_research_dataset.parquet",
        "multi_horizon_stats.json": RESEARCH_DIR / "multi_horizon_stats.json",
        "strategy_strength.json": RESEARCH_DIR / "strategy_strength.json",
        "swarm_audit_log.jsonl": RESEARCH_DIR / "swarm_audit_log.jsonl",
        "swarm_research_verifier.jsonl": RESEARCH_DIR / "swarm_research_verifier.jsonl",
        "swarm_challenger_log.jsonl": RESEARCH_DIR / "swarm_challenger_log.jsonl",
    }
    
    rows = []
    for name, path in files.items():
        rows.append({"file": name, "path": str(path), "mtime_utc": _mtime(path)})
    
    st.table(pd.DataFrame(rows))
    
    st.subheader("Log Files")
    if LOGS_DIR.exists():
        log_files = list(LOGS_DIR.glob("*.log"))
        if log_files:
            rows = [
                {"file": f.name, "size_kb": f.stat().st_size / 1024.0}
                for f in log_files
            ]
            st.table(pd.DataFrame(rows))
        else:
            st.info("No .log files found in logs/.")
    else:
        st.info("logs/ directory not found.")


