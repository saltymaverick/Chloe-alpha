"""
SWARM red-flag aggregation for Ops Mode Plus.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
SCORECARD_DIR = REPORTS_DIR / "scorecards"
CONFIG_DIR = ROOT_DIR / "config"

TIER_MAP = {
    "tier_1": ["MATICUSDT", "BTCUSDT", "AVAXUSDT", "DOGEUSDT"],
    "tier_2": ["XRPUSDT", "SOLUSDT", "ETHUSDT"],
    "tier_3": ["BNBUSDT", "DOTUSDT", "ADAUSDT", "LINKUSDT", "ATOMUSDT"],
}

PRIMARY_REGIME = {
    "BTCUSDT": "high_vol",
    "MATICUSDT": "high_vol",
    "AVAXUSDT": "trend_down",
    "DOGEUSDT": "high_vol",
    "SOLUSDT": "high_vol",
    "XRPUSDT": "high_vol",
    "ETHUSDT": "high_vol",
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


def _tail_jsonl(path: Path, n: int = 1) -> List[dict]:
    if not path.exists():
        return []
    lines = path.read_text().strip().splitlines()
    output: List[dict] = []
    for line in lines[-n:]:
        try:
            output.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return output


def _tier_for(symbol: str) -> int:
    symbol = symbol.upper()
    for idx, tier in enumerate(["tier_1", "tier_2", "tier_3"], start=1):
        if symbol in TIER_MAP[tier]:
            return idx
    return 3


def aggregate_red_flags(
    pf_path: Path = REPORTS_DIR / "pf_local.json",
    asset_scorecards_path: Path = SCORECARD_DIR / "asset_scorecards.json",
    drift_report_path: Path = RESEARCH_DIR / "regime_drift_report.json",
    verifier_log_path: Path = RESEARCH_DIR / "swarm_research_verifier.jsonl",
    output_path: Path = RESEARCH_DIR / "swarm_red_flags.json",
) -> Path:
    """
    Aggregate critical/warning/info flags and write a compact JSON file.
    """
    pf_data = _load_json(pf_path)
    asset_scorecards = _load_json(asset_scorecards_path).get("assets", [])
    asset_map = {row["symbol"]: row for row in asset_scorecards}
    drift_report = _load_json(drift_report_path).get("symbols", {})
    verifier_logs = _tail_jsonl(verifier_log_path, n=1)
    trading_cfg = _load_json(CONFIG_DIR / "trading_enablement.json")
    trading_enabled = set(s.upper() for s in trading_cfg.get("enabled_for_trading", []))

    critical: List[str] = []
    warnings: List[str] = []
    info: List[str] = []

    # Critical PF issues
    for symbol in trading_enabled:
        metrics = asset_map.get(symbol)
        if not metrics:
            continue
        pf_val = metrics.get("pf")
        trades = metrics.get("total_trades", 0)
        if isinstance(pf_val, (int, float)) and pf_val < 0.9 and trades >= 10:
            critical.append(f"{symbol}: PF {pf_val:.2f} with {trades} trades (below 0.90).")

    # Missing hybrid datasets for enabled assets
    for symbol in trading_enabled:
        hybrid_path = RESEARCH_DIR / symbol / "hybrid_research_dataset.parquet"
        if not hybrid_path.exists():
            critical.append(f"{symbol}: hybrid dataset missing ({hybrid_path}).")

    # Verifier issues
    if verifier_logs:
        latest = verifier_logs[-1]
        if not (latest.get("analyzer_ok") and latest.get("strengths_ok") and latest.get("thresholds_ok")):
            critical.append("SWARM verifier detected missing research outputs.")
        else:
            info.append("SWARM verifier: all research outputs present.")

    # PF warnings
    for symbol in trading_enabled:
        metrics = asset_map.get(symbol)
        if not metrics:
            continue
        pf_val = metrics.get("pf")
        trades = metrics.get("total_trades", 0)
        if isinstance(pf_val, (int, float)) and 0.9 <= pf_val < 1.0 and trades >= 10:
            warnings.append(f"{symbol}: PF {pf_val:.2f} trending soft (10+ trades).")
        if trades < 5 and _tier_for(symbol) == 1:
            warnings.append(f"{symbol}: Tier 1 asset has only {trades} trades logged.")

    # Drift warnings for Tier 1 assets
    for symbol in TIER_MAP["tier_1"]:
        regimes = drift_report.get(symbol, {})
        primary = PRIMARY_REGIME.get(symbol)
        if not primary:
            continue
        state = regimes.get(primary, {}).get("state")
        if state == "weakening":
            warnings.append(f"{symbol} {primary} edge weakening per drift monitor.")

    if not critical and not warnings:
        info.append("No red flags detected. Ops green.")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "has_critical": bool(critical),
        "critical": critical,
        "warnings": warnings,
        "info": info,
    }
    output_path.write_text(json.dumps(payload, indent=2))
    return output_path

