# tools/gpt_quant_analyst.py

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Any, List

import numpy as np

try:
    from openai import OpenAI
except ImportError:
    raise SystemExit("openai package required: pip install openai")


def _load_jsonl(path: Path, max_rows: int | None = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open() as f:
        for i, line in enumerate(f):
            if max_rows is not None and i >= max_rows:
                break
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a compact summary GPT can reason over:
      regime → confidence bin → aggregated stats + feature stats
    """
    bins = np.arange(0.0, 1.0001, 0.05)  # 0.00–1.00 in 0.05 steps

    summary: Dict[str, Any] = {}

    for rec in records:
        regime = rec.get("regime", "unknown")
        conf = float(rec.get("final_conf", 0.0))
        ret = float(rec.get("forward_ret", 0.0))
        feat = rec.get("features", {})

        if regime not in summary:
            summary[regime] = {}

        # Find confidence bin
        idx = int(np.clip(conf / 0.05, 0, len(bins) - 1))
        conf_bin_label = f"{bins[idx]:.2f}-{min(1.0, bins[idx]+0.05):.2f}"

        regime_bucket = summary[regime].setdefault(conf_bin_label, {
            "count": 0,
            "pos": 0,
            "neg": 0,
            "sum_ret": 0.0,
            "sum_ret_pos": 0.0,
            "sum_ret_neg": 0.0,
            "features_mean": {},
        })

        rb = regime_bucket
        rb["count"] += 1
        rb["sum_ret"] += ret
        if ret > 0:
            rb["pos"] += 1
            rb["sum_ret_pos"] += ret
        elif ret < 0:
            rb["neg"] += 1
            rb["sum_ret_neg"] += ret

        for k, v in feat.items():
            if v is None:
                continue
            try:
                v = float(v)
                if np.isnan(v) or np.isinf(v):
                    continue
            except (TypeError, ValueError):
                continue
            
            fm = rb["features_mean"]
            if k not in fm:
                fm[k] = {"sum": 0.0, "count": 0}
            fm[k]["sum"] += v
            fm[k]["count"] += 1

    # Finalize means + PF
    for regime, buckets in summary.items():
        for conf_bin, rb in buckets.items():
            count = rb["count"]
            rb["mean_ret"] = rb["sum_ret"] / count if count > 0 else 0.0
            pos_sum = rb["sum_ret_pos"]
            neg_sum = -rb["sum_ret_neg"]
            if neg_sum > 0:
                rb["pf"] = pos_sum / neg_sum
            else:
                rb["pf"] = float("inf") if pos_sum > 0 else 0.0

            fm = rb["features_mean"]
            rb["features_mean"] = {
                k: (v["sum"] / v["count"] if v["count"] > 0 else None)
                for k, v in fm.items()
            }

    return summary


def _build_prompt(summary: Dict[str, Any]) -> str:
    return (
        "You are a professional quantitative analyst helping tune an algorithmic trader.\n"
        "You are given performance by regime × confidence bin, plus average features.\n"
        "For each regime (trend_down, high_vol, trend_up, chop):\n"
        "- Decide if it should be ENABLED or DISABLED for trading.\n"
        "- Propose a MINIMUM entry confidence threshold (0.35–0.85).\n"
        "- Base this on PF, mean_ret, and count; require at least ~50 samples before trusting.\n"
        "- Favor lower thresholds when PF>1.5 and sample size is good.\n"
        "- Favor higher thresholds or disabling when PF<1.0.\n"
        "- Note any strong feature patterns (e.g. squeeze_on=1, high_vol, etc.) that correlate with good PF.\n\n"
        "SUMMARY JSON (regime → confidence_bin → stats):\n"
        f"{json.dumps(summary, indent=2)}\n\n"
        "Respond ONLY with a JSON object of the form:\n"
        "{\n"
        '  "regimes": {\n'
        '    "trend_down": {\n'
        '      "enable": true,\n'
        '      "entry_min_conf": 0.52,\n'
        '      "notes": "..."\n'
        "    },\n"
        "    ...\n"
        "  }\n"
        "}\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="GPT quant regime & threshold analyst")
    ap.add_argument("--summary-jsonl", help="Optional JSONL input (if using a different format)")
    ap.add_argument("--windows", default="reports/analysis/quant_windows.jsonl")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--config-path", default="config/entry_thresholds.json")
    args = ap.parse_args()

    windows_path = Path(args.windows)
    if not windows_path.exists():
        raise SystemExit(f"Missing windows dataset: {windows_path}")

    records = _load_jsonl(windows_path)
    print(f"Loaded {len(records)} quant windows")

    summary = _summarize(records)
    prompt = _build_prompt(summary)

    # Check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY environment variable not set")

    client = OpenAI(api_key=api_key)

    print("\n=== Calling GPT ===")
    print(f"Model: {args.model}")
    print(f"Prompt length: {len(prompt)} chars")
    
    try:
        resp = client.chat.completions.create(
            model=args.model,
            messages=[
                {"role": "system", "content": "You are a professional quantitative analyst."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,  # Lower temperature for more deterministic analysis
        )
        
        content = resp.choices[0].message.content
    except Exception as e:
        raise SystemExit(f"OpenAI API error: {e}")

    print("\n=== RAW GPT RESPONSE ===\n")
    print(content)

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise SystemExit(f"GPT did not return valid JSON: {e}")

    regimes = data.get("regimes", {})
    if not regimes:
        raise SystemExit("No regimes in GPT response")

    # Load current thresholds
    cfg_path = Path(args.config_path)
    if cfg_path.exists():
        current = json.loads(cfg_path.read_text())
    else:
        current = {
            "trend_down": 0.50,
            "high_vol": 0.55,
            "trend_up": 0.60,
            "chop": 0.65,
        }

    print("\n=== PROPOSED THRESHOLDS ===\n")
    print(f"{'Regime':<12} {'Enable':<8} {'Old':<6} {'New':<6} {'Notes':<40}")
    print("-" * 80)

    new_cfg = dict(current)

    for regime, info in regimes.items():
        enable = bool(info.get("enable", False))
        thr = float(info.get("entry_min_conf", current.get(regime, 0.6)))
        thr = max(0.35, min(0.85, thr))
        notes = info.get("notes", "")[:38]  # Truncate long notes

        old = current.get(regime, None)
        print(f"{regime:<12} {str(enable):<8} {str(old):<6} {thr:<6.2f} {notes:<40}")
        
        if enable:
            new_cfg[regime] = thr
        # If disabled, keep current threshold but note it's disabled

    if args.apply:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(new_cfg, indent=2))
        print(f"\n✅ Updated thresholds written to {cfg_path}")
    else:
        print("\n(Dry run only; pass --apply to write config)")


if __name__ == "__main__":
    main()


