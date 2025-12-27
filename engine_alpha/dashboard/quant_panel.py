from __future__ import annotations

from pathlib import Path
import json
import streamlit as st
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
CONFIG_DIR = ROOT_DIR / "config"

STRENGTH_PATH = RESEARCH_DIR / "strategy_strength.json"
THRESHOLDS_PATH = CONFIG_DIR / "regime_thresholds.json"
CONF_MAP_PATH = CONFIG_DIR / "confidence_map.json"
CALIB_PATH = RESEARCH_DIR / "confidence_calibration.json"


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


def _interpret_regime(regime: str, info: dict, thr: dict | None) -> str:
    edge = info.get("edge", 0.0)
    strength = info.get("strength", 0.0)
    wN = info.get("weighted_count", 0.0)
    hit = info.get("hit_rate", 0.0)

    enabled = True
    entry_min_conf = None
    if thr is not None:
        enabled = thr.get("enabled", True)
        entry_min_conf = thr.get("entry_min_conf")

    # Simple interpretation
    if wN < 20:
        sample_comment = f"Low sample size ({wN:.1f} weighted). Treat cautiously."
    elif wN < 60:
        sample_comment = f"Moderate sample size ({wN:.1f} weighted)."
    else:
        sample_comment = f"Good sample size ({wN:.1f} weighted)."

    if edge > 0.0:
        edge_comment = f"Positive edge ({edge:+.5f})."
    elif edge < 0.0:
        edge_comment = f"Negative edge ({edge:+.5f})."
    else:
        edge_comment = "No measurable edge."

    if strength > 0.0:
        str_comment = f"Net strength is positive ({strength:+.6f})."
    elif strength < 0.0:
        str_comment = f"Net strength is negative ({strength:+.6f})."
    else:
        str_comment = "Strength neutral."

    if entry_min_conf is None:
        conf_comment = "No regime-specific confidence threshold defined."
    else:
        conf_comment = (
            f"Requires confidence ≥ {entry_min_conf:.2f} to trade this regime."
        )

    enabled_comment = "Regime is ENABLED." if enabled else "Regime is DISABLED."

    return (
        f"{enabled_comment} {edge_comment} {str_comment} "
        f"{sample_comment} {conf_comment}"
    )


def render():
    st.title("Quant View — Regimes & Confidence")

    strengths = _load_json(STRENGTH_PATH)
    thresholds = _load_json(THRESHOLDS_PATH)
    conf_map = _load_json(CONF_MAP_PATH)
    calib = _load_json(CALIB_PATH)

    if not strengths:
        st.warning("No strategy_strength.json found yet. Run nightly research first.")
        return

    st.subheader("Regime Summary")

    rows = []
    for regime, info in strengths.items():
        thr = thresholds.get(regime, {}) if thresholds else {}
        interp = _interpret_regime(regime, info, thr if thr else None)
        rows.append(
            {
                "regime": regime,
                "enabled": thr.get("enabled", True) if thr else True,
                "edge": info.get("edge", 0.0),
                "strength": info.get("strength", 0.0),
                "hit_rate": info.get("hit_rate", 0.0),
                "weighted_count": info.get("weighted_count", 0.0),
                "entry_min_conf": thr.get("entry_min_conf", None),
                "interpretation": interp,
            }
        )

    df = pd.DataFrame(rows)
    st.dataframe(
        df.sort_values("edge", ascending=False),
        use_container_width=True,
    )

    st.markdown("### Human-Readable Regime Interpretation")
    for r in rows:
        st.markdown(
            f"**{r['regime']}** — {r['interpretation']}"
        )

    st.markdown("---")
    st.subheader("Confidence Buckets (Expected Returns)")

    if conf_map:
        c_rows = []
        for b, info in conf_map.items():
            c_rows.append(
                {
                    "bucket": int(b),
                    "conf_min": info.get("conf_range", [0, 0])[0],
                    "conf_max": info.get("conf_range", [0, 0])[1],
                    "expected_return": info.get("expected_return", 0.0),
                    "weighted_count": info.get("weighted_count", 0.0),
                }
            )
        df_cm = pd.DataFrame(c_rows).sort_values("bucket")
        st.dataframe(df_cm, use_container_width=True)
    else:
        st.info("No confidence_map.json yet.")

    st.markdown("---")
    st.subheader("Confidence Calibration (How Trustworthy Is Confidence?)")

    if calib:
        st.json(calib)
        gq = calib.get("global_quality", None)
        if gq is not None:
            st.metric("Global Confidence Quality", f"{gq:.3f}")
            if gq < 0.5:
                st.warning(
                    "Confidence is poorly calibrated right now. Chloe should be cautious."
                )
            elif gq < 0.8:
                st.info("Confidence is moderately calibrated. Still some uncertainty.")
            else:
                st.success("Confidence is well-calibrated. Chloe can trust it more.")
    else:
        st.info(
            "No confidence_calibration.json found yet. Run nightly research with calibration enabled."
        )

