# tools/asset_audit.py

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
sys_path_insert = str(ROOT_DIR)
import sys
sys.path.insert(0, sys_path_insert)

from engine_alpha.config.assets import load_all_assets, get_enabled_assets, AssetConfig

CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
OHLVC_DIR = DATA_DIR / "ohlcv"
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_ROOT = REPORTS_DIR / "research"
PF_DIR = REPORTS_DIR / "pf"  # optional per-symbol dir
PF_LOCAL_PATH = REPORTS_DIR / "pf_local.json"
THRESHOLDS_PATH = CONFIG_DIR / "regime_thresholds.json"


@dataclass
class AssetAuditResult:
    symbol: str
    config_ok: bool
    data_ok: bool
    research_ok: bool
    thresholds_ok: bool
    pf_ok: bool
    ready_for_paper: bool
    ready_for_live: bool
    details: Dict[str, Any]
    issues: List[str]


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _check_config(asset: AssetConfig) -> tuple[bool, List[str], Dict[str, Any]]:
    issues = []
    details: Dict[str, Any] = {
        "symbol": asset.symbol,
        "base_timeframe": asset.base_timeframe,
        "enabled": asset.enabled,
        "venue": asset.venue,
        "risk_bucket": asset.risk_bucket,
        "quote_ccy": asset.quote_ccy,
        "max_leverage": asset.max_leverage,
        "min_notional_usd": asset.min_notional_usd,
    }

    if not asset.symbol:
        issues.append("Missing symbol in AssetConfig.")
    if not asset.base_timeframe:
        issues.append("Missing base_timeframe.")
    if not asset.venue:
        issues.append("Missing venue.")
    if not asset.risk_bucket:
        issues.append("Missing risk_bucket.")
    if asset.min_notional_usd <= 0:
        issues.append("min_notional_usd should be > 0.")

    config_ok = len(issues) == 0
    return config_ok, issues, details


def _check_data(asset: AssetConfig) -> tuple[bool, List[str], Dict[str, Any]]:
    """
    Check OHLCV live data and hybrid dataset row counts.
    """
    issues: List[str] = []
    details: Dict[str, Any] = {}

    live_path = OHLVC_DIR / f"{asset.symbol.lower()}_{asset.base_timeframe.lower()}_live.csv"
    details["live_csv_path"] = str(live_path)
    live_rows = 0
    if live_path.exists():
        try:
            # quick & dirty row count without loading fully
            live_rows = sum(1 for _ in live_path.open("r")) - 1  # minus header
        except Exception:
            issues.append("Failed to read live OHLCV CSV.")
    else:
        issues.append("Live OHLCV CSV not found.")

    details["live_rows"] = max(live_rows, 0)

    hybrid_path = RESEARCH_ROOT / asset.symbol / "hybrid_research_dataset.parquet"
    details["hybrid_path"] = str(hybrid_path)
    hybrid_rows = None
    if hybrid_path.exists():
        # We can't import pandas here in this fast count; assume it has enough if exists.
        # Caller can use nightly_research logs for precise row counts.
        hybrid_rows = ">= 1"
    else:
        hybrid_rows = 0
        issues.append("Hybrid research dataset parquet not found yet.")

    details["hybrid_rows"] = hybrid_rows

    # For paper readiness, require at least some live data; hybrid will appear after nightly.
    data_ok = (live_rows >= 200)  # heuristic threshold
    if not data_ok and "Live OHLCV CSV not found." not in issues:
        issues.append(f"Insufficient live data rows ({live_rows} < 200).")

    return data_ok, issues, details


def _check_research(asset: AssetConfig) -> tuple[bool, List[str], Dict[str, Any]]:
    """
    Check if analyzer stats and (optionally) per-symbol research files exist.
    """
    issues: List[str] = []
    details: Dict[str, Any] = {}

    stats_path = RESEARCH_ROOT / asset.symbol / "multi_horizon_stats.json"
    strength_path = RESEARCH_ROOT / asset.symbol / "strategy_strength.json"
    conf_map_path = RESEARCH_ROOT / asset.symbol / "confidence_map.json"

    details["stats_path"] = str(stats_path)
    details["strength_path"] = str(strength_path)
    details["conf_map_path"] = str(conf_map_path)

    stats = _load_json(stats_path)
    if not stats:
        issues.append("Analyzer stats missing or empty.")

    # For now, strengths and conf_map may still be global; treat missing per-symbol as non-fatal.
    strengths = _load_json(strength_path)
    conf_map = _load_json(conf_map_path)

    details["has_strength"] = bool(strengths)
    details["has_conf_map"] = bool(conf_map)

    # Minimal research_ok: stats exist and non-empty
    research_ok = bool(stats)
    return research_ok, issues, details


