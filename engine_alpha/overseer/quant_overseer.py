"""
Quant Overseer — read-only governance layer synthesizing Chloe telemetry.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
SCORECARD_DIR = REPORTS_DIR / "scorecards"
CONFIG_DIR = ROOT_DIR / "config"
ASSET_SCORES_PATH = RESEARCH_DIR / "asset_scores.json"

DEFAULT_OUTPUT = RESEARCH_DIR / "overseer_report.json"

TIER_MAP = {
    1: ["MATICUSDT", "BTCUSDT", "AVAXUSDT", "DOGEUSDT"],
    2: ["XRPUSDT", "SOLUSDT", "ETHUSDT"],
    3: ["BNBUSDT", "DOTUSDT", "ADAUSDT", "LINKUSDT", "ATOMUSDT"],
}

PROMO_REQUIREMENTS = {
    "min_trades_live": 20,
    "min_pf_live": 1.05,
}


def load_json_safe(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = path.read_text().strip()
        if not data:
            return {}
        return json.loads(data)
    except Exception:
        return {}


def _tier_for(symbol: str) -> int:
    symbol = symbol.upper()
    for tier, symbols in TIER_MAP.items():
        if symbol in symbols:
            return tier
    return 3


def _phase_comment(phase: str) -> str:
    mapping = {
        "phase_0": "Phase 0: ETH, BTC, SOL, and DOGE trade in paper; all other assets gather research only.",
        "phase_1": "Phase 1: ETH and BTC proving ground; prepping remaining Tier 1 for paper activation.",
        "phase_2": "Phase 2: Tier 1 in paper (BTC→AVAX→DOGE), Tier 2 observation mode. MATIC research-only until feed fixed.",
        "phase_3": "Phase 3: Live trading candidates under evaluation.",
    }
    return mapping.get(phase, f"Operating in {phase}.")


def _redflag_lookup(red_flags: dict) -> Tuple[List[str], List[str]]:
    return red_flags.get("critical", []) or [], red_flags.get("warnings", []) or []


def build_overseer_report(
    trading_enablement_path: Path = CONFIG_DIR / "trading_enablement.json",
    asset_registry_path: Path = CONFIG_DIR / "asset_registry.json",
    asset_scorecards_path: Path = SCORECARD_DIR / "asset_scorecards.json",
    strategy_scorecards_path: Path = SCORECARD_DIR / "strategy_scorecards.json",
    drift_report_path: Path = RESEARCH_DIR / "regime_drift_report.json",
    red_flags_path: Path = RESEARCH_DIR / "swarm_red_flags.json",
    output_path: Path = DEFAULT_OUTPUT,
) -> dict:
    trading_enablement = load_json_safe(trading_enablement_path)
    asset_registry = load_json_safe(asset_registry_path)
    asset_scorecards = load_json_safe(asset_scorecards_path).get("assets", [])
    strategy_scorecards = load_json_safe(strategy_scorecards_path)
    drift_report = load_json_safe(drift_report_path).get("symbols", {})
    red_flags = load_json_safe(red_flags_path)
    asset_scores = load_json_safe(ASSET_SCORES_PATH).get("assets", {})

    phase = trading_enablement.get("phase", "phase_0")
    enabled_symbols = set(s.upper() for s in trading_enablement.get("enabled_for_trading", []))
    asset_map = {row["symbol"]: row for row in asset_scorecards if "symbol" in row}
    strat_overall = strategy_scorecards.get("overall", []) if strategy_scorecards else []
    strat_per_symbol = strategy_scorecards.get("per_symbol", []) if strategy_scorecards else []

    critical_flags, warning_flags = _redflag_lookup(red_flags)

    assets_report = {}
    urgency_ranking: List[Tuple[str, float]] = []
    ready_for_paper: List[str] = []
    ready_for_live: List[str] = []

    for symbol_key, cfg in asset_registry.items():
        symbol = cfg.get("symbol", symbol_key).upper()
        tier = _tier_for(symbol)
        metrics = asset_map.get(symbol, {})
        total_trades = metrics.get("total_trades", 0)
        pf_val = metrics.get("pf")
        drift_states = drift_report.get(symbol, {})

        asset_red_flags = {"critical": [], "warnings": []}
        for flag in critical_flags:
            if symbol in flag:
                asset_red_flags["critical"].append(flag)
        for flag in warning_flags:
            if symbol in flag:
                asset_red_flags["warnings"].append(flag)

        comment_parts = []
        if total_trades < 5:
            comment_parts.append("Too early; gathering sample size.")
        elif isinstance(pf_val, (int, float)) and pf_val < 0.9:
            comment_parts.append("PF below healthy range; keep in observation.")
        elif isinstance(pf_val, (int, float)) and pf_val >= 1.05 and total_trades >= 10:
            comment_parts.append("Showing promising PF; candidate for promotion once stability confirmed.")
            if tier == 1 and symbol not in enabled_symbols:
                ready_for_paper.append(symbol)
            if total_trades >= PROMO_REQUIREMENTS["min_trades_live"]:
                ready_for_live.append(symbol)
        else:
            comment_parts.append("Stable but still under watch.")

        if asset_red_flags["critical"]:
            comment_parts.append("Critical red flags present.")
        elif asset_red_flags["warnings"]:
            comment_parts.append("Warnings logged; monitor closely.")

        score_entry = asset_scores.get(symbol)
        if score_entry:
            urgency_ranking.append((symbol, score_entry.get("urgency", 0.0)))

        assets_report[symbol] = {
            "tier": tier,
            "trading_enabled": symbol in enabled_symbols,
            "pf": pf_val,
            "total_trades": total_trades,
            "max_drawdown": metrics.get("max_drawdown"),
            "most_used_regime": metrics.get("most_used_regime"),
            "most_used_strategy": metrics.get("most_used_strategy"),
            "drift_state": drift_states,
            "red_flags": asset_red_flags,
            "overseer_comment": " ".join(comment_parts),
            "scores": score_entry,
        }

    strategies_report = {}
    strategy_asset_map: Dict[str, Dict[str, dict]] = {}
    for row in strat_per_symbol:
        strat = row.get("strategy", "unknown")
        symbol = row.get("symbol", "UNKNOWN").upper()
        strategy_asset_map.setdefault(strat, {})[symbol] = {
            "pf": row.get("pf"),
            "total_trades": row.get("total_trades"),
        }

    for row in strat_overall:
        strat = row.get("strategy", "unknown")
        pf_val = row.get("pf")
        total_trades = row.get("total_trades", 0)
        if total_trades < 3:
            comment = "Insufficient trades for evaluation."
        elif isinstance(pf_val, (int, float)) and pf_val >= 1.05:
            comment = "Performing well; continue monitoring."
        elif isinstance(pf_val, (int, float)) and pf_val < 0.9:
            comment = "Underperforming; consider dialing back exposure."
        else:
            comment = "Stable but unremarkable performance."

        strategies_report[strat] = {
            "pf": pf_val,
            "total_trades": total_trades,
            "assets": strategy_asset_map.get(strat, {}),
            "overseer_comment": comment,
        }

    urgency_ranking.sort(key=lambda item: item[1], reverse=True)
    top_urgent_assets = [sym for sym, _ in urgency_ranking[:5]]

    global_section = {
        "phase": phase,
        "phase_comment": _phase_comment(phase),
        "tier1_assets": TIER_MAP[1],
        "ready_for_paper_promote": sorted(set(ready_for_paper)),
        "ready_for_live_promote": sorted(set(ready_for_live)),
        "warnings": warning_flags,
        "critical": critical_flags,
        "top_urgent_assets": top_urgent_assets,
    }

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "global": global_section,
        "assets": assets_report,
        "strategies": strategies_report,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2))
    return report

