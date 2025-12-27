"""
Thresholds & Confidence Explainer — human terms for Chloe's gating logic.
"""

from __future__ import annotations

from pathlib import Path
import json
import streamlit as st
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"

REGIME_DESCRIPTIONS = {
    "high_vol": "Chloe needs extra certainty when volatility is wild.",
    "trend_down": "Used for shorting sharp downtrends.",
    "trend_up": "Used for trading healthy uptrends.",
    "chop": "Range-bound markets. Usually disabled for safety.",
}

BUCKET_NOTES = {
    0: "Bucket 0 = Chloe is guessing. Trades rarely happen here.",
    9: "Bucket 9 = Chloe is very sure. These are rare but powerful signals.",
}


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


def _format_confidence(bucket: int, entry: dict) -> dict:
    exp_ret = entry.get("expected_return")
    count = entry.get("count")
    note = BUCKET_NOTES.get(bucket, "")
    if isinstance(exp_ret, (int, float)):
        exp_display = f"{exp_ret * 100:.2f}%"
    else:
        exp_display = "N/A"
    return {
        "Bucket": bucket,
        "Expected Return": exp_display,
        "Samples": int(count or 0),
        "Interpretation": note or "Chloe's confidence bucket.",
    }


def render() -> None:
    st.title("Thresholds & Confidence")
    st.caption("Plain-English explanation of Chloe's regime gates and confidence buckets.")

    thresholds = _load_json(CONFIG_DIR / "regime_thresholds.json")
    confidence_map = _load_json(CONFIG_DIR / "confidence_map.json")

    if not thresholds:
        st.warning("regime_thresholds.json missing or empty.")
    else:
        st.subheader("Regime Gates")
        rows = []
        for regime, info in thresholds.items():
            enabled = info.get("enabled", False)
            entry_conf = info.get("entry_min_conf", "N/A")
            desc = REGIME_DESCRIPTIONS.get(regime, "Regime.")
            rows.append(
                {
                    "Regime": regime,
                    "Enabled": enabled,
                    "Entry Conf. Needed": entry_conf,
                    "What it means": desc,
                }
            )
        df_regimes = pd.DataFrame(rows)
        st.dataframe(df_regimes, use_container_width=True, hide_index=True)

    if not confidence_map:
        st.warning("confidence_map.json missing or empty.")
        return

    st.subheader("Confidence Buckets (0–9)")
    bucket_rows = []
    for bucket_str, entry in confidence_map.items():
        try:
            bucket = int(bucket_str)
        except ValueError:
            continue
        bucket_rows.append(_format_confidence(bucket, entry))

    df_buckets = pd.DataFrame(bucket_rows).sort_values("Bucket")
    st.dataframe(df_buckets, use_container_width=True, hide_index=True)

    st.info(
        "Confidence buckets tell you how sure Chloe is. "
        "She compares each signal against the regime thresholds before acting."
    )

