"""
SWARM Panel — Supervisory layer monitoring
"""

from __future__ import annotations

from pathlib import Path
import json
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"

SENTINEL_REPORT_PATH = RESEARCH_DIR / "swarm_sentinel_report.json"
SWARM_AUDIT_LOG = RESEARCH_DIR / "swarm_audit_log.jsonl"
SWARM_RESEARCH_LOG = RESEARCH_DIR / "swarm_research_verifier.jsonl"
CHALLENGER_LOG = RESEARCH_DIR / "swarm_challenger_log.jsonl"


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


def _tail_jsonl(path: Path, n: int = 20) -> list[dict]:
    if not path.exists():
        return []
    
    lines = path.read_text().splitlines()
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def get_swarm_status() -> dict:
    return {
        "sentinel": _load_json(SENTINEL_REPORT_PATH),
        "recent_audits": _tail_jsonl(SWARM_AUDIT_LOG, 10),
        "recent_research_checks": _tail_jsonl(SWARM_RESEARCH_LOG, 10),
        "recent_challenges": _tail_jsonl(CHALLENGER_LOG, 20),
    }


def render():
    st.title("SWARM Supervisory Layer")
    
    status = get_swarm_status()
    
    st.subheader("Sentinel Snapshot")
    if status["sentinel"]:
        st.json(status["sentinel"])
    else:
        st.info("No sentinel snapshot yet.")
    
    st.subheader("Recent Audit Runs")
    if status["recent_audits"]:
        st.json(status["recent_audits"])
    else:
        st.info("No swarm_audit_log.jsonl entries yet.")
    
    st.subheader("Research Verification Checks")
    if status["recent_research_checks"]:
        st.json(status["recent_research_checks"])
    else:
        st.info("No swarm_research_verifier.jsonl entries yet.")
    
    st.subheader("Challenger Decisions")
    if status["recent_challenges"]:
        st.json(status["recent_challenges"])
    else:
        st.info("No challenger logs yet.")