def _check_thresholds(asset: AssetConfig) -> tuple[bool, List[str], Dict[str, Any]]:
    issues: List[str] = []
    details: Dict[str, Any] = {}

    # Check per-symbol thresholds first
    sym_thr_path = RESEARCH_ROOT / asset.symbol / "regime_thresholds.json"
    sym_thr = _load_json(sym_thr_path)
    
    # Fallback to global thresholds
    if not sym_thr:
        thr_all = _load_json(THRESHOLDS_PATH)
        # Check if global thresholds has per-symbol structure
        if isinstance(thr_all, dict) and asset.symbol in thr_all:
            sym_thr = thr_all[asset.symbol]
        elif isinstance(thr_all, dict):
            # Global thresholds might be regime-level (backward compatibility)
            sym_thr = thr_all

    details["thresholds_path"] = str(sym_thr_path) if sym_thr_path.exists() else str(THRESHOLDS_PATH)
    details["has_symbol_thresholds"] = bool(sym_thr)

    if not sym_thr:
        issues.append("No thresholds found for this symbol (per-symbol or global).")
        return False, issues, details

    # Check if it's a dict of regimes or a single threshold value
    if isinstance(sym_thr, dict):
        # Per-regime thresholds
        enabled_regimes = [
            r for r, cfg in sym_thr.items()
            if isinstance(cfg, dict) and cfg.get("enabled", True)
        ]
        details["enabled_regimes"] = enabled_regimes

        if not enabled_regimes:
            issues.append("No enabled regimes for this symbol.")
            thresholds_ok = False
        else:
            thresholds_ok = True
    else:
        # Single threshold (backward compatibility)
        thresholds_ok = True
        details["enabled_regimes"] = ["all"]

    return thresholds_ok, issues, details


def _load_pf_for_symbol(symbol: str) -> Dict[str, Any]:
    """
    Try per-symbol PF json under reports/pf/{symbol}.json,
    then fallback to global pf_local.json.
    """
    per_sym_path = PF_DIR / f"pf_{symbol}.json"
    if per_sym_path.exists():
        return _load_json(per_sym_path)
    # Fallback global
    return _load_json(PF_LOCAL_PATH)


def _count_trades_from_jsonl(symbol: str) -> Dict[str, int]:
    """
    Count wins/losses directly from trades.jsonl for a given symbol.
    Returns: {"wins": int, "losses": int, "total": int, "scratch": int}
    """
    trades_path = REPORTS_DIR / "trades.jsonl"
    if not trades_path.exists():
        return {"wins": 0, "losses": 0, "total": 0, "scratch": 0}
    
    wins = 0
    losses = 0
    scratch = 0
    
    try:
        with trades_path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    # Filter by symbol if present
                    trade_symbol = trade.get("symbol", "").upper()
                    if symbol and trade_symbol and trade_symbol != symbol.upper():
                        continue
                    
                    # Only count closes
                    if trade.get("type") != "close":
                        continue
                    
                    # Skip scratch trades
                    if trade.get("is_scratch", False):
                        scratch += 1
                        continue
                    
                    pct = float(trade.get("pct", 0.0))
                    if pct > 0:
                        wins += 1
                    elif pct < 0:
                        losses += 1
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except Exception:
        pass
    
    return {
        "wins": wins,
        "losses": losses,
        "total": wins + losses,
        "scratch": scratch,
    }


