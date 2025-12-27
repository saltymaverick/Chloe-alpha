"""
Research Panel — Strategy strength, confidence map, thresholds
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
    st.title("Research & Learning")
    
    analyzer_path = RESEARCH_DIR / "multi_horizon_stats.json"
    strength_path = RESEARCH_DIR / "strategy_strength.json"
    conf_map_path = CONFIG_DIR / "confidence_map.json"
    thresholds_path = CONFIG_DIR / "entry_thresholds.json"
    
    analyzer = _load_json(analyzer_path)
    strengths = _load_json(strength_path)
    conf_map = _load_json(conf_map_path)
    thresholds = _load_json(thresholds_path)
    
    st.subheader("Strategy Strength")
    if strengths:
        rows = [
            {
                "regime": r,
                "strength": v.get("strength", 0.0),
                "edge": v.get("edge", 0.0),
                "hit_rate": v.get("hit_rate", 0.0),
                "weighted_count": v.get("weighted_count", 0.0),
            }
            for r, v in strengths.items()
        ]
        df = pd.DataFrame(rows)
        st.dataframe(df.sort_values("strength", ascending=False))
    else:
        st.info("No strategy_strength.json yet.")
    
    st.subheader("Regime Thresholds")
    if thresholds:
        df_thr = pd.DataFrame(
            [
                {
                    "regime": r,
                    "entry_min_conf": v if isinstance(v, (int, float)) else v.get("entry_min_conf", None),
                }
                for r, v in thresholds.items()
            ]
        )
        st.dataframe(df_thr)
    else:
        st.info("No entry_thresholds.json yet.")
    
    st.subheader("Confidence Map")
    if conf_map:
        rows = []
        for bucket, info in conf_map.items():
            rows.append(
                {
                    "bucket": int(bucket),
                    "conf_min": info.get("conf_range", [0, 0])[0],
                    "conf_max": info.get("conf_range", [0, 0])[1],
                    "expected_return": info.get("expected_return", 0.0),
                    "weighted_count": info.get("weighted_count", 0.0),
                }
            )
        df_cm = pd.DataFrame(rows).sort_values("bucket")
        st.dataframe(df_cm)
    else:
        st.info("No confidence_map.json yet.")
    
    st.subheader("Analyzer Horizons")
    if analyzer:
        st.json({k: {"stats_count": len(v.get("stats", {}))} for k, v in analyzer.items()})
    else:
        st.info("No multi_horizon_stats.json yet.")

