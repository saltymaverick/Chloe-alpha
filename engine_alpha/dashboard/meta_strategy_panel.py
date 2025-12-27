"""
Meta-Strategy Reflections Dashboard Panel

Displays Chloe's higher-level strategic thinking and proposed ideas.
"""

from __future__ import annotations

from pathlib import Path
import json
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
META_LOG = RESEARCH_DIR / "meta_strategy_reflections.jsonl"


def _tail_jsonl(path: Path, n: int = 10) -> list:
    """Read last N lines from JSONL file."""
    if not path.exists():
        return []
    
    lines = path.read_text().splitlines()
    out = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def render():
    st.title("Meta-Strategy Reflections")
    st.caption("Chloe's higher-level strategic thinking and proposed ideas")

    if not META_LOG.exists():
        st.info(
            "No meta_strategy_reflections.jsonl found yet. "
            "Run: `python3 -m tools.run_meta_strategy_reflection`"
        )
        return

    reflections = _tail_jsonl(META_LOG, n=10)
    
    if not reflections:
        st.info("No reflections found in log file.")
        return

    st.metric("Total Reflections", len(reflections))

    # Show most recent reflection first
    for i, rec in enumerate(reversed(reflections), 1):
        ts = rec.get("ts", "unknown")
        reflection = rec.get("reflection", {})
        
        with st.expander(f"📅 {ts}", expanded=(i == 1)):
            if isinstance(reflection, dict):
                # Patterns section
                if "patterns" in reflection and reflection["patterns"]:
                    st.subheader("🔍 Patterns Identified")
                    for pattern in reflection["patterns"]:
                        st.markdown(f"**{pattern.get('description', 'N/A')}**")
                        st.caption(f"Evidence: {pattern.get('evidence', 'N/A')}")
                        st.caption(f"Implications: {pattern.get('implications', 'N/A')}")
                        st.markdown("---")
                
                # Strategic ideas section
                if "strategic_ideas" in reflection and reflection["strategic_ideas"]:
                    st.subheader("💡 Strategic Ideas")
                    for idea in reflection["strategic_ideas"]:
                        name = idea.get("name", "Unnamed Idea")
                        priority = idea.get("priority", "medium")
                        
                        # Color code by priority
                        if priority == "high":
                            st.markdown(f"### 🔴 {name} [HIGH PRIORITY]")
                        elif priority == "medium":
                            st.markdown(f"### 🟡 {name} [MEDIUM PRIORITY]")
                        else:
                            st.markdown(f"### 🟢 {name} [LOW PRIORITY]")
                        
                        st.markdown(f"**Intuition:** {idea.get('intuition', 'N/A')}")
                        st.markdown(f"**Conditions:** {idea.get('conditions', 'N/A')}")
                        st.markdown(f"**Implementation Sketch:** {idea.get('sketch', idea.get('implementation_sketch', 'N/A'))}")
                        st.markdown(f"**Risk Considerations:** {idea.get('risk', idea.get('risk_considerations', 'N/A'))}")
                        st.markdown("---")
                
                # Summary
                if "summary" in reflection:
                    st.subheader("📋 Summary")
                    st.info(reflection["summary"])
                
                # Raw JSON view (collapsible)
                with st.expander("🔧 Raw JSON"):
                    st.json(reflection)
            else:
                # Fallback for non-dict reflections
                st.json(reflection)
            
            # Show prompt context (collapsible)
            with st.expander("📝 Prompt Context"):
                prompt = rec.get("prompt", {})
                if isinstance(prompt, dict):
                    st.json(prompt)
                else:
                    st.text(str(prompt))