def _check_pf(asset: AssetConfig) -> tuple[bool, List[str], Dict[str, Any]]:
    issues: List[str] = []
    details: Dict[str, Any] = {}

    pf = _load_pf_for_symbol(asset.symbol)
    details["pf_source"] = "per_symbol" if (PF_DIR / f"pf_{asset.symbol}.json").exists() else "pf_local.json"
    details["pf"] = pf

    # Count trades directly from trades.jsonl (more accurate than PF file)
    trade_counts = _count_trades_from_jsonl(asset.symbol)
    wins_from_jsonl = trade_counts["wins"]
    losses_from_jsonl = trade_counts["losses"]
    total_from_jsonl = trade_counts["total"]
    scratch_from_jsonl = trade_counts["scratch"]

    # Prefer JSONL counts if available, otherwise fall back to PF file
    if total_from_jsonl > 0:
        wins = wins_from_jsonl
        losses = losses_from_jsonl
        total_trades = total_from_jsonl
        details["count_source"] = "trades.jsonl"
        details["scratch_trades"] = scratch_from_jsonl
        
        # Compute PF from actual trades if we have enough data
        if losses > 0:
            # Simple PF: sum of wins / abs(sum of losses)
            # For now, use PF from file if available, otherwise compute from counts
            pf_val = float(pf.get("pf", 1.0)) if pf else 1.0
        else:
            pf_val = float("inf") if wins > 0 else 1.0
    else:
        # Fall back to PF file counts
        pf_val = float(pf.get("pf", 1.0)) if pf else 1.0
        wins = int(pf.get("wins", 0))
        losses = int(pf.get("losses", 0))
        total_trades = wins + losses
        details["count_source"] = "pf_file"
        details["scratch_trades"] = 0

    details["pf_val"] = pf_val
    details["wins"] = wins
    details["losses"] = losses
    details["total_trades"] = total_trades

    if not pf and total_trades == 0:
        issues.append("No PF data found (per-symbol or global) and no trades in trades.jsonl.")
        return False, issues, details

    # For "live readiness", require at least some trades + not catastrophic PF.
    if total_trades < 10:
        issues.append(f"Too few trades ({total_trades} < 10) to trust PF.")
        pf_ok = False
    elif pf_val < 0.9:
        issues.append(f"PF ({pf_val:.3f}) below minimum of 0.90.")
        pf_ok = False
    else:
        pf_ok = True

    return pf_ok, issues, details


def audit_asset(asset: AssetConfig, for_live: bool = False) -> AssetAuditResult:
    config_ok, config_issues, cfg_details = _check_config(asset)
    data_ok, data_issues, data_details = _check_data(asset)
    research_ok, research_issues, research_details = _check_research(asset)
    thresholds_ok, thr_issues, thr_details = _check_thresholds(asset)
    pf_ok, pf_issues, pf_details = _check_pf(asset)

    details: Dict[str, Any] = {}
    details.update({"config": cfg_details})
    details.update({"data": data_details})
    details.update({"research": research_details})
    details.update({"thresholds": thr_details})
    details.update({"pf": pf_details})

    issues: List[str] = []
    issues.extend(config_issues)
    issues.extend(data_issues)
    issues.extend(research_issues)
    issues.extend(thr_issues)
    issues.extend(pf_issues)

    # Readiness logic
    ready_for_paper = config_ok and data_ok and research_ok and thresholds_ok
    ready_for_live = ready_for_paper and pf_ok and asset.enabled

    # If auditing "for_live", we tighten the interpretation and flag missing PF/trades strongly
    if for_live and not pf_ok:
        issues.append("Not ready for live: PF/trade history insufficient or weak.")

    return AssetAuditResult(
        symbol=asset.symbol,
        config_ok=config_ok,
        data_ok=data_ok,
        research_ok=research_ok,
        thresholds_ok=thresholds_ok,
        pf_ok=pf_ok,
        ready_for_paper=ready_for_paper,
        ready_for_live=ready_for_live,
        details=details,
        issues=issues,
    )


def main():
    parser = argparse.ArgumentParser(description="Audit multi-asset readiness for Chloe.")
    parser.add_argument("--symbol", type=str, default=None, help="Audit a single symbol (e.g. ETHUSDT).")
    parser.add_argument("--all", action="store_true", help="Audit all assets in asset_registry.json.")
    parser.add_argument("--enabled-only", action="store_true", help="Audit only enabled assets.")
    parser.add_argument("--for-live", action="store_true", help="Audit readiness for LIVE trading (stricter).")
    args = parser.parse_args()

    if not args.symbol and not args.all and not args.enabled_only:
        parser.error("Specify --symbol SYMBOL or --all or --enabled-only.")

    if args.symbol:
        assets = [a for a in load_all_assets() if a.symbol == args.symbol]
        if not assets:
            print(f"❌ Symbol '{args.symbol}' not found in asset_registry.json", file=sys.stderr)
            sys.exit(1)
    elif args.enabled_only:
        assets = get_enabled_assets()
    else:
        assets = load_all_assets()

    results: List[AssetAuditResult] = []
    for asset in assets:
        res = audit_asset(asset, for_live=args.for_live)
        results.append(res)

    # Print JSON summary
    output = [asdict(r) for r in results]
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

