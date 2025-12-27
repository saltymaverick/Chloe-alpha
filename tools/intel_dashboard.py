"""
Strategy Intelligence Dashboard - Unified view of Chloe's research and GPT reasoning.

Consolidates all research outputs into a single, human-readable CLI view.
Read-only and advisory-only.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
GPT_DIR = REPORTS_DIR / "gpt"
CONFIG_DIR = ROOT / "config"
TRADES_PATH = REPORTS_DIR / "trades.jsonl"


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Safely load JSON file, return None if missing or invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _safe_tail_jsonl(path: Path, n: int = 50) -> List[Dict[str, Any]]:
    """Safely tail JSONL file, return list of parsed JSON objects."""
    if not path.exists():
        return []
    try:
        lines = path.read_text().splitlines()
        events = []
        for line in lines[-n:]:
            if line.strip():
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        return events
    except Exception:
        return []


def _fmt_pf(x: Optional[float]) -> str:
    """Format PF value for display (use — if None, never show 999/∞)."""
    if x is None:
        return "—"
    if math.isinf(x) or x >= 999.0:
        return "—"
    return f"{x:.3f}"


def _get(obj: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely descend nested dicts."""
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _now_iso() -> str:
    """Get current ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _count_corrupted_events(window_days: int) -> int:
    """Count corrupted events in the last N days."""
    if not TRADES_PATH.exists():
        return 0
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    count = 0
    
    try:
        with TRADES_PATH.open("r") as f:
            for line in f:
                try:
                    evt = json.loads(line.strip())
                except Exception:
                    continue
                
                # Check timestamp
                ts = evt.get("ts")
                if not ts:
                    continue
                
                try:
                    ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    continue
                
                if ts_dt < cutoff:
                    continue
                
                # Check if corrupted
                if is_corrupted_trade_event(evt):
                    count += 1
    except Exception:
        pass
    
    return count


def load_config() -> Dict[str, Any]:
    """Load engine config to determine mode."""
    config_path = CONFIG_DIR / "engine_config.json"
    if config_path.exists():
        return load_json(config_path)
    return {}


def get_mode() -> str:
    """Get current mode from config or env."""
    config = load_config()
    mode = config.get("mode", "")
    if mode:
        return mode.upper()
    env_mode = os.getenv("MODE", "").upper()
    if env_mode:
        return env_mode
    return "PAPER"


def load_symbol_registry() -> List[str]:
    """Load enabled symbols from registry."""
    registry_path = CONFIG_DIR / "symbols.yaml"
    if not registry_path.exists():
        return []
    try:
        import yaml
        data = yaml.safe_load(registry_path.read_text())
        symbols = data.get("symbols", [])
        return [s.get("id") for s in symbols if s.get("enabled", False)]
    except Exception:
        return []


def get_tier_for_symbol(symbol: str, reflection_output: Dict[str, Any]) -> str:
    """Get tier assignment for a symbol from reflection output."""
    tiers = reflection_output.get("tiers", {})
    for tier_name, symbols_list in tiers.items():
        if symbol in symbols_list:
            return tier_name.replace("tier", "T")
    
    # Try symbol_insights format (v1)
    symbol_insights = reflection_output.get("symbol_insights", {})
    if isinstance(symbol_insights, dict):
        insight = symbol_insights.get(symbol)
        if isinstance(insight, dict):
            tier = insight.get("tier", "")
            if tier:
                return tier.replace("tier", "T")
    
    return "?"


def get_exp_stats(symbol: str, are_snapshot: Dict[str, Any]) -> Tuple[int, Optional[float], Optional[float]]:
    """Get exploration stats (trades, ExpPF, NormPF) for a symbol."""
    symbols_data = are_snapshot.get("symbols", {})
    symbol_data = symbols_data.get(symbol, {})
    
    # Try short horizon first (exploration trades)
    short = symbol_data.get("short", {})
    exp_trades = short.get("exp_trades_count", 0)
    exp_pf = short.get("exp_pf")
    
    # Try medium/long for norm PF
    medium = symbol_data.get("medium", {})
    long_horizon = symbol_data.get("long", {})
    
    norm_pf = medium.get("exp_pf") or long_horizon.get("exp_pf")
    
    return exp_trades, exp_pf, norm_pf


def get_drift_status(symbol: str, drift_report: Dict[str, Any]) -> str:
    """Get drift status for a symbol."""
    symbols_data = drift_report.get("symbols", {})
    symbol_data = symbols_data.get(symbol, {})
    
    # Try both "status" and "drift_state" keys
    drift_state = symbol_data.get("status") or symbol_data.get("drift_state", "unknown")
    
    if drift_state == "improving":
        return "improving"
    elif drift_state == "degrading":
        return "degrading"
    elif drift_state == "stable":
        return "stable"
    elif drift_state == "insufficient_data":
        return "insufficient_data"
    else:
        return "?"


def get_quality_score(symbol: str, quality_scores: Dict[str, Any]) -> Optional[int]:
    """Get quality score for a symbol."""
    # Handle both formats: {symbol: {score: ...}} and {symbols: {symbol: {score: ...}}}
    symbols_data = quality_scores.get("symbols", quality_scores)
    symbol_data = symbols_data.get(symbol, {})
    
    # Try both "score" and "quality_score" keys
    score = symbol_data.get("score") or symbol_data.get("quality_score")
    if score is not None:
        try:
            return int(float(score))  # Handle float scores
        except (TypeError, ValueError):
            return None
    return None


def get_execution_quality_label(symbol: str, execution_quality: Dict[str, Any]) -> Optional[str]:
    """Get execution quality label for a symbol (dominant regime)."""
    data = execution_quality.get("data", {})
    symbol_data = data.get(symbol, {})
    
    if not symbol_data:
        return None
    
    # Find dominant regime (most trades)
    best_regime = None
    best_trades = 0
    
    for regime, regime_data in symbol_data.items():
        trades = regime_data.get("trades", 0)
        if trades > best_trades:
            best_trades = trades
            best_regime = regime_data.get("label")
    
    return best_regime


def format_pf(pf: Optional[float]) -> str:
    """Format PF value for display."""
    if pf is None:
        return "?"
    if pf == float("inf"):
        return "inf"
    return f"{pf:.2f}"


def compute_pf_from_trades() -> Dict[str, Dict[str, Any]]:
    """
    Compute exploration PF and normal PF per symbol from trades.jsonl.
    
    Returns:
      {
        "ETHUSDT": {
          "exploration_pf": float or None,
          "normal_pf": float or None,
          "expl_trades": int,
          "norm_trades": int,
        },
        ...
      }
    """
    pf: Dict[str, Dict[str, Any]] = {}
    
    if not TRADES_PATH.exists():
        return pf
    
    try:
        with TRADES_PATH.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    t = json.loads(line)
                except Exception:
                    continue
                
                # Only process v2 trades with type="close"
                if t.get("logger_version") != "trades_v2":
                    continue
                if t.get("type") != "close":
                    continue
                
                sym = t.get("symbol")
                if not sym:
                    continue
                
                kind = t.get("trade_kind", "normal")
                pct = t.get("pct")
                if pct is None:
                    continue
                try:
                    pct_val = float(pct)
                except Exception:
                    continue
                
                info = pf.setdefault(sym, {
                    "expl_pos": 0.0,
                    "expl_neg": 0.0,
                    "norm_pos": 0.0,
                    "norm_neg": 0.0,
                    "expl_trades": 0,
                    "norm_trades": 0,
                })
                
                if kind == "exploration":
                    info["expl_trades"] += 1
                    if pct_val > 0:
                        info["expl_pos"] += pct_val
                    elif pct_val < 0:
                        info["expl_neg"] += pct_val
                else:
                    info["norm_trades"] += 1
                    if pct_val > 0:
                        info["norm_pos"] += pct_val
                    elif pct_val < 0:
                        info["norm_neg"] += pct_val
    except Exception:
        return pf
    
    # Convert to PFs
    result: Dict[str, Dict[str, Any]] = {}
    for sym, info in pf.items():
        expl_pf = None
        norm_pf = None
        
        # Exploration PF
        if info["expl_neg"] < 0:  # at least one losing trade
            expl_pf = info["expl_pos"] / abs(info["expl_neg"])
        elif info["expl_trades"] > 0 and info["expl_neg"] == 0:
            # All exploration trades winners => PF = inf
            expl_pf = float("inf")
        
        # Normal PF
        if info["norm_neg"] < 0:
            norm_pf = info["norm_pos"] / abs(info["norm_neg"])
        elif info["norm_trades"] > 0 and info["norm_neg"] == 0:
            # All normal trades winners => PF = inf
            norm_pf = float("inf")
        
        result[sym] = {
            "exploration_pf": expl_pf,
            "normal_pf": norm_pf,
            "expl_trades": info["expl_trades"],
            "norm_trades": info["norm_trades"],
        }
    
    return result


def print_header(mode: str, symbol_count: int):
    """Print dashboard header."""
    now = datetime.now(timezone.utc).isoformat()
    print("=" * 70)
    print("CHLOE ALPHA - STRATEGY INTELLIGENCE DASHBOARD")
    print("=" * 70)
    print(f"Time: {now}")
    print(f"Mode: {mode}")
    print(f"Symbols: {symbol_count}")
    print()


def print_symbol_summary(
    symbols: List[str],
    reflection_output: Dict[str, Any],
    are_snapshot: Dict[str, Any],
    drift_report: Dict[str, Any],
    quality_scores: Dict[str, Any],
    execution_quality: Dict[str, Any],
    pf_stats: Dict[str, Dict[str, Any]],
    pf_normalized: Optional[Dict[str, Any]] = None,  # Phase 4k
):
    """Print symbol summary table."""
    print("SYMBOL SUMMARY")
    print("-" * 70)
    print(f"{'Symbol':<10} {'Tier':<5} {'ExpTr':<6} {'ExpPF':<8} {'NormalLanePF':<12} {'Drift':<12} {'Qual':<6} {'ExecQL':<10}")
    print("-" * 70)
    
    for symbol in sorted(symbols):
        tier = get_tier_for_symbol(symbol, reflection_output)
        exp_trades, exp_pf, _ = get_exp_stats(symbol, are_snapshot)
        drift = get_drift_status(symbol, drift_report)
        qual = get_quality_score(symbol, quality_scores)
        exec_ql = get_execution_quality_label(symbol, execution_quality)
        
        # Get NormalLanePF from computed stats (from trades.jsonl)
        stats = pf_stats.get(symbol, {})
        norm_pf = stats.get("normal_pf")
        
        exp_trades_str = str(exp_trades) if exp_trades > 0 else "0"
        exp_pf_str = format_pf(exp_pf)
        
        # Format NormalLanePF safely (handle None and inf)
        if norm_pf is None:
            norm_pf_str = "  —  "
        elif norm_pf == float("inf"):
            norm_pf_str = "  ∞  "
        else:
            norm_pf_str = f"{norm_pf:>10.2f}"
        
        drift_str = drift[:10] if len(drift) > 10 else drift
        qual_str = str(qual) if qual is not None else "?"
        exec_ql_str = exec_ql or "?"
        
        print(f"{symbol:<10} {tier:<5} {exp_trades_str:<6} {exp_pf_str:<8} {norm_pf_str:<12} {drift_str:<12} {qual_str:<6} {exec_ql_str:<10}")
    
    print()
    
    # Phase 4k: Add PF Normalization section
    if pf_normalized:
        symbols_norm = pf_normalized.get("symbols", {})
        if symbols_norm:
            print("PF NORMALIZATION (from pf_normalized.json)")
            print("-" * 70)
            print(f"{'Symbol':<10} {'PF_norm_short':<14} {'PF_norm_long':<14}")
            print("-" * 70)
            for sym in sorted(symbols_norm.keys()):
                info = symbols_norm.get(sym, {})
                norm_short = info.get("short_exp_pf_norm")
                norm_long = info.get("long_exp_pf_norm")
                
                short_str = f"{norm_short:.2f}" if isinstance(norm_short, (int, float)) else "—"
                long_str = f"{norm_long:.2f}" if isinstance(norm_long, (int, float)) else "—"
                
                print(f"{sym:<10} {short_str:<14} {long_str:<14}")
            print()


def print_reflection_snapshot(reflection_output: Dict[str, Any]):
    """Print reflection snapshot (global summary)."""
    print("REFLECTION SNAPSHOT")
    print("-" * 70)
    
    global_summary = reflection_output.get("global_summary", {})
    
    if isinstance(global_summary, dict):
        notes = global_summary.get("notes", [])
        warnings = global_summary.get("warnings", [])
        
        if notes:
            print("Notes:")
            for note in notes:
                print(f"  • {note}")
        
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"  ⚠️  {warning}")
    
    if not global_summary:
        print("No global summary available.")
    
    print()


def print_tuner_proposals(tuner_output: Dict[str, Any]):
    """Print tuner proposals (v4)."""
    print("TUNER PROPOSALS")
    print("-" * 70)
    
    proposals = tuner_output.get("proposals", {})
    if not proposals:
        print("No tuner proposals available.")
        print()
        return
    
    has_proposals = False
    for symbol in sorted(proposals.keys()):
        symbol_props = proposals[symbol]
        if not isinstance(symbol_props, dict):
            continue
        
        conf_delta = symbol_props.get("conf_min_delta", 0.0)
        exp_delta = symbol_props.get("exploration_cap_delta", 0)
        
        # Only show non-zero deltas
        if conf_delta == 0.0 and exp_delta == 0:
            continue
        
        has_proposals = True
        
        conf_str = f"{conf_delta:+.2f}" if conf_delta != 0 else "0.00"
        exp_str = f"{exp_delta:+d}" if exp_delta != 0 else "0"
        
        notes = symbol_props.get("notes", [])
        notes_str = " ".join(notes) if notes else ""
        
        print(f"{symbol}: conf_min_delta={conf_str}, exploration_cap_delta={exp_str}  [{notes_str}]")
    
    if not has_proposals:
        print("No active tuning proposals (all deltas are zero).")
    
    print()


def print_dream_patterns(dream_output: Dict[str, Any]):
    """Print dream patterns (v4)."""
    print("DREAM PATTERNS")
    print("-" * 70)
    
    scenario_reviews = dream_output.get("scenario_reviews", [])
    if not scenario_reviews:
        print("No dream scenario reviews available.")
        print()
        return
    
    # Count scenarios per symbol
    symbol_counts: Dict[str, Dict[str, int]] = {}
    
    for review in scenario_reviews:
        if not isinstance(review, dict):
            continue
        
        symbol = review.get("symbol", "")
        label = review.get("label", "")
        
        if not symbol:
            continue
        
        if symbol not in symbol_counts:
            symbol_counts[symbol] = {"good": 0, "bad": 0, "improve": 0}
        
        if label == "good":
            symbol_counts[symbol]["good"] += 1
        elif label == "bad":
            symbol_counts[symbol]["bad"] += 1
        elif label == "improve":
            symbol_counts[symbol]["improve"] += 1
    
    # Print per-symbol summary
    for symbol in sorted(symbol_counts.keys()):
        counts = symbol_counts[symbol]
        print(f"{symbol}: good={counts['good']}, bad={counts['bad']}, improve={counts['improve']}")
    
    # Print global patterns
    global_summary = dream_output.get("global_summary", {})
    if isinstance(global_summary, dict):
        patterns = global_summary.get("patterns", [])
        warnings = global_summary.get("warnings", [])
        
        if patterns:
            print()
            print("Key Patterns:")
            for pattern in patterns:
                print(f"  • {pattern}")
        
        if warnings:
            print()
            print("Warnings:")
            for warning in warnings:
                print(f"  ⚠️  {warning}")
    
    print()


def print_meta_issues(meta_report: Dict[str, Any]):
    """Print meta-reasoner issues."""
    print("META-REASONER ISSUES")
    print("-" * 70)
    
    issues = meta_report.get("issues", [])
    if not issues:
        print("No meta-reasoner issues detected.")
        print()
        return
    
    for issue in issues:
        issue_type = issue.get("type", "unknown")
        symbol = issue.get("symbol", "")
        details = issue.get("details", "")
        symbols_list = issue.get("symbols", [])
        
        if symbols_list:
            symbols_str = ", ".join(symbols_list)
            print(f"[{issue_type}] {symbols_str}")
        elif symbol:
            print(f"[{issue_type}] {symbol}")
        else:
            print(f"[{issue_type}]")
        
        if details:
            print(f"  • {details}")
    
    # Print recommendations if available
    recommendations = meta_report.get("recommendations", [])
    if recommendations:
        print()
        print("Recommendations:")
        for rec in recommendations:
            print(f"  • {rec}")
    
    print()


def print_footer(
    symbols: List[str],
    reflection_output: Dict[str, Any],
    are_snapshot: Dict[str, Any],
    quality_scores: Dict[str, Any],
    dream_output: Dict[str, Any]
):
    """Print dashboard footer with summary stats."""
    print("SUMMARY")
    print("-" * 70)
    
    # Count tiers
    tiers = reflection_output.get("tiers", {})
    tier1_symbols = tiers.get("tier1", [])
    tier2_symbols = tiers.get("tier2", [])
    tier3_symbols = tiers.get("tier3", [])
    
    print(f"Tier1 symbols ({len(tier1_symbols)}): {', '.join(sorted(tier1_symbols))}")
    print(f"Tier2 symbols ({len(tier2_symbols)}): {', '.join(sorted(tier2_symbols))}")
    print(f"Tier3 symbols ({len(tier3_symbols)}): {', '.join(sorted(tier3_symbols))}")
    print()
    
    # Top 3 by ExpPF
    pf_by_symbol: List[Tuple[str, float]] = []
    for symbol in symbols:
        _, exp_pf, _ = get_exp_stats(symbol, are_snapshot)
        if exp_pf is not None and exp_pf != float("inf"):
            pf_by_symbol.append((symbol, exp_pf))
    
    pf_by_symbol.sort(key=lambda x: x[1], reverse=True)
    
    if pf_by_symbol:
        print("Top Exploration PF:")
        for symbol, pf in pf_by_symbol[:3]:
            print(f"  • {symbol} ({pf:.2f})")
        print()
    
    # Top 3 by quality score
    qual_by_symbol: List[Tuple[str, int]] = []
    for symbol in symbols:
        qual = get_quality_score(symbol, quality_scores)
        if qual is not None:
            qual_by_symbol.append((symbol, qual))
    
    qual_by_symbol.sort(key=lambda x: x[1], reverse=True)
    
    if qual_by_symbol:
        print("Top Quality Scores:")
        for symbol, qual in qual_by_symbol[:3]:
            print(f"  • {symbol} ({qual})")
        print()
    
    # De-risk candidates (Tier3 with bad Dream patterns)
    scenario_reviews = dream_output.get("scenario_reviews", [])
    bad_by_symbol: Dict[str, int] = {}
    
    for review in scenario_reviews:
        if not isinstance(review, dict):
            continue
        symbol = review.get("symbol", "")
        label = review.get("label", "")
        if symbol and label == "bad":
            bad_by_symbol[symbol] = bad_by_symbol.get(symbol, 0) + 1
    
    de_risk_candidates = []
    for symbol in tier3_symbols:
        bad_count = bad_by_symbol.get(symbol, 0)
        _, exp_pf, _ = get_exp_stats(symbol, are_snapshot)
        if bad_count > 0 or (exp_pf is not None and exp_pf < 0.8):
            de_risk_candidates.append(symbol)
    
    if de_risk_candidates:
        print("De-risk candidates:")
        print(f"  • {', '.join(sorted(de_risk_candidates))} (weak PF, poor Dream patterns)")
    
    print()
    print("=" * 70)


def load_last_tuning_reason() -> Optional[Dict[str, Any]]:
    """Load the most recent tuning reason entry from the log."""
    from engine_alpha.logging.tuning_reason_logger import load_last_tuning_reason
    return load_last_tuning_reason()


def load_edge_profiles() -> Dict[str, Dict[str, Any]]:
    """Load symbol edge profiles."""
    from engine_alpha.research.symbol_edge_profiler import load_symbol_edge_profiles
    return load_symbol_edge_profiles()


def load_tuning_advisor() -> Dict[str, Dict[str, Any]]:
    """Load tuning advisor recommendations."""
    from engine_alpha.research.tuning_advisor import load_tuning_advisor
    return load_tuning_advisor()


def load_risk_snapshot() -> Dict[str, Dict[str, Any]]:
    """Load risk snapshot."""
    risk_path = REPORTS_DIR / "risk" / "risk_snapshot.json"
    if not risk_path.exists():
        return {}
    try:
        data = load_json(risk_path)
        if "snapshot" in data:
            return data.get("snapshot", {})
        return data
    except Exception:
        return {}


def load_scm_state() -> Dict[str, Dict[str, Any]]:
    """Load SCM state."""
    from engine_alpha.research.scm_controller import load_scm_state
    return load_scm_state()


def load_liquidity_sweeps() -> Dict[str, Dict[str, Any]]:
    """Load liquidity sweeps data."""
    liq_path = REPORTS_DIR / "research" / "liquidity_sweeps.json"
    if not liq_path.exists():
        return {}
    try:
        data = load_json(liq_path)
        # Handle versioned format
        if "symbols" in data:
            return data.get("symbols", {})
        else:
            return data  # legacy shape
    except Exception:
        return {}


def load_volume_imbalance() -> Dict[str, Dict[str, Any]]:
    """Load volume imbalance data."""
    vi_path = REPORTS_DIR / "research" / "volume_imbalance.json"
    if not vi_path.exists():
        return {}
    try:
        data = load_json(vi_path)
        # Handle versioned format
        if "symbols" in data:
            return data.get("symbols", {})
        else:
            return data  # legacy shape
    except Exception:
        return {}


def load_market_structure() -> Dict[str, Dict[str, Any]]:
    """Load market structure data."""
    ms_path = REPORTS_DIR / "research" / "market_structure.json"
    if not ms_path.exists():
        return {}
    try:
        data = load_json(ms_path)
        # Handle versioned format
        if "symbols" in data:
            return data.get("symbols", {})
        else:
            return data  # legacy shape
    except Exception:
        return {}


def load_breakout_reliability() -> Dict[str, Dict[str, Any]]:
    """Load breakout reliability data."""
    bre_path = REPORTS_DIR / "research" / "breakout_reliability.json"
    if not bre_path.exists():
        return {}
    try:
        data = load_json(bre_path)
        # Handle versioned format
        if "symbols" in data:
            return data.get("symbols", {})
        else:
            return data  # legacy shape
    except Exception:
        return {}


def _load_research_json(path_rel: str) -> Optional[Dict[str, Any]]:
    """Load research JSON file, return None if missing/invalid."""
    p = REPORTS_DIR / path_rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def load_micro_health() -> Optional[Dict[str, Any]]:
    """Load microstructure health."""
    data = _load_research_json("research/microstructure_snapshot_15m.json")
    if not data:
        return None
    return data.get("health")


def load_imbalance_health() -> Optional[Dict[str, Any]]:
    """Load volume imbalance health."""
    data = _load_research_json("research/volume_imbalance.json")
    if not data:
        return None
    return data.get("health")


def load_sweeps_health() -> Optional[Dict[str, Any]]:
    """Load liquidity sweeps health."""
    data = _load_research_json("research/liquidity_sweeps.json")
    if not data:
        return None
    return data.get("health")


def load_mstruct_health() -> Optional[Dict[str, Any]]:
    """Load market structure health."""
    data = _load_research_json("research/market_structure.json")
    if not data:
        return None
    return data.get("health")


def load_breakout_health() -> Optional[Dict[str, Any]]:
    """Load breakout reliability health."""
    data = _load_research_json("research/breakout_reliability.json")
    if not data:
        return None
    return data.get("health")


def load_regime_fusion() -> Dict[str, Dict[str, Any]]:
    """Load regime fusion V2 data."""
    regime_path = REPORTS_DIR / "research" / "regime_fusion.json"
    if not regime_path.exists():
        return {}
    try:
        data = load_json(regime_path)
        # Handle versioned format
        if "symbols" in data:
            return data.get("symbols", {})
        else:
            return data  # legacy shape
    except Exception:
        return {}


def load_confidence_v2() -> Dict[str, Dict[str, Any]]:
    """Load confidence V2 data."""
    conf_path = REPORTS_DIR / "research" / "confidence_v2.json"
    if not conf_path.exists():
        return {}
    try:
        data = load_json(conf_path)
        # Handle versioned format
        if "symbols" in data:
            return data.get("symbols", {})
        else:
            return data  # legacy shape
    except Exception:
        return {}


def print_regime_v2_summary() -> None:
    """Print Regime V2 Summary section."""
    regime_data = load_regime_fusion()
    if not regime_data:
        return
    
    print()
    print("REGIME V2 SUMMARY")
    print("----------------------------------------------------------------------")
    print("Symbol   Regime      Confidence  Inertia  Components")
    print("----------------------------------------------------------------------")
    
    for key in sorted(regime_data.keys()):
        entry = regime_data[key]
        symbol = entry.get("symbol", key.split(":")[0] if ":" in key else key)
        regime = entry.get("fused_label", "unknown")
        conf = entry.get("fused_confidence", 0.0)
        inertia = entry.get("inertia_applied", 0.0)
        components = entry.get("components", [])
        
        comp_str = ", ".join([f"{c.get('name', '?')}={c.get('label', '?')}" for c in components[:2]])
        if len(components) > 2:
            comp_str += "..."
        
        conf_str = f"{conf:.3f}" if conf is not None else " — "
        inertia_str = f"{inertia:.2f}" if inertia is not None else " — "
        
        print(f"{symbol:<8} {regime:<12} {conf_str:<11} {inertia_str:<8} {comp_str}")


def print_confidence_v2_summary() -> None:
    """Print Confidence V2 Decomposition section."""
    conf_data = load_confidence_v2()
    if not conf_data:
        return
    
    print()
    print("CONFIDENCE V2 DECOMPOSITION")
    print("----------------------------------------------------------------------")
    print("Symbol   Overall  PF      Sample  Regime  Stability  Hybrid")
    print("----------------------------------------------------------------------")
    
    for key in sorted(conf_data.keys()):
        entry = conf_data[key]
        symbol = entry.get("symbol", key.split(":")[0] if ":" in key else key)
        overall = entry.get("overall", 0.0)
        components = entry.get("components", {})
        hybrid = entry.get("hybrid_lane", {})
        
        pf = components.get("pf_quality", 0.0)
        sample = components.get("sample_size", 0.0)
        regime = components.get("regime_alignment", 0.0)
        stability = components.get("stability", 0.0)
        boost = hybrid.get("boost", 0.0)
        lane = hybrid.get("lane", "normal")
        
        overall_str = f"{overall:.3f}" if overall is not None else " — "
        pf_str = f"{pf:.3f}" if pf is not None else " — "
        sample_str = f"{sample:.3f}" if sample is not None else " — "
        regime_str = f"{regime:.3f}" if regime is not None else " — "
        stability_str = f"{stability:.3f}" if stability is not None else " — "
        hybrid_str = f"{lane}({boost:+.2f})" if boost is not None else lane
        
        print(f"{symbol:<8} {overall_str:<8} {pf_str:<8} {sample_str:<8} {regime_str:<8} {stability_str:<10} {hybrid_str}")


def load_regime_fusion() -> Dict[str, Dict[str, Any]]:
    """Load regime fusion V2 data."""
    regime_path = REPORTS_DIR / "research" / "regime_fusion.json"
    if not regime_path.exists():
        return {}
    try:
        data = load_json(regime_path)
        # Handle versioned format
        if "symbols" in data:
            return data.get("symbols", {})
        else:
            return data  # legacy shape
    except Exception:
        return {}


def load_confidence_v2() -> Dict[str, Dict[str, Any]]:
    """Load confidence V2 data."""
    conf_path = REPORTS_DIR / "research" / "confidence_v2.json"
    if not conf_path.exists():
        return {}
    try:
        data = load_json(conf_path)
        # Handle versioned format
        if "symbols" in data:
            return data.get("symbols", {})
        else:
            return data  # legacy shape
    except Exception:
        return {}


def print_regime_v2_summary() -> None:
    """Print Regime V2 Summary section."""
    regime_data = load_regime_fusion()
    if not regime_data:
        return
    
    print()
    print("REGIME V2 SUMMARY")
    print("----------------------------------------------------------------------")
    print("Symbol   Regime      Confidence  Inertia  Components")
    print("----------------------------------------------------------------------")
    
    for key in sorted(regime_data.keys()):
        entry = regime_data[key]
        symbol = entry.get("symbol", key.split(":")[0] if ":" in key else key)
        regime = entry.get("fused_label", "unknown")
        conf = entry.get("fused_confidence", 0.0)
        inertia = entry.get("inertia_applied", 0.0)
        components = entry.get("components", [])
        
        comp_str = ", ".join([f"{c.get('name', '?')}={c.get('label', '?')}" for c in components[:2]])
        if len(components) > 2:
            comp_str += "..."
        
        conf_str = f"{conf:.3f}" if conf is not None else " — "
        inertia_str = f"{inertia:.2f}" if inertia is not None else " — "
        
        print(f"{symbol:<8} {regime:<12} {conf_str:<11} {inertia_str:<8} {comp_str}")


def print_confidence_v2_summary() -> None:
    """Print Confidence V2 Decomposition section."""
    conf_data = load_confidence_v2()
    if not conf_data:
        return
    
    print()
    print("CONFIDENCE V2 DECOMPOSITION")
    print("----------------------------------------------------------------------")
    print("Symbol   Overall  PF      Sample  Regime  Stability  Hybrid")
    print("----------------------------------------------------------------------")
    
    for key in sorted(conf_data.keys()):
        entry = conf_data[key]
        symbol = entry.get("symbol", key.split(":")[0] if ":" in key else key)
        overall = entry.get("overall", 0.0)
        components = entry.get("components", {})
        hybrid = entry.get("hybrid_lane", {})
        
        pf = components.get("pf_quality", 0.0)
        sample = components.get("sample_size", 0.0)
        regime = components.get("regime_alignment", 0.0)
        stability = components.get("stability", 0.0)
        boost = hybrid.get("boost", 0.0)
        lane = hybrid.get("lane", "normal")
        
        overall_str = f"{overall:.3f}" if overall is not None else " — "
        pf_str = f"{pf:.3f}" if pf is not None else " — "
        sample_str = f"{sample:.3f}" if sample is not None else " — "
        regime_str = f"{regime:.3f}" if regime is not None else " — "
        stability_str = f"{stability:.3f}" if stability is not None else " — "
        hybrid_str = f"{lane}({boost:+.2f})" if boost is not None else lane
        
        print(f"{symbol:<8} {overall_str:<8} {pf_str:<8} {sample_str:<8} {regime_str:<8} {stability_str:<10} {hybrid_str}")


def print_capital_overview(payload: dict) -> None:
    """
    Capital overview section.

    Extended to include:
      * PF time-series (global)
      * Capital protection mode
      * Suggested withdrawal fraction (future live mode)
    """
    print()
    print("CAPITAL OVERVIEW")
    print("======================================================================")
    print()

    pf_ts = payload.get("pf_timeseries", {})
    cap = payload.get("capital_protection", {})

    global_pf = (pf_ts or {}).get("global", {})
    cap_global = (cap or {}).get("global", {})

    # 1. PF Time-Series Snapshot
    print("1. PF TIME-SERIES (GLOBAL)")
    print("----------------------------------------------------------------------")
    if global_pf:
        pf_1d = global_pf.get("1d", {}).get("pf")
        pf_7d = global_pf.get("7d", {}).get("pf")
        pf_30d = global_pf.get("30d", {}).get("pf")
        pf_90d = global_pf.get("90d", {}).get("pf")
        print(f"  PF_1D : {pf_1d if pf_1d is not None else '—'}")
        print(f"  PF_7D : {pf_7d if pf_7d is not None else '—'}")
        print(f"  PF_30D: {pf_30d if pf_30d is not None else '—'}")
        print(f"  PF_90D: {pf_90d if pf_90d is not None else '—'}")
    else:
        print("  No PF time-series data yet — need more trades.")
    
    # Corrupted events warning
    corrupted_count_7d = _count_corrupted_events(7)
    if corrupted_count_7d > 0:
        print(f"  ⚠️  Corrupted events skipped (last 7d): {corrupted_count_7d}")
    print()

    # 2. Capital Protection Mode
    print("2. CAPITAL PROTECTION MODE")
    print("----------------------------------------------------------------------")
    if cap_global:
        mode = cap_global.get("mode", "unknown")
        pf_7d = cap_global.get("pf_7d")
        pf_30d = cap_global.get("pf_30d")
        loss_streak = cap_global.get("loss_streak")
        sanity_rec = cap_global.get("sanity_rec")
        reasons = cap_global.get("reasons", [])
        actions = cap_global.get("actions", [])

        trades_7d = cap_global.get("trades_7d")  # Phase 4j
        trades_30d = cap_global.get("trades_30d")  # Phase 4j
        
        print(f"  Mode        : {mode}")
        print(f"  PF_7D / 30D : {pf_7d if pf_7d is not None else '—'} / {pf_30d if pf_30d is not None else '—'}")
        print(f"  Trades 7D/30D: {trades_7d if trades_7d is not None else '—'} / {trades_30d if trades_30d is not None else '—'}")  # Phase 4j
        print(f"  Loss streak : {loss_streak if loss_streak is not None else '—'}")
        print(f"  Sanity rec  : {sanity_rec if sanity_rec is not None else '—'}")
        print("  Reasons:")
        for r in reasons:
            print(f"    • {r}")
        print("  Recommended actions:")
        for a in actions:
            print(f"    • {a}")
    else:
        print("  No capital protection data yet — run PF time-series and capital_protection.")
    print()

    # 3. Suggested Withdrawal Plan (future live usage)
    print("3. WITHDRAWAL PLAN (FUTURE LIVE MODE)")
    print("----------------------------------------------------------------------")
    if cap_global and cap_global.get("suggested_withdrawal_fraction", 0.0) > 0.0:
        frac = cap_global["suggested_withdrawal_fraction"]
        print(
            f"  Suggested profit withdrawal fraction: {frac:.0%} of net equity "
            "(once live capital is enabled and PF is confirmed stable)."
        )
    else:
        print("  No withdrawal suggested at this time.")
    print()

    print("======================================================================")
    print("💡 All capital operations are advisory-only and read-only.")
    print("   No real funds have been moved or allocated.")
    print("  [OK] CapitalOverview")


def print_exploration_policy_v3(payload: dict) -> None:
    """
    Phase 3a exploration policy summary.

    This is ADVISORY-ONLY and does not change Chloe's behavior yet.
    """
    policy = payload.get("exploration_policy_v3")
    if not policy:
        return

    symbols = policy.get("symbols", {})
    if not symbols:
        return

    print()
    print("EXPLORATION POLICY V3 (PHASE 3a)")
    print("======================================================================")
    print()
    print("Symbol   Level     Allow  Throttle   PF_7D   PF_30D  Tier    Drift        ExecQL  Hybrid")
    print("----------------------------------------------------------------------")
    for sym in sorted(symbols.keys()):
        entry = symbols[sym]
        level = entry.get("level", "unknown")
        allow = "Y" if entry.get("allow_new_entries") else "N"
        throttle = entry.get("throttle_factor")
        pf_7d = entry.get("pf_7d")
        pf_30d = entry.get("pf_30d")
        tier = entry.get("tier") or "—"
        drift = entry.get("drift") or "—"
        execql = entry.get("exec_quality") or "—"
        hybrid = entry.get("hybrid_lane") or "—"

        def fmt(x: Any) -> str:
            if x is None:
                return "—"
            try:
                return f"{float(x):.3f}"
            except Exception:
                return str(x)

        print(
            f"{sym:<8} {level:<8}  {allow:<5}  {fmt(throttle):<8}  "
            f"{fmt(pf_7d):<6}  {fmt(pf_30d):<7}  {tier:<6}  {drift:<12}  {execql:<7}  {hybrid:<6}"
        )

    print()
    print("Notes:")
    print("  • level=full    → normal exploration intensity")
    print("  • level=reduced → exploration throttled by ~50%")


def print_capital_plan(payload: dict) -> None:
    """
    Print Capital Allocator V1 summary (Phase 4a).
    """
    plan = payload.get("capital_plan")
    if not plan:
        return

    meta = plan.get("meta", {})
    symbols = plan.get("symbols", {})
    top5 = plan.get("marksman_top5", [])

    print()
    print("MARKSMAN CAPITAL ALLOCATION (PHASE 4a)")
    print("======================================================================")
    print(f"Engine      : {meta.get('engine')}")
    print(f"Version     : {meta.get('version')}")
    print(f"GeneratedAt : {meta.get('generated_at')}")
    print()

    if not symbols:
        print("  No capital plan data available.")
        print("======================================================================")
        return

    print("Top 5 Symbols by Score/Weight (Phase 4f: Validity-Capped)")
    print("----------------------------------------------------------------------")
    for sym in top5:
        entry = symbols.get(sym) or {}
        w = entry.get("weight", 0.0)
        raw_w = entry.get("raw_weight", w)  # fallback to weight if raw_weight missing
        score = entry.get("score", 0.0)
        tier = entry.get("tier") or "—"
        drift = entry.get("drift") or "—"
        execql = entry.get("execql") or "—"
        pol = entry.get("policy_level") or "—"
        lane = entry.get("lane_intent") or "—"  # Phase 4h
        cap_ratio = (w / raw_w) if raw_w > 0 else 1.0
        print(
            f"{sym:8s} score={score:.4f} w={w:.3f} raw={raw_w:.3f} cap_adj={cap_ratio:.2f} "
            f"tier={tier:6s} drift={drift:10s} exec={execql:8s} policy={pol:7s} lane={lane:7s}"
        )

    print()
    print("Full capital plan written to: reports/risk/capital_plan.json")
    print("======================================================================")
    print("  • level=blocked → exploration should be disabled for this symbol (advisory).")
    print("  • allow=Y       → symbol is eligible for new exploration entries (in PAPER).")
    print()
    print("======================================================================")


def print_exploit_lane_gate(payload: dict) -> None:
    """
    Print Exploit Lane Gate summary (Phase 4l).
    
    Shows only symbols that fail the gate (would be blocked).
    """
    capital_plan_path = REPORTS_DIR / "risk" / "capital_plan.json"
    capital_protection_path = REPORTS_DIR / "risk" / "capital_protection.json"
    live_candidates_path = REPORTS_DIR / "risk" / "live_candidates.json"
    policy_path = REPORTS_DIR / "research" / "exploration_policy_v3.json"
    
    if not capital_plan_path.exists():
        return
    
    try:
        capital_plan = load_json(capital_plan_path)
        capital_protection = load_json(capital_protection_path)
        live_candidates = load_json(live_candidates_path)
        policy = load_json(policy_path)
    except Exception:
        return
    
    symbols_plan = capital_plan.get("symbols", {})
    if not symbols_plan:
        return
    
    # Get global mode
    global_mode = capital_protection.get("global", {})
    mode = global_mode.get("mode", "unknown")
    
    # Test each symbol with the gate
    blocked_symbols = []
    for symbol in sorted(symbols_plan.keys()):
        try:
            from engine_alpha.risk.exploit_lane_gate import apply_exploit_lane_gate
            
            can_open, decision = apply_exploit_lane_gate(
                symbol=symbol,
                can_open=True,
                is_paper=True,
                is_exploration=False,
            )
            
            if not can_open and decision:
                entry = symbols_plan.get(symbol, {})
                weight = entry.get("weight", 0.0)
                lane_intent = entry.get("lane_intent", "—")
                
                symbols_policy = policy.get("symbols", {})
                symbol_policy = symbols_policy.get(symbol, {})
                policy_level = symbol_policy.get("level", "—")
                
                symbols_lc = live_candidates.get("symbols", {})
                symbol_lc = symbols_lc.get(symbol, {})
                ready_now_raw = symbol_lc.get("ready_now", "—")
                # Normalize ready_now display (handle boolean and string)
                if ready_now_raw is True or ready_now_raw == "Y" or ready_now_raw == "y":
                    ready_now_display = "Y"
                elif ready_now_raw is False or ready_now_raw == "N" or ready_now_raw == "n":
                    ready_now_display = "N"
                else:
                    ready_now_display = str(ready_now_raw) if ready_now_raw != "—" else "—"
                
                blocked_symbols.append({
                    "symbol": symbol,
                    "weight": weight,
                    "lane_intent": lane_intent,
                    "mode": mode,
                    "policy": policy_level,
                    "ready_now": ready_now_display,
                    "reason": decision.reason or "—",
                })
        except Exception:
            # Skip symbols that cause errors
            continue
    
    if not blocked_symbols:
        return  # Don't print section if nothing is blocked
    
    print()
    print("EXPLOIT LANE GATE (Phase 4l)")
    print("======================================================================")
    print("Symbol  Weight  Intent   Mode              Policy    ReadyNow  Reason")
    print("----------------------------------------------------------------------")
    for item in blocked_symbols:
        print(
            f"{item['symbol']:<7} {item['weight']:<7.3f} {item['lane_intent']:<8} "
            f"{item['mode']:<17} {item['policy']:<9} {item['ready_now']:<9} {item['reason']}"
        )
    print("======================================================================")
    print("Note: This gate is PAPER-only and restrictive-only (blocks opens, never enables).")
    print()


def print_exploit_readiness_summary(payload: dict) -> None:
    """
    Print Exploit Readiness Summary (Phase 4L+).
    
    Shows a single-glance answer: "If I went live right now, what would Chloe trade?"
    """
    capital_plan_path = REPORTS_DIR / "risk" / "capital_plan.json"
    capital_protection_path = REPORTS_DIR / "risk" / "capital_protection.json"
    live_candidates_path = REPORTS_DIR / "risk" / "live_candidates.json"
    policy_path = REPORTS_DIR / "research" / "exploration_policy_v3.json"
    
    if not capital_plan_path.exists():
        return
    
    try:
        capital_plan = load_json(capital_plan_path)
        capital_protection = load_json(capital_protection_path)
        live_candidates = load_json(live_candidates_path)
        policy = load_json(policy_path)
    except Exception:
        return
    
    symbols_plan = capital_plan.get("symbols", {})
    if not symbols_plan:
        return
    
    # Get global mode
    global_mode = capital_protection.get("global", {})
    mode = global_mode.get("mode", "(missing data)")
    
    # Evaluate all symbols with exploit gate
    eligible_symbols = []  # lane_intent == "exploit", policy not blocked
    allowed_symbols = []  # passed gate
    blocked_symbols = []  # failed gate with reasons
    
    for symbol in sorted(symbols_plan.keys()):
        entry = symbols_plan.get(symbol, {})
        lane_intent = entry.get("lane_intent")
        weight = entry.get("weight", 0.0)
        
        # Check if eligible (exploit-intent, not blocked by policy)
        symbols_policy = policy.get("symbols", {})
        symbol_policy = symbols_policy.get(symbol, {})
        policy_level = symbol_policy.get("level")
        allow_new_entries = symbol_policy.get("allow_new_entries", True)
        is_policy_blocked = (policy_level == "blocked") or (allow_new_entries is False)
        
        if lane_intent == "exploit" and not is_policy_blocked:
            eligible_symbols.append(symbol)
            
            # Test with gate
            try:
                from engine_alpha.risk.exploit_lane_gate import apply_exploit_lane_gate, is_ready_now
                
                can_open, decision = apply_exploit_lane_gate(
                    symbol=symbol,
                    can_open=True,
                    is_paper=True,
                    is_exploration=False,
                )
                
                symbols_lc = live_candidates.get("symbols", {})
                symbol_lc = symbols_lc.get(symbol, {})
                ready_now_raw = symbol_lc.get("ready_now") or symbol_lc.get("ReadyNow") or symbol_lc.get("ready")
                ready_now = "Y" if is_ready_now(ready_now_raw) else "N"
                
                if can_open:
                    allowed_symbols.append({
                        "symbol": symbol,
                        "weight": weight,
                        "ready_now": ready_now,
                    })
                else:
                    blocked_symbols.append({
                        "symbol": symbol,
                        "weight": weight,
                        "ready_now": ready_now,
                        "reason": decision.reason if decision else "(unknown)",
                    })
            except Exception:
                # Skip symbols that cause errors
                blocked_symbols.append({
                    "symbol": symbol,
                    "weight": weight,
                    "ready_now": "?",
                    "reason": "(gate evaluation failed)",
                })
    
    print()
    print("EXPLOIT READINESS SUMMARY (Phase 4L+)")
    print("======================================================================")
    print(f"Mode            : {mode}")
    print(f"Eligible        : {len(eligible_symbols)}")
    print(f"Allowed         : {len(allowed_symbols)}")
    
    if allowed_symbols:
        allowed_list = ", ".join([item["symbol"] for item in allowed_symbols])
        print(f"Allowed Symbols : {allowed_list}")
    else:
        print("Allowed Symbols : (none)")
    
    print()
    print("Blocked Reasons :")
    if blocked_symbols:
        # Show top blocked symbols (max 10)
        for item in blocked_symbols[:10]:
            print(f" - {item['symbol']}: {item['reason']}")
        if len(blocked_symbols) > 10:
            print(f" ... and {len(blocked_symbols) - 10} more")
    else:
        print(" (none)")
    
    print("======================================================================")
    print()


def print_micro_paper_exploit_status(payload: dict) -> None:
    """
    Print Micro-Paper Exploit Status (Phase 5c).
    """
    print("MICRO-PAPER EXPLOIT STATUS (Phase 5c)")
    print("=" * 80)
    
    enabled = os.getenv("ENABLE_MICRO_PAPER_EXPLOIT", "false").lower() == "true"
    capital_protection = payload.get("capital_protection", {})
    # Extract capital mode (same way as exploit_lane_runner)
    capital_mode = capital_protection.get("mode")
    if not capital_mode:
        global_mode = capital_protection.get("global", {})
        capital_mode = global_mode.get("mode", "unknown")
    
    exploit_state = load_json(REPORTS_DIR / "exploit" / "exploit_state.json")
    exploit_pf = load_json(REPORTS_DIR / "exploit" / "exploit_pf.json")
    exploit_trades_path = REPORTS_DIR / "exploit" / "exploit_trades.jsonl"
    
    print(f"Enabled:        {enabled}")
    print(f"Capital Mode:   {capital_mode}")
    print()
    
    # Open positions
    open_positions = exploit_state.get("open_positions", {})
    print(f"Open Positions: {len(open_positions)}")
    print("-" * 80)
    if open_positions:
        for sym, pos in open_positions.items():
            dir_str = "LONG" if pos.get("direction") == 1 else "SHORT"
            entry_price = pos.get("entry_price", 0)
            notional = pos.get("notional_usd", 0)
            print(f"  {sym:<12} {dir_str:<5} entry={entry_price:.4f} notional=${notional:.2f}")
    else:
        print("  (none)")
    print()
    
    # Exploit PF
    if exploit_pf:
        pf_1d = exploit_pf.get("pf_1d")
        pf_7d = exploit_pf.get("pf_7d")
        pf_30d = exploit_pf.get("pf_30d")
        trades_1d = exploit_pf.get("trades_1d", 0)
        trades_7d = exploit_pf.get("trades_7d", 0)
        trades_30d = exploit_pf.get("trades_30d", 0)
        
        pf1_str = f"{pf_1d:.4f}" if pf_1d else "—"
        pf7_str = f"{pf_7d:.4f}" if pf_7d else "—"
        pf30_str = f"{pf_30d:.4f}" if pf_30d else "—"
        
        print("Exploit PF:")
        print("-" * 80)
        print(f"  PF_1D:  {pf1_str:<10} (trades: {trades_1d})")
        print(f"  PF_7D:  {pf7_str:<10} (trades: {trades_7d})")
        print(f"  PF_30D: {pf30_str:<10} (trades: {trades_30d})")
        print()
    
    # Last trades
    if exploit_trades_path.exists():
        try:
            lines = exploit_trades_path.read_text().splitlines()
            last_trades = []
            for line in reversed(lines[-10:]):
                try:
                    last_trades.append(json.loads(line))
                except Exception:
                    continue
            
            if last_trades:
                print("Last 10 Trades:")
                print("-" * 80)
                print(f"{'Time':<20} {'Symbol':<12} {'Event':<8} {'Notional':<10} {'PnL':<10}")
                print("-" * 80)
                for trade in last_trades[-10:]:
                    ts = trade.get("ts", "")[:19] if trade.get("ts") else ""
                    sym = trade.get("symbol", "")
                    event = trade.get("event", "")
                    notional = trade.get("notional_usd", 0)
                    pnl = trade.get("pnl_usd")
                    pnl_str = f"${pnl:.2f}" if pnl is not None else "—"
                    print(f"{ts:<20} {sym:<12} {event:<8} ${notional:<9.2f} {pnl_str:<10}")
        except Exception:
            pass
    
    print()
    print("=" * 80)
    print()


def print_exploit_param_proposals(payload: dict) -> None:
    """
    Print Exploit Parameter Mutation Proposals.
    """
    print("EXPLOIT PARAM MUTATION (Proposals)")
    print("=" * 80)
    
    proposals_data = load_json(REPORTS_DIR / "evolver" / "exploit_param_proposals.json")
    
    if not proposals_data:
        print("No proposals available.")
        print()
        print("=" * 80)
        print()
        return
    
    capital_mode = proposals_data.get("capital_mode", "unknown")
    summary = proposals_data.get("summary", "")
    proposals = proposals_data.get("proposals", [])
    risk_checks = proposals_data.get("risk_checks", [])
    
    print(f"Capital Mode: {capital_mode}")
    print(f"Summary:      {summary}")
    print()
    
    if proposals:
        print(f"Proposed Changes ({len(proposals)}):")
        print("-" * 80)
        for i, prop in enumerate(proposals, 1):
            param_path = prop.get("param_path", "")
            current = prop.get("current_value")
            proposed = prop.get("proposed_value")
            reason = prop.get("reason", "")
            risk = prop.get("risk_impact", "unknown")
            
            change = proposed - current if (current is not None and proposed is not None) else 0
            change_str = f"{change:+.3f}" if change != 0 else "0"
            
            print(f"[{i}] {param_path}")
            print(f"     {current} → {proposed} ({change_str})")
            print(f"     Reason: {reason}")
            print(f"     Risk:   {risk}")
            print()
    else:
        print("No proposals (no safe improvements identified)")
        print()
    
    if risk_checks:
        print("Risk Checks:")
        print("-" * 80)
        for check in risk_checks:
            print(f"  ✓ {check}")
        print()
    
    print("=" * 80)
    print()


def print_exploit_micro_lane(payload: dict) -> None:
    """
    Print Exploit Micro Lane summary (Phase 5c).
    
    Shows current position, cooldown status, and last events.
    """
    state_path = REPORTS_DIR / "loop" / "exploit_micro_state.json"
    log_path = REPORTS_DIR / "loop" / "exploit_micro_log.jsonl"
    capital_protection_path = REPORTS_DIR / "risk" / "capital_protection.json"
    
    if not state_path.exists() and not log_path.exists():
        return
    
    print()
    print("EXPLOIT MICRO LANE (Phase 5c)")
    print("======================================================================")
    
    # Load state
    state = {}
    if state_path.exists():
        try:
            state = load_json(state_path)
        except Exception:
            pass
    
    # Load capital protection
    capital_protection = {}
    if capital_protection_path.exists():
        try:
            capital_protection = load_json(capital_protection_path)
        except Exception:
            pass
    
    # Extract capital mode (same way as exploit_lane_runner)
    capital_mode = capital_protection.get("mode")
    if not capital_mode:
        global_mode = capital_protection.get("global", {})
        capital_mode = global_mode.get("mode", "unknown")
    
    # Current position
    if state.get("open_position"):
        symbol = state.get("symbol", "unknown")
        side = state.get("side", "unknown")
        entry_ts = state.get("entry_ts", "unknown")
        notional = state.get("notional", 0.0)
        print(f"Position: {symbol} {side.upper()} (entry: {entry_ts[:19]}, notional: ${notional:.2f})")
    else:
        print("Position: None")
    
    # Cooldown
    cooldown_until = state.get("cooldown_until")
    if cooldown_until:
        print(f"Cooldown Until: {cooldown_until[:19]}")
    else:
        print("Cooldown: None")
    
    print(f"Capital Mode: {capital_mode}")
    print()
    
    # Last events
    if log_path.exists():
        try:
            with log_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
                events = []
                for line in lines[-10:]:
                    try:
                        events.append(json.loads(line.strip()))
                    except Exception:
                        continue
                
                if events:
                    print("Last 10 Events:")
                    print("-" * 70)
                    print(f"{'Time':<20} {'Symbol':<12} {'Action':<12} {'Reason'}")
                    print("-" * 70)
                    for event in events[-10:]:
                        ts = event.get("ts", "")[:19] if event.get("ts") else ""
                        sym = event.get("symbol", "")
                        action = event.get("action", "")
                        reason = event.get("reason", "")[:30]
                        print(f"{ts:<20} {sym:<12} {action:<12} {reason}")
                    print()
        except Exception:
            pass
    
    print("======================================================================")
    print()


def print_shadow_exploit_scorecard(payload: dict) -> None:
    """
    Print Shadow Exploit Scorecard (Phase 5b).
    
    Shows global PF metrics and top symbols by shadow performance.
    
    Phase 5H.4: Unified to read from shadow_exploit_pf.json (single source of truth).
    """
    # Phase 5H.4: Read from same source as Shadow PF Display
    pf_path = REPORTS_DIR / "reflect" / "shadow_exploit_pf.json"
    
    if not pf_path.exists():
        return
    
    try:
        pf_data = load_json(pf_path)
    except Exception:
        return
    
    global_pf = pf_data.get("global", {})
    by_symbol = pf_data.get("by_symbol", {})
    
    if not global_pf:
        return
    
    print()
    print("SHADOW EXPLOIT SCORECARD (Phase 5b)")
    print("======================================================================")
    
    # Global metrics (Phase 5H.4: from shadow_exploit_pf.json)
    print("GLOBAL METRICS")
    print("-" * 70)
    pf_1d = global_pf.get("pf_1d")
    pf_7d = global_pf.get("pf_7d")
    pf_30d = global_pf.get("pf_30d")
    trades_1d = global_pf.get("trades_1d", 0)
    trades_7d = global_pf.get("trades_7d", 0)
    trades_30d = global_pf.get("trades_30d", 0)
    
    # Calculate win rate and other metrics from scores file if available (for backward compat)
    scores_path = REPORTS_DIR / "reflect" / "shadow_exploit_scores.json"
    win_rate = 0.0
    mdd = 0.0
    expectancy = 0.0
    if scores_path.exists():
        try:
            scores_data = load_json(scores_path)
            global_metrics = scores_data.get("global", {})
            win_rate = global_metrics.get("win_rate", 0.0)
            mdd = global_metrics.get("max_drawdown_pct", 0.0)
            expectancy = global_metrics.get("expectancy_pct", 0.0)
        except Exception:
            pass
    
    # Phase 5H.4: Format PF values consistently (rounded like 0.9696)
    pf1_str = f"{pf_1d:.4f}" if pf_1d is not None else "—"
    pf7_str = f"{pf_7d:.4f}" if pf_7d is not None else "—"
    pf30_str = f"{pf_30d:.4f}" if pf_30d is not None else "—"
    
    total_trades = trades_30d  # Use 30d as total
    print(f"Total Trades: {total_trades}")
    if win_rate > 0:
        print(f"Win Rate: {win_rate*100:.1f}%")
    print(f"PF_1D:  {pf1_str:<8} (trades: {trades_1d})")
    print(f"PF_7D:  {pf7_str:<8} (trades: {trades_7d})")
    print(f"PF_30D: {pf30_str:<8} (trades: {trades_30d})")
    if mdd > 0:
        print(f"Max DD: {mdd:.2f}%")
    if expectancy != 0:
        print(f"Expectancy: {expectancy:.3f}%")
    print()
    
    # Top symbols by PF_30D (Phase 5H.4: from shadow_exploit_pf.json)
    if by_symbol:
        print("TOP 5 SYMBOLS BY SHADOW PF_30D")
        print("-" * 70)
        print(f"{'Symbol':<10} {'PF_30D':>8} {'Trades':>8} {'MDD%':>6} {'Exp%':>7}")
        print("-" * 70)
        
        sorted_symbols = sorted(
            by_symbol.items(),
            key=lambda x: x[1].get("pf_30d", 0.0),
            reverse=True,
        )[:5]
        
        for symbol, data in sorted_symbols:
            pf_30d = data.get("pf_30d")
            trades = data.get("trades_30d", 0)
            # Try to get MDD/expectancy from scores file if available
            mdd_sym = 0.0
            exp_sym = 0.0
            if scores_path.exists():
                try:
                    scores_data = load_json(scores_path)
                    symbol_data = scores_data.get("by_symbol", {}).get(symbol, {})
                    mdd_sym = symbol_data.get("max_drawdown_pct", 0.0)
                    exp_sym = symbol_data.get("expectancy_pct", 0.0)
                except Exception:
                    pass
            
            pf_str = f"{pf_30d:.4f}" if pf_30d is not None else "—"
            print(f"{symbol:<10} {pf_str:>8} {trades:>8} {mdd_sym:>5.2f}% {exp_sym:>6.3f}%")
    
    print("======================================================================")
    print()


def print_shadow_promotion_candidates(payload: dict) -> None:
    """
    Print Shadow Promotion Candidates (Phase 5b).
    
    Shows promotion-eligible symbols based on shadow performance.
    """
    candidates_path = REPORTS_DIR / "evolver" / "shadow_promotion_candidates.json"
    
    if not candidates_path.exists():
        return
    
    try:
        candidates_data = load_json(candidates_path)
    except Exception:
        return
    
    capital_mode = candidates_data.get("capital_mode", "unknown")
    candidates = candidates_data.get("candidates", [])
    notes = candidates_data.get("notes", [])
    
    if not candidates and not notes:
        return
    
    print()
    print("SHADOW PROMOTION CANDIDATES (Phase 5b)")
    print("======================================================================")
    
    print(f"Capital Mode: {capital_mode}")
    print()
    
    if notes:
        print("Notes:")
        print("-" * 70)
        for note in notes:
            print(f"  • {note}")
        print()
    
    if candidates:
        print(f"ELIGIBLE CANDIDATES ({len(candidates)})")
        print("-" * 70)
        print(
            f"{'Symbol':<10} {'Composite':>10} {'PF_30D':>8} {'PF_7D':>8} "
            f"{'Trades':>8} {'MDD%':>6} {'Validity':>8}"
        )
        print("-" * 70)
        
        for cand in candidates[:10]:  # Top 10
            symbol = cand.get("symbol", "")
            composite = cand.get("composite", 0.0)
            metrics = cand.get("metrics", {})
            # Use pf_display (never raw) for dashboard display
            pf_30d = metrics.get("shadow_pf_30d")  # Already from promotion gate (uses display)
            pf_7d = metrics.get("shadow_pf_7d")  # Already from promotion gate (uses display)
            trades_30d = metrics.get("shadow_trades_30d", 0)
            mdd = metrics.get("max_drawdown_pct", 0.0)
            validity = metrics.get("pf_validity", 0.0)
            
            pf30_str = f"{pf_30d:.3f}" if pf_30d else "—"
            pf7_str = f"{pf_7d:.3f}" if pf_7d else "—"
            
            print(
                f"{symbol:<10} {composite:>10.3f} {pf30_str:>8} {pf7_str:>8} "
                f"{trades_30d:>8} {mdd:>5.2f}% {validity:>7.2f}"
            )
    else:
        print("NO ELIGIBLE CANDIDATES")
        print("-" * 70)
        print("No symbols meet all promotion criteria.")
    
    print("======================================================================")
    print()


def print_shadow_exploit_lane(payload: dict) -> None:
    """
    Print Shadow Exploit Lane summary (Phase 5a).
    
    Shows shadow position state, recent events, and shadow PF.
    """
    log_path = REPORTS_DIR / "reflect" / "shadow_exploit_log.jsonl"
    state_path = REPORTS_DIR / "reflect" / "shadow_exploit_state.json"
    pf_path = REPORTS_DIR / "reflect" / "shadow_exploit_pf.json"
    
    if not log_path.exists() and not state_path.exists():
        return
    
    print()
    print("SHADOW EXPLOIT LANE (Phase 5a)")
    print("======================================================================")
    
    # Load shadow state
    positions = {}
    if state_path.exists():
        try:
            state_data = load_json(state_path)
            positions = state_data.get("positions", {})
        except Exception:
            pass
    
    # Load last events
    events = []
    if log_path.exists():
        try:
            with log_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-10:]:
                    try:
                        events.append(json.loads(line.strip()))
                    except Exception:
                        continue
        except Exception:
            pass
    
    # Load PF snapshot
    pf_data = {}
    if pf_path.exists():
        try:
            pf_data = load_json(pf_path)
        except Exception:
            pass
    
    # Show open positions
    if positions:
        print("Open Shadow Positions:")
        print("-" * 70)
        for sym, pos in list(positions.items())[:5]:
            dir_str = "LONG" if pos.get("direction", 0) == 1 else "SHORT"
            entry_px = pos.get("entry_price", 0.0)
            bars = pos.get("bars_open", 0)
            print(f"  {sym:<12} {dir_str:<5} entry={entry_px:.4f} bars={bars}")
        if len(positions) > 5:
            print(f"  ... and {len(positions) - 5} more")
        print()
    
    # Show last events
    if events:
        print("Last 10 Events:")
        print("-" * 70)
        print(f"{'Time':<20} {'Symbol':<12} {'Action':<12} {'Reason'}")
        print("-" * 70)
        for event in events[-10:]:
            ts = event.get("ts", "")[:19] if event.get("ts") else ""
            sym = event.get("symbol", "")
            action = event.get("action", "")
            reason = event.get("reason", "")[:30]
            print(f"{ts:<20} {sym:<12} {action:<12} {reason}")
        print()
    
    # Show PF snapshot (Phase 5H.4: read from shadow_exploit_pf.json as single source of truth)
    if pf_data:
        # Read from global section (matching scorer output structure)
        global_pf = pf_data.get("global", {})
        pf_1d = global_pf.get("pf_1d")
        pf_7d = global_pf.get("pf_7d")
        pf_30d = global_pf.get("pf_30d")
        trades_1d = global_pf.get("trades_1d", 0)
        trades_7d = global_pf.get("trades_7d", 0)
        trades_30d = global_pf.get("trades_30d", 0)
        generated_at = pf_data.get("generated_at") or pf_data.get("ts")
        
        # Format PF values
        pf_1d_str = f"{pf_1d:.4f}" if pf_1d is not None else "—"
        pf_7d_str = f"{pf_7d:.4f}" if pf_7d is not None else "—"
        pf_30d_str = f"{pf_30d:.4f}" if pf_30d is not None else "—"
        
        print("Shadow PF:")
        print("-" * 70)
        print(f"  PF_1D:  {pf_1d_str:<20} (trades: {trades_1d})")
        print(f"  PF_7D:  {pf_7d_str:<20} (trades: {trades_7d})")
        print(f"  PF_30D: {pf_30d_str:<20} (trades: {trades_30d})")
        if generated_at:
            gen_ts = generated_at[:19] if isinstance(generated_at, str) else str(generated_at)[:19]
            print(f"  Generated: {gen_ts}")
        
        # Compare with real PF if available
        pf_ts_path = REPORTS_DIR / "pf" / "pf_timeseries.json"
        if pf_ts_path.exists():
            try:
                pf_ts = load_json(pf_ts_path)
                global_ts = pf_ts.get("global", {})
                real_pf_7d = global_ts.get("7d", {}).get("pf")
                real_pf_30d = global_ts.get("30d", {}).get("pf")
                
                if real_pf_7d is not None or real_pf_30d is not None:
                    print()
                    print("Shadow vs Real PF:")
                    print("-" * 70)
                    if pf_7d is not None and real_pf_7d is not None:
                        diff_7d = pf_7d - real_pf_7d
                        print(f"  PF_7D:  shadow={pf_7d:.4f} vs real={real_pf_7d:.4f} (diff={diff_7d:+.4f})")
                    if pf_30d is not None and real_pf_30d is not None:
                        diff_30d = pf_30d - real_pf_30d
                        print(f"  PF_30D: shadow={pf_30d:.4f} vs real={real_pf_30d:.4f} (diff={diff_30d:+.4f})")
            except Exception:
                pass
    else:
        # Phase 5H.4: File missing or malformed
        print("Shadow PF:")
        print("-" * 70)
        print("  PF_1D:  —")
        print("  PF_7D:  —")
        print("  PF_30D: —")
        print("  Note: shadow_pf_unavailable")
    
    print("======================================================================")
    print("Note: Shadow lane is PAPER-only, read-only, and never places orders.")
    print()


def print_exploit_arming_status() -> None:
    """
    Print Exploit Auto-Arming Status (Phase 5d).
    
    Shows the current arming state and reasons.
    """
    arming_path = REPORTS_DIR / "loop" / "exploit_arming.json"
    
    if not arming_path.exists():
        print("EXPLOIT AUTO-ARMING STATUS (Phase 5d)")
        print("=" * 70)
        print("Status: missing (run exploit_arming engine)")
        print("=" * 70)
        print()
        return
    
    try:
        arming_data = load_json(arming_path)
    except Exception:
        print("EXPLOIT AUTO-ARMING STATUS (Phase 5d)")
        print("=" * 70)
        print("Status: error loading state")
        print("=" * 70)
        print()
        return
    
    print("EXPLOIT AUTO-ARMING STATUS (Phase 5d)")
    print("=" * 70)
    
    operator_enabled = arming_data.get("operator_enabled", False)
    capital_mode = arming_data.get("capital_mode", "unknown")
    armed = arming_data.get("armed", False)
    arm_score = arming_data.get("arm_score", 0.0)
    consecutive_ok = arming_data.get("consecutive_ok_ticks", 0)
    disarm_reason = arming_data.get("disarm_reason")
    eligible_symbols = arming_data.get("eligible_symbols", [])
    armed_since = arming_data.get("armed_since")
    
    # Get promotion mode from promotion_gate.json (not stored in arming state)
    promotion_gate_path = REPORTS_DIR / "loop" / "promotion_gate.json"
    promotion_mode = "unknown"
    if promotion_gate_path.exists():
        try:
            promotion_gate_data = load_json(promotion_gate_path)
            promotion_mode = promotion_gate_data.get("mode", "unknown")
        except Exception:
            pass
    
    status_str = "ARMED" if armed else "DISARMED"
    print(f"Status: {status_str}")
    print(f"Operator Enabled: {operator_enabled}")
    print(f"Capital Mode: {capital_mode}")
    print(f"Arm Score: {arm_score:.3f}")
    print(f"Consecutive OK Ticks: {consecutive_ok}/{6}")
    
    if armed and armed_since:
        print(f"Armed Since: {armed_since[:19]}")
    elif disarm_reason:
        print(f"Disarm Reason: {disarm_reason}")
    
    print(f"Eligible for Arming: {len(eligible_symbols)}")
    if eligible_symbols:
        print(f"  {', '.join(eligible_symbols[:10])}")
        if len(eligible_symbols) > 10:
            print(f"  ... and {len(eligible_symbols) - 10} more")
    else:
        # Add clarifying note when 0
        if promotion_mode != "EXPLOIT_ENABLED" or capital_mode != "normal":
            print("  (Note: Requires promotion_gate=EXPLOIT_ENABLED AND capital_mode=normal)")
    
    print("=" * 70)
    print()


def print_pf_attribution() -> None:
    """
    Print PF Attribution & Capital Mode Diagnosis (Phase 5e).
    
    Shows PF by lane, PF by symbol, loss contribution, and capital mode explanation.
    """
    try:
        from tools.run_pf_attribution import run_pf_attribution
        
        result = run_pf_attribution()
        
        print("PF ATTRIBUTION & CAPITAL MODE DIAGNOSIS (Phase 5e)")
        print("=" * 70)
        
        # PF by Lane
        print("PF BY LANE (30D)")
        print("-" * 70)
        lane_pf = result.get("lane_pf", {})
        for lane in ["core", "explore", "exploit", "shadow"]:
            data = lane_pf.get(lane, {})
            pf = data.get("pf")
            trades = data.get("trades", 0)
            pf_str = f"{pf:.2f}" if pf is not None else "—"
            print(f"lane={lane:<10} PF={pf_str:<6} trades={trades}")
        print()
        
        # PF by Symbol (top 10 worst)
        print("SYMBOL PF ATTRIBUTION (30D) — Top 10 Worst")
        print("-" * 70)
        symbol_list = result.get("symbol_pf", [])
        if symbol_list:
            for sym, pf, pnl, trades in symbol_list[:10]:
                pf_str = f"{pf:.2f}" if pf is not None else "—"
                pnl_str = f"{pnl:+.2f}" if pnl is not None else "0.00"
                print(f"{sym:<12} PF={pf_str:<6} pnl={pnl_str:<10} trades={trades}")
        else:
            print("(no trades found)")
        print()
        
        # Capital Mode Explanation
        mode_explanation = result.get("mode_explanation", {})
        mode = mode_explanation.get("mode", "unknown")
        pf_7d = mode_explanation.get("pf_7d")
        trigger = mode_explanation.get("trigger", "unknown")
        recommendation = mode_explanation.get("recommendation", "Unknown")
        top_contributors = mode_explanation.get("top_contributors", [])
        
        print("CAPITAL MODE ATTRIBUTION")
        print("-" * 70)
        print(f"capital_mode = {mode}")
        print(f"Triggered by: {trigger}")
        if pf_7d is not None:
            print(f"PF_7D = {pf_7d:.3f}")
        
        if top_contributors:
            print("Top contributors:")
            for contrib in top_contributors[:3]:
                sym = contrib["symbol"]
                pct = contrib["pct_contribution"]
                print(f"  - {sym} ({pct:.1f}%)")
        
        print(f"Recommendation: {recommendation}")
        print()
        print("=" * 70)
        print()
    except Exception as e:
        print("PF ATTRIBUTION & CAPITAL MODE DIAGNOSIS (Phase 5e)")
        print("=" * 70)
        print(f"Error: {str(e)}")
        print("=" * 70)
        print()


def print_readynow_trace() -> None:
    """
    Print ReadyNow Trace (Phase 5e).
    
    Shows why symbols are ReadyNow=YES or NO, with component breakdown.
    """
    try:
        from tools.run_readynow_trace import run_readynow_trace
        
        result = run_readynow_trace()
        
        print("READYNOW TRACE (Why Exploits Are Blocked) (Phase 5e)")
        print("=" * 70)
        
        traces = result.get("traces", [])
        blockers = result.get("blockers", [])
        
        # Get exploit-intent symbols
        capital_plan = _safe_load_json(REPORTS_DIR / "risk" / "capital_plan.json") or {}
        symbols_data = capital_plan.get("symbols", {}) or capital_plan.get("by_symbol", {})
        exploit_symbols = [
            sym for sym, data in symbols_data.items()
            if data.get("lane_intent") == "exploit"
        ]
        
        # Show traces for exploit symbols first
        shown = set()
        for trace in traces:
            symbol = trace.get("symbol", "")
            if symbol in exploit_symbols:
                ready_now = trace.get("ready_now", False)
                reasons = trace.get("reasons", [])
                components = trace.get("components", {})
                
                print(f"{symbol}: {'YES' if ready_now else 'NO'}")
                if not ready_now and reasons:
                    print(f"  Blockers: {', '.join(reasons[:3])}")
                shown.add(symbol)
        
        # Show summary
        if blockers:
            print()
            print("READYNOW BLOCK SUMMARY")
            print("-" * 70)
            exploit_blockers = [(s, r) for s, r in blockers if s in exploit_symbols]
            if exploit_blockers:
                for symbol, reason in exploit_blockers[:10]:
                    print(f"{symbol:<12} → {reason}")
            else:
                print("(no exploit symbols blocked)")
        else:
            print()
            print("READYNOW BLOCK SUMMARY")
            print("-" * 70)
            print("(no blockers found)")
        
        print()
        print("=" * 70)
        print()
    except Exception as e:
        print("READYNOW TRACE (Why Exploits Are Blocked) (Phase 5e)")
        print("=" * 70)
        print(f"Error: {str(e)}")
        print("=" * 70)
        print()


def print_quarantine_status() -> None:
    """
    Print Loss-Contributor Quarantine Status (Phase 5g).
    
    Shows quarantined symbols, blocked symbols, and weight adjustments.
    """
    quarantine_path = REPORTS_DIR / "risk" / "quarantine.json"
    
    if not quarantine_path.exists():
        print("LOSS-CONTRIBUTOR QUARANTINE (Phase 5g)")
        print("=" * 70)
        print("Status: missing (run quarantine engine)")
        print("=" * 70)
        print()
        return
    
    try:
        quarantine = load_json(quarantine_path)
    except Exception:
        print("LOSS-CONTRIBUTOR QUARANTINE (Phase 5g)")
        print("=" * 70)
        print("Status: error loading state")
        print("=" * 70)
        print()
        return
    
    print("LOSS-CONTRIBUTOR QUARANTINE (Phase 5g)")
    print("=" * 70)
    
    enabled = quarantine.get("enabled", False)
    capital_mode = quarantine.get("capital_mode", "unknown")
    quarantined = quarantine.get("quarantined", [])
    blocked_symbols = quarantine.get("blocked_symbols", [])
    weight_adjustments = quarantine.get("weight_adjustments", [])
    
    print(f"Enabled: {enabled}")
    print(f"Capital Mode: {capital_mode}")
    print(f"Quarantined Symbols: {len(quarantined)}")
    
    if quarantined:
        print()
        print("QUARANTINED SYMBOLS:")
        print("-" * 70)
        for q in quarantined:
            symbol = q["symbol"]
            pnl = q["pnl_usd"]
            contrib = q["contribution_pct"]
            cooldown = q.get("cooldown_until", "?")
            print(f"{symbol:<12} PnL=${pnl:+.2f}  Contribution={contrib:.1f}%  Cooldown={cooldown[:19]}")
    
    if blocked_symbols:
        print()
        print(f"BLOCKED SYMBOLS: {', '.join(blocked_symbols)}")
    
    if weight_adjustments:
        print()
        print("WEIGHT ADJUSTMENTS:")
        print("-" * 70)
        for adj in weight_adjustments:
            symbol = adj["symbol"]
            raw_weight = adj.get("raw_weight", 0.0)
            new_weight = adj.get("new_weight", 0.0)
            multiplier = adj.get("multiplier", 0.0)
            print(f"{symbol:<12} raw={raw_weight:.4f} → new={new_weight:.4f} (mult={multiplier:.2f})")
    
    overlay_path = REPORTS_DIR / "risk" / "capital_plan_quarantine.json"
    if overlay_path.exists():
        print()
        print(f"Modified capital plan: reports/risk/capital_plan_quarantine.json")
    
    notes = quarantine.get("notes", [])
    if notes:
        print()
        print("NOTES:")
        for note in notes:
            print(f"  - {note}")
    
    print()
    print("=" * 70)
    print()


def print_probe_lane_gate_status() -> None:
    """
    Print Probe Lane Gate Status.
    
    Shows gate decision, reason, shadow metrics, and eligible symbols.
    Reads exclusively from probe_lane_gate.json.
    """
    gate_state_path = REPORTS_DIR / "loop" / "probe_lane_gate.json"
    
    print("PROBE LANE GATE (Auto-Enable/Disable)")
    print("=" * 70)
    
    if not gate_state_path.exists():
        print("Status: NOT EVALUATED")
        print("Reason: Gate state file missing")
        print()
        print("=" * 70)
        print()
        return
    
    try:
        gate_state = load_json(gate_state_path)
    except Exception:
        print("Status: ERROR")
        print("Reason: Failed to load gate state")
        print()
        print("=" * 70)
        print()
        return
    
    enabled = gate_state.get("enabled", False)
    decision = gate_state.get("decision", "unknown")
    reason = gate_state.get("reason", "unknown")
    shadow_pf_7d = gate_state.get("shadow_pf_7d")
    shadow_pf_30d = gate_state.get("shadow_pf_30d")
    shadow_trades = gate_state.get("shadow_trades")
    shadow_max_dd = gate_state.get("shadow_max_dd")
    eligible_symbols = gate_state.get("eligible_symbols", [])
    evaluated_at = gate_state.get("evaluated_at")
    capital_mode = gate_state.get("capital_mode", "unknown")
    
    # Status
    if enabled:
        print(f"Status: ENABLED")
    else:
        print(f"Status: DISABLED")
    
    print(f"Decision: {decision.upper()}")
    print(f"Reason: {reason}")
    print(f"Capital Mode: {capital_mode}")
    
    if evaluated_at:
        print(f"Last Evaluation: {evaluated_at[:19]}")
    
    print()
    
    # Shadow metrics
    print("Shadow Metrics:")
    if shadow_pf_7d is not None:
        print(f"  PF_7D: {shadow_pf_7d:.3f}")
    else:
        print(f"  PF_7D: —")
    
    if shadow_pf_30d is not None:
        print(f"  PF_30D: {shadow_pf_30d:.3f}")
    else:
        print(f"  PF_30D: —")
    
    if shadow_trades is not None:
        print(f"  Trades: {shadow_trades}")
    else:
        print(f"  Trades: —")
    
    if shadow_max_dd is not None:
        print(f"  Max DD: {shadow_max_dd:.3f}%")
    else:
        print(f"  Max DD: —")
    
    print()
    
    # Eligible symbols
    print(f"Eligible Symbols: {len(eligible_symbols)}")
    if eligible_symbols:
        for sym_info in eligible_symbols[:5]:
            symbol = sym_info.get("symbol", "?")
            pf_30d = sym_info.get("pf_30d")
            trades = sym_info.get("trades_30d")
            pf_str = f"{pf_30d:.3f}" if pf_30d is not None else "—"
            print(f"  {symbol}: PF_30D={pf_str}, Trades={trades}")
        if len(eligible_symbols) > 5:
            print(f"  ... and {len(eligible_symbols) - 5} more")
    
    print()
    print("=" * 70)
    print()


def print_probe_lane_status() -> None:
    """
    Print Probe Lane Status (execution status).
    
    Shows last action/reason, cooldown status, and selected symbol.
    """
    probe_state_path = REPORTS_DIR / "loop" / "probe_lane_state.json"
    probe_log_path = REPORTS_DIR / "loop" / "probe_lane_log.jsonl"
    
    print("PROBE LANE (Micro-Live Exploration During Halt)")
    print("=" * 70)
    
    # Load state
    state = {}
    if probe_state_path.exists():
        try:
            state = load_json(probe_state_path)
        except Exception:
            pass
    
    last_action = state.get("last_action", "none")
    last_symbol = state.get("last_symbol")
    last_trade_at = state.get("last_trade_at")
    
    print(f"Last Action: {last_action}")
    if last_symbol:
        print(f"Last Symbol: {last_symbol}")
    if last_trade_at:
        print(f"Last Trade: {last_trade_at[:19]}")
    
    # Get last log entry
    if probe_log_path.exists():
        try:
            lines = probe_log_path.read_text().splitlines()
            if lines:
                last_log = json.loads(lines[-1])
                reason = last_log.get("reason", "unknown")
                selected = last_log.get("selected_symbol")
                shadow_metrics = last_log.get("shadow_metrics", {})
                
                print(f"Last Reason: {reason}")
                if shadow_metrics:
                    pf_30d = shadow_metrics.get("pf_30d")
                    pf_7d = shadow_metrics.get("pf_7d")
                    trades = shadow_metrics.get("trades_30d")
                    if pf_30d and pf_7d:
                        print(f"Last Shadow Metrics: PF_30D={pf_30d:.3f}, PF_7D={pf_7d:.3f}, Trades={trades}")
        except Exception:
            pass
    
    print()
    print("=" * 70)
    print()


def print_recovery_ramp_status() -> None:
    """
    Print Recovery Ramp Status (Phase 5H).
    
    Shows capital mode, recovery mode, recovery score, gates, metrics,
    hysteresis, and whether recovery trading is allowed.
    Reads exclusively from recovery_ramp.json.
    """
    ramp_state_path = REPORTS_DIR / "risk" / "recovery_ramp.json"
    
    print("RECOVERY RAMP STATUS (Phase 5H)")
    print("=" * 70)
    
    if not ramp_state_path.exists():
        print("  (recovery_ramp.json not found)")
        print()
        return
    
    try:
        ramp_state = load_json(ramp_state_path)
    except Exception:
        print("  (error loading recovery_ramp.json)")
        print()
        return
    
    # Basic status
    capital_mode = ramp_state.get("capital_mode", "unknown")
    recovery_mode = ramp_state.get("recovery_mode", "OFF")
    recovery_score = ramp_state.get("recovery_score", 0.0)
    reason = ramp_state.get("reason", "")
    
    print(f"Capital Mode: {capital_mode}")
    print(f"Recovery Mode: {recovery_mode}")
    print(f"Recovery Score: {recovery_score:.3f}")
    print(f"Reason: {reason}")
    print()
    
    # Gates
    print("Gates:")
    gates = ramp_state.get("gates", {})
    for gate_name, gate_pass in gates.items():
        status = "✓" if gate_pass else "✗"
        print(f"  {status} {gate_name}: {gate_pass}")
    print()
    
    # Metrics
    print("Metrics:")
    metrics = ramp_state.get("metrics", {})
    pf_7d = metrics.get("pf_7d")
    pf_30d = metrics.get("pf_30d")
    pf_7d_slope = metrics.get("pf_7d_slope")
    clean_closes = metrics.get("recent_clean_closes", 0)
    loss_closes = metrics.get("recent_loss_closes", 0)
    quarantined_symbols = metrics.get("quarantined_symbols", [])
    
    print(f"  PF_7D: {_fmt_pf(pf_7d)}")
    print(f"  PF_30D: {_fmt_pf(pf_30d)}")
    if pf_7d_slope is not None:
        print(f"  PF_7D Slope: {pf_7d_slope:+.4f}")
    else:
        print(f"  PF_7D Slope: —")
    print(f"  Clean Closes (24h): {clean_closes}")
    print(f"  Loss Closes (24h): {loss_closes}")
    if quarantined_symbols:
        print(f"  Quarantined Symbols: {', '.join(quarantined_symbols)}")
    print()
    
    # Hysteresis
    print("Hysteresis:")
    hysteresis = ramp_state.get("hysteresis", {})
    ok_ticks = hysteresis.get("ok_ticks", 0)
    needed_ticks = hysteresis.get("needed_ok_ticks", 6)
    print(f"  OK Ticks: {ok_ticks}/{needed_ticks}")
    print()
    
    # Allowances
    print("Allowances:")
    allowances = ramp_state.get("allowances", {})
    allow_trading = allowances.get("allow_recovery_trading", False)
    allowed_symbols = allowances.get("allowed_symbols", [])
    max_positions = allowances.get("max_positions", 1)
    risk_mult_cap = allowances.get("risk_mult_cap", 0.25)
    
    print(f"  Allow Recovery Trading: {allow_trading}")
    print(f"  Max Positions: {max_positions}")
    print(f"  Risk Mult Cap: {risk_mult_cap:.2f}")
    if allowed_symbols:
        print(f"  Allowed Symbols: {', '.join(allowed_symbols)}")
    else:
        print(f"  Allowed Symbols: (none)")
    print()
    
    # Notes
    notes = ramp_state.get("notes", [])
    if notes:
        print("Notes:")
        for note in notes:
            print(f"  • {note}")
        print()
    
    # Recovery lane status (if log exists)
    recovery_lane_log_path = REPORTS_DIR / "loop" / "recovery_lane_log.jsonl"
    if recovery_lane_log_path.exists():
        try:
            log_entries = _safe_tail_jsonl(recovery_lane_log_path, n=5)
            if log_entries:
                last_entry = log_entries[-1]
                action = last_entry.get("action", "unknown")
                last_reason = last_entry.get("reason", "")
                last_symbol = last_entry.get("symbol")
                last_ts = last_entry.get("ts", "")
                
                print("Recovery Lane (Last Action):")
                print(f"  Action: {action.upper()}")
                print(f"  Reason: {last_reason}")
                if last_symbol:
                    print(f"  Symbol: {last_symbol}")
                if last_ts:
                    print(f"  Timestamp: {last_ts}")
                print()
        except Exception:
            pass
    
    print("=" * 70)
    print()


def print_recovery_ramp_status() -> None:
    """
    Print Recovery Ramp Status (Phase 5H).
    
    Shows capital mode, recovery mode, recovery score, gates, metrics,
    hysteresis, and whether recovery trading is allowed.
    Reads exclusively from recovery_ramp.json.
    """
    ramp_state_path = REPORTS_DIR / "risk" / "recovery_ramp.json"
    
    print("RECOVERY RAMP STATUS (Phase 5H)")
    print("=" * 70)
    
    if not ramp_state_path.exists():
        print("  (recovery_ramp.json not found)")
        print()
        return
    
    try:
        ramp_state = load_json(ramp_state_path)
    except Exception:
        print("  (error loading recovery_ramp.json)")
        print()
        return
    
    # Basic status
    capital_mode = ramp_state.get("capital_mode", "unknown")
    recovery_mode = ramp_state.get("recovery_mode", "OFF")
    recovery_score = ramp_state.get("recovery_score", 0.0)
    reason = ramp_state.get("reason", "")
    
    print(f"Capital Mode: {capital_mode}")
    print(f"Recovery Mode: {recovery_mode}")
    print(f"Recovery Score: {recovery_score:.3f}")
    print(f"Reason: {reason}")
    print()
    
    # Gates
    print("Gates:")
    gates = ramp_state.get("gates", {})
    for gate_name, gate_pass in gates.items():
        status = "✓" if gate_pass else "✗"
        print(f"  {status} {gate_name}: {gate_pass}")
    print()
    
    # Metrics
    print("Metrics:")
    metrics = ramp_state.get("metrics", {})
    pf_7d = metrics.get("pf_7d")
    pf_30d = metrics.get("pf_30d")
    pf_7d_slope = metrics.get("pf_7d_slope")
    clean_closes = metrics.get("recent_clean_closes", 0)
    loss_closes = metrics.get("recent_loss_closes", 0)
    quarantined_symbols = metrics.get("quarantined_symbols", [])
    
    print(f"  PF_7D: {_fmt_pf(pf_7d)}")
    print(f"  PF_30D: {_fmt_pf(pf_30d)}")
    if pf_7d_slope is not None:
        print(f"  PF_7D Slope: {pf_7d_slope:+.4f}")
    else:
        print(f"  PF_7D Slope: —")
    print(f"  Clean Closes (24h): {clean_closes}")
    print(f"  Loss Closes (24h): {loss_closes}")
    if quarantined_symbols:
        print(f"  Quarantined Symbols: {', '.join(quarantined_symbols)}")
    print()
    
    # Hysteresis
    print("Hysteresis:")
    hysteresis = ramp_state.get("hysteresis", {})
    ok_ticks = hysteresis.get("ok_ticks", 0)
    needed_ticks = hysteresis.get("needed_ok_ticks", 6)
    print(f"  OK Ticks: {ok_ticks}/{needed_ticks}")
    print()
    
    # Allowances
    print("Allowances:")
    allowances = ramp_state.get("allowances", {})
    allow_trading = allowances.get("allow_recovery_trading", False)
    allowed_symbols = allowances.get("allowed_symbols", [])
    max_positions = allowances.get("max_positions", 1)
    risk_mult_cap = allowances.get("risk_mult_cap", 0.25)
    
    print(f"  Allow Recovery Trading: {allow_trading}")
    print(f"  Max Positions: {max_positions}")
    print(f"  Risk Mult Cap: {risk_mult_cap:.2f}")
    if allowed_symbols:
        print(f"  Allowed Symbols: {', '.join(allowed_symbols)}")
    else:
        print(f"  Allowed Symbols: (none)")
    print()
    
    # Notes
    notes = ramp_state.get("notes", [])
    if notes:
        print("Notes:")
        for note in notes:
            print(f"  • {note}")
        print()
    
    # Recovery lane status (if log exists)
    recovery_lane_log_path = REPORTS_DIR / "loop" / "recovery_lane_log.jsonl"
    if recovery_lane_log_path.exists():
        try:
            log_entries = _safe_tail_jsonl(recovery_lane_log_path, n=5)
            if log_entries:
                last_entry = log_entries[-1]
                action = last_entry.get("action", "unknown")
                last_reason = last_entry.get("reason", "")
                last_symbol = last_entry.get("symbol")
                last_ts = last_entry.get("ts", "")
                
                print("Recovery Lane (Last Action):")
                print(f"  Action: {action.upper()}")
                print(f"  Reason: {last_reason}")
                if last_symbol:
                    print(f"  Symbol: {last_symbol}")
                if last_ts:
                    print(f"  Timestamp: {last_ts}")
                print()
        except Exception:
            pass
    
    print("=" * 70)
    print()


def print_promotion_gate_status() -> None:
    """
    Print Promotion Gate Status (Probe → Exploit).
    
    Shows mode, decision, reason, live probe metrics, and shadow confirmation.
    Reads exclusively from promotion_gate.json.
    """
    gate_state_path = REPORTS_DIR / "loop" / "promotion_gate.json"
    
    print("PROMOTION GATE (Probe → Exploit)")
    print("=" * 70)
    
    if not gate_state_path.exists():
        print("Status: NOT EVALUATED")
        print("Reason: Gate state file missing")
        print()
        print("=" * 70)
        print()
        return
    
    try:
        gate_state = load_json(gate_state_path)
    except Exception:
        print("Status: ERROR")
        print("Reason: Failed to load gate state")
        print()
        print("=" * 70)
        print()
        return
    
    mode = gate_state.get("mode", "DISABLED")
    decision = gate_state.get("decision", "hold")
    reason = gate_state.get("reason", "unknown")
    selected_symbol = gate_state.get("selected_symbol")
    live_probe = gate_state.get("live_probe", {})
    shadow = gate_state.get("shadow", {})
    evaluated_at = gate_state.get("evaluated_at")
    
    # Status
    print(f"Mode: {mode}")
    print(f"Decision: {decision.upper()}")
    print(f"Reason: {reason}")
    
    if selected_symbol:
        print(f"Selected Symbol: {selected_symbol}")
    
    if evaluated_at:
        print(f"Last Evaluation: {evaluated_at[:19]}")
    
    print()
    
    # Live probe metrics
    print("Live Probe Metrics:")
    print(f"  Trades: {live_probe.get('trades', 0)}")
    pf = live_probe.get("pf", 0.0)
    print(f"  PF: {pf:.3f}" if pf > 0 else "  PF: —")
    win_rate = live_probe.get("win_rate", 0.0)
    print(f"  Win Rate: {win_rate:.1%}" if win_rate > 0 else "  Win Rate: —")
    max_dd = live_probe.get("max_dd", 0.0)
    print(f"  Max DD: {max_dd:.3f}%" if max_dd > 0 else "  Max DD: —")
    consec_losses = live_probe.get("consecutive_losses", 0)
    print(f"  Consecutive Losses: {consec_losses}")
    
    print()
    
    # Shadow confirmation
    print("Shadow Confirmation:")
    shadow_pf_7d = shadow.get("pf_7d")
    shadow_pf_30d = shadow.get("pf_30d")
    shadow_trades = shadow.get("trades")
    
    if shadow_pf_7d is not None:
        print(f"  PF_7D: {shadow_pf_7d:.3f}")
    else:
        print(f"  PF_7D: —")
    
    if shadow_pf_30d is not None:
        print(f"  PF_30D: {shadow_pf_30d:.3f}")
    else:
        print(f"  PF_30D: —")
    
    if shadow_trades is not None:
        print(f"  Trades: {shadow_trades}")
    else:
        print(f"  Trades: —")
    
    print()
    print("=" * 70)
    print()


def print_recovery_ramp_v2_status() -> None:
    """
    Print Recovery Ramp V2 Status (Phase 5H.2).
    
    Shows per-symbol recovery eligibility, scores, and allowed symbols.
    Reads exclusively from recovery_ramp_v2.json.
    """
    ramp_v2_state_path = REPORTS_DIR / "risk" / "recovery_ramp_v2.json"
    
    print("RECOVERY RAMP V2 (Per-Symbol) (Phase 5H.2)")
    print("=" * 70)
    
    if not ramp_v2_state_path.exists():
        print("  (recovery_ramp_v2.json not found)")
        print()
        return
    
    try:
        ramp_v2_state = load_json(ramp_v2_state_path)
    except Exception:
        print("  (error loading recovery_ramp_v2.json)")
        print()
        return
    
    # Global status
    capital_mode = ramp_v2_state.get("capital_mode", "unknown")
    global_data = ramp_v2_state.get("global", {})
    decision = ramp_v2_state.get("decision", {})
    
    print(f"Capital Mode: {capital_mode}")
    print(f"PF Timeseries Fresh: {global_data.get('pf_timeseries_fresh_pass', False)}")
    pf_age = global_data.get("pf_timeseries_age_minutes")
    if pf_age is not None:
        print(f"PF Timeseries Age: {pf_age:.1f} minutes")
    print(f"Allow Recovery Lane: {decision.get('allow_recovery_lane', False)}")
    print(f"Reason: {decision.get('reason', '')}")
    print()
    
    # Allowed symbols
    allowed_symbols = decision.get("allowed_symbols", [])
    if allowed_symbols:
        print(f"Allowed Symbols: {', '.join(allowed_symbols)}")
    else:
        print("Allowed Symbols: (none)")
    print()
    
    # Top candidates
    symbols = ramp_v2_state.get("symbols", {})
    candidates = []
    
    for symbol, symbol_data in symbols.items():
        eligible = symbol_data.get("eligible", False)
        score = symbol_data.get("score", 0.0)
        reasons = symbol_data.get("reasons", [])
        
        candidates.append({
            "symbol": symbol,
            "eligible": eligible,
            "score": score,
            "reasons": reasons,
        })
    
    # Sort by score (descending)
    candidates.sort(key=lambda x: -x["score"])
    
    print("Top Candidates:")
    for i, cand in enumerate(candidates[:3], 1):
        status = "✓" if cand["eligible"] else "✗"
        reasons_str = ", ".join(cand["reasons"][:2]) if cand["reasons"] else "—"
        print(f"  {status} {cand['symbol']:<10} Score: {cand['score']:.3f}  Reasons: {reasons_str}")
    print()
    
    # State age
    ts_str = ramp_v2_state.get("ts")
    if ts_str:
        try:
            state_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
            now = datetime.now(timezone.utc)
            age_minutes = (now - state_time).total_seconds() / 60.0
            print(f"State Age: {age_minutes:.1f} minutes")
        except Exception:
            pass
    
        print("=" * 70)
        print()


def print_recovery_v2_score() -> None:
    """
    Print Recovery V2 Performance Score (Phase 5H.3).
    
    Shows read-only performance metrics from recovery_v2_score.json.
    """
    score_path = REPORTS_DIR / "loop" / "recovery_v2_score.json"
    
    print("RECOVERY V2 SCORE (Read-only) (Phase 5H.3)")
    print("=" * 70)
    
    score = load_json(score_path)
    
    if not score:
        print("  (no data yet)")
        print()
        print("=" * 70)
        print()
        return
    
    metrics_24h = score.get("24h", {})
    metrics_7d = score.get("7d", {})
    
    trades_24h = metrics_24h.get("trades", 0)
    trades_7d = metrics_7d.get("trades", 0)
    
    if trades_24h == 0 and trades_7d == 0:
        print("  (no trades yet)")
        print()
        print("=" * 70)
        print()
        return
    
    # 24h metrics
    pf_24h = metrics_24h.get("pf", 0.0)
    pf_24h_str = "inf" if pf_24h == float("inf") else f"{pf_24h:.3f}"
    win_rate_24h = metrics_24h.get("win_rate", 0.0)
    mdd_24h = metrics_24h.get("max_drawdown_pct", 0.0)
    
    # 7d metrics
    pf_7d = metrics_7d.get("pf", 0.0)
    pf_7d_str = "inf" if pf_7d == float("inf") else f"{pf_7d:.3f}"
    trades_7d = metrics_7d.get("trades", 0)
    
    print(f"24h PF              : {pf_24h_str}")
    print(f"24h Trades          : {trades_24h}")
    print(f"24h Win Rate        : {win_rate_24h:.1%}")
    print(f"24h MDD%            : {mdd_24h:.3f}%")
    print(f"7d PF               : {pf_7d_str}")
    print(f"7d Trades           : {trades_7d}")
    print()
    print("=" * 70)
    print()


def print_recovery_assist_status() -> None:
    """
    Print Recovery Assist Status (Phase 5H.4).
    
    Shows recovery assist evaluation state.
    """
    assist_path = REPORTS_DIR / "risk" / "recovery_assist.json"
    
    print("RECOVERY ASSIST (Phase 5H.4)")
    print("=" * 70)
    
    assist_data = load_json(assist_path)
    
    if not assist_data:
        print("  (no data yet)")
        print()
        print("=" * 70)
        print()
        return
    
    assist_enabled = assist_data.get("assist_enabled", False)
    reason = assist_data.get("reason", "")
    gates = assist_data.get("gates", {})
    metrics = assist_data.get("metrics", {})
    
    print(f"Assist Enabled: {'YES' if assist_enabled else 'NO'}")
    print(f"Reason         : {reason}")
    print()
    print("Gates:")
    print(f"  Trades 24h (>=30)     : {'PASS' if gates.get('trades_24h') else 'FAIL'}")
    print(f"  PF 24h (>=1.10)       : {'PASS' if gates.get('pf_24h') else 'FAIL'}")
    print(f"  MDD 24h (<=2.0%)      : {'PASS' if gates.get('mdd_24h') else 'FAIL'}")
    print(f"  Symbol Diversity      : {'PASS' if gates.get('symbol_diversity') else 'FAIL'}")
    print(f"  Net PnL USD (>0)      : {'PASS' if gates.get('net_pnl_usd_24h') else 'FAIL'}")
    print(f"  Worst Dominant Symbol Exp (>=-0.05%): {'PASS' if gates.get('worst_symbol_expectancy_24h') else 'FAIL'}")
    print()
    print("Metrics:")
    print(f"  Trades 24h    : {metrics.get('trades_24h', 0)}")
    pf_24h = metrics.get('pf_24h', 0.0)
    if pf_24h == float("inf"):
        print(f"  PF 24h        : inf")
    else:
        print(f"  PF 24h        : {pf_24h:.3f}")
    print(f"  MDD 24h       : {metrics.get('mdd_24h', 0.0):.3f}%")
    print(f"  Symbols (3+ closes): {metrics.get('symbols_with_3+_closes', metrics.get('symbols_with_sufficient_closes', 0))}")
    print(f"  Non-SOL closes: {metrics.get('non_sol_closes_24h', 0)}")
    net_pnl = metrics.get('net_pnl_usd_24h', 0.0)
    print(f"  Net PnL USD   : ${net_pnl:+.4f}")
    worst_exp = metrics.get('worst_symbol_expectancy_24h')
    if worst_exp is not None:
        print(f"  Worst Dominant Symbol Exp: {worst_exp:.3f}% (dominant=≥8 closes or ≥25%)")
    else:
        print(f"  Worst Dominant Symbol Exp: N/A (no dominant symbols)")
    print()
    print("Symbol Counts (24h):")
    symbol_counts = assist_data.get("symbol_counts_24h", {})
    if symbol_counts:
        for symbol, count in sorted(symbol_counts.items(), key=lambda x: -x[1]):
            print(f"  {symbol}: {count}")
    else:
        print("  (none)")
    print()
    print("=" * 70)
    print()


def print_micro_core_ramp_status() -> None:
    """
    Print Micro Core Ramp Status (Phase 5H.4).
    
    Shows open position (if any) and last 10 actions from micro_core_ramp_log.jsonl.
    """
    log_path = REPORTS_DIR / "loop" / "micro_core_ramp_log.jsonl"
    state_path = REPORTS_DIR / "loop" / "micro_core_ramp_state.json"
    
    print("MICRO CORE RAMP (Phase 5H.4)")
    print("=" * 70)
    
    # Check for open position
    state = load_json(state_path)
    open_positions = state.get("open_positions", {})
    
    if open_positions:
        for symbol, position in open_positions.items():
            direction = position.get("direction", 0)
            entry_price = position.get("entry_price", 0.0)
            entry_ts = position.get("entry_ts", "")
            confidence = position.get("confidence", 0.0)
            
            # Skip invalid positions
            if direction == 0 or entry_price <= 0:
                continue
            
            # Calculate age
            age_str = "—"
            if entry_ts:
                try:
                    entry_time = datetime.fromisoformat(entry_ts.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    age_minutes = int((now - entry_time).total_seconds() / 60.0)
                    age_str = f"{age_minutes}m"
                except Exception:
                    pass
            
            dir_str = "LONG" if direction == 1 else "SHORT" if direction == -1 else "FLAT"
            
            print(f"Open Position:")
            print(f"  Symbol: {symbol}")
            print(f"  Direction: {dir_str}")
            print(f"  Entry Price: ${entry_price:.2f}")
            print(f"  Entry Confidence: {confidence:.3f}")
            print(f"  Age: {age_str}")
            print(f"  Exit Rules: TP=+0.20% | SL=-0.15% | Timeout=45m | Conf Drop<0.42 | Dir Flip")
            print()
    
    if not log_path.exists():
        if not open_positions:
            print("  (no actions logged yet)")
        print()
        print("=" * 70)
        print()
        return
    
    try:
        log_entries = _safe_tail_jsonl(log_path, n=10)
        
        if not log_entries:
            print("  (no log entries)")
            print()
            print("=" * 70)
            print()
            return
        
        # Print last 10 entries
        for entry in log_entries[-10:]:
            try:
                action = entry.get("action", "unknown")
                symbol = entry.get("symbol") or "—"
                reason = entry.get("reason", "")
                ts = entry.get("ts", "")
                direction = entry.get("direction")
                confidence = entry.get("confidence")
                pnl_pct = entry.get("pnl_pct")
                
                # Format timestamp
                ts_display = ts[:19] if ts else "—"
                
                # Format direction
                dir_str = "LONG" if direction == 1 else "SHORT" if direction == -1 else "—"
                
                # Format line
                line = f"  {ts_display}  {action.upper():<8}  {str(symbol):<10}"
                if direction is not None:
                    line += f"  {dir_str:<5}"
                if confidence is not None:
                    line += f"  conf={confidence:.2f}"
                if pnl_pct is not None:
                    line += f"  PnL={pnl_pct:+.2f}%"
                if reason:
                    line += f"  {reason}"
                
                print(line)
            except Exception:
                continue
        
        print()
        print("=" * 70)
        print()
    except Exception:
        print("  (error reading log)")
        print()
        print("=" * 70)
        print()


def print_pf_sources_interpretation() -> None:
    """
    Print PF Sources & Interpretation Panel (Phase 5H.2).
    
    Shows Core PF, Shadow PF, and Recovery V2 trades to reduce confusion.
    """
    print("PF SOURCES & INTERPRETATION (Anti-Spook) (Phase 5H.2)")
    print("=" * 70)
    
    # Core PF from capital_protection.json
    capital_protection_path = REPORTS_DIR / "risk" / "capital_protection.json"
    capital_protection = load_json(capital_protection_path)
    global_data = capital_protection.get("global", {})
    core_pf_7d = global_data.get("pf_7d")
    core_pf_30d = global_data.get("pf_30d")
    
    # Shadow PF from shadow_exploit_pf.json
    shadow_pf_paths = [
        REPORTS_DIR / "pf" / "shadow_exploit_pf.json",
        REPORTS_DIR / "reflect" / "shadow_exploit_pf.json",
    ]
    shadow_pf = {}
    for path in shadow_pf_paths:
        if path.exists():
            shadow_pf = load_json(path)
            break
    
    shadow_pf_7d = shadow_pf.get("global", {}).get("7d", {}).get("pf_display")
    shadow_pf_30d = shadow_pf.get("global", {}).get("30d", {}).get("pf_display")
    
    # Recovery V2 trades count (last 24h)
    recovery_trades_path = REPORTS_DIR / "loop" / "recovery_lane_v2_trades.jsonl"
    recovery_trades_24h = 0
    if recovery_trades_path.exists():
        try:
            from datetime import datetime, timezone, timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            lines = recovery_trades_path.read_text().splitlines()
            for line in lines:
                if line.strip():
                    try:
                        trade = json.loads(line)
                        ts = trade.get("ts", "")
                        if ts >= cutoff:
                            recovery_trades_24h += 1
                    except Exception:
                        continue
        except Exception:
            pass
    
    print(f"Core PF_7D:  {_fmt_pf(core_pf_7d)}")
    print(f"Core PF_30D: {_fmt_pf(core_pf_30d)}")
    print(f"Shadow PF_7D:  {_fmt_pf(shadow_pf_7d)}")
    print(f"Shadow PF_30D: {_fmt_pf(shadow_pf_30d)}")
    print(f"Recovery V2 Trades (24h): {recovery_trades_24h}")
    print()
    print("Interpretation:")
    print("  • Core PF uses reports/trades.jsonl close events (real paper bot)")
    print("  • Shadow PF uses shadow_exploit_log.jsonl would_exit events (sim)")
    print("  • Recovery V2 is a micro lane with its own trade log; it does not")
    print("    affect capital_mode yet (until later phase)")
    print()
    print("=" * 70)
    print()


def print_recovery_lane_v2_status() -> None:
    """
    Print Recovery Lane V2 Status (Phase 5H.2).
    
    Shows open recovery position (if any) and last 10 actions from recovery_lane_v2_log.jsonl.
    """
    log_path = REPORTS_DIR / "loop" / "recovery_lane_v2_log.jsonl"
    state_path = REPORTS_DIR / "loop" / "recovery_lane_v2_state.json"
    
    print("RECOVERY LANE V2 (Phase 5H.2)")
    print("=" * 70)
    
    # Check for open recovery position
    state = load_json(state_path)
    open_positions = state.get("open_positions", {})
    positions_map = state.get("positions", {})  # Full position data (more reliable)
    
    # Filter out ghost/stale positions (FLAT direction or missing entry_price)
    valid_open_positions = {}
    for symbol, position in open_positions.items():
        direction = position.get("direction", 0)
        entry_price = position.get("entry_price", 0.0)
        
        # Skip FLAT positions or positions with no entry price (ghost entries)
        if direction == 0 or entry_price <= 0:
            continue
        
        # Prefer full position data from positions map if available
        full_position = positions_map.get(symbol, position)
        valid_open_positions[symbol] = full_position
    
    if valid_open_positions:
        for symbol, position in valid_open_positions.items():
            direction = position.get("direction", 0)
            entry_price = position.get("entry_price", 0.0)
            entry_ts = position.get("entry_ts", "")
            confidence = position.get("confidence") or position.get("entry_confidence", 0.0)
            
            # Skip if still invalid after merge
            if direction == 0 or entry_price <= 0:
                continue
            
            # Calculate age
            age_str = "—"
            if entry_ts:
                try:
                    entry_time = datetime.fromisoformat(entry_ts.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    age_minutes = int((now - entry_time).total_seconds() / 60.0)
                    age_str = f"{age_minutes}m"
                except Exception:
                    pass
            
            dir_str = "LONG" if direction == 1 else "SHORT" if direction == -1 else "FLAT"
            
            print(f"Open Recovery Position:")
            print(f"  Symbol: {symbol}")
            print(f"  Direction: {dir_str}")
            print(f"  Entry Price: ${entry_price:.2f}")
            print(f"  Entry Confidence: {confidence:.3f}")
            print(f"  Age: {age_str}")
            print(f"  Exit Rules: TP=+0.20% | SL=-0.15% | Timeout=45m | Conf Drop<0.42 | Dir Flip")
            print()
    
    if not log_path.exists():
        if not open_positions:
            print("  (no actions logged yet)")
        print()
        print("=" * 70)
        print()
        return
    
    try:
        log_entries = _safe_tail_jsonl(log_path, n=10)
        
        if not log_entries:
            print("  (no log entries)")
            print()
            print("=" * 70)
            print()
            return
        
        # Print last 10 entries
        for entry in log_entries[-10:]:
            try:
                action = entry.get("action", "unknown")
                symbol = entry.get("symbol") or "—"
                reason = entry.get("reason", "")
                ts = entry.get("ts", "")
                direction = entry.get("direction")
                confidence = entry.get("confidence")
                notional = entry.get("notional_usd")
                pnl_pct = entry.get("pnl_pct")
                
                # Format timestamp
                ts_display = ts[:19] if ts else "—"
                
                # Format direction
                dir_str = "LONG" if direction == 1 else "SHORT" if direction == -1 else "—"
                
                # Format line
                line = f"  {ts_display}  {action.upper():<8}  {str(symbol):<10}"
                if direction is not None:
                    line += f"  {dir_str:<6}"
                if confidence is not None:
                    line += f"  conf={confidence:.2f}"
                if notional is not None:
                    line += f"  ${notional:.2f}"
                if pnl_pct is not None:
                    line += f"  PnL={pnl_pct:+.2f}%"
                line += f"  {reason}"
                
                print(line)
            except Exception:
                # Skip malformed entries
                continue
        
        print()
    except Exception as e:
        # Fail silently - don't break dashboard if log read fails
        print("  (error reading log)")
        print()
    
    print("=" * 70)
    print()


def print_model_a_timer_compliance() -> None:
    """
    Print Model A Timer Compliance Check.
    
    Shows PASS/FAIL and lists forbidden timers if present.
    """
    try:
        from tools.run_model_a_compliance import check_compliance
        
        is_compliant, allowed, forbidden = check_compliance()
        
        print("MODEL A TIMER COMPLIANCE")
        print("=" * 70)
        
        if is_compliant:
            print("✅ PASS: Model A compliant")
            print(f"Allowed timers: {len(allowed)}")
            for timer in sorted(allowed):
                print(f"  ✅ {timer}")
        else:
            print("❌ FAIL: Model A compliance violation")
            print()
            print("Forbidden timers detected:")
            for timer in sorted(forbidden):
                print(f"  ❌ {timer}")
            print()
            print("RECOMMENDATION: Disable forbidden timers:")
            for timer in sorted(forbidden):
                print(f"  sudo systemctl disable --now {timer}")
        
        print()
        print("=" * 70)
        print()
    except Exception as e:
        # Fail silently - don't break dashboard if check fails
        print("MODEL A TIMER COMPLIANCE")
        print("=" * 70)
        print(f"Error: {str(e)}")
        print("=" * 70)
        print()


def print_phase5_readiness_panel() -> None:
    """
    Print Phase 5 Readiness Panel (Phase 5d).
    
    Consolidated diagnostic view of all Phase 5 components:
    - Capital mode + reason
    - Exploit gate allow/block summary
    - Shadow exploit health
    - Shadow PF display
    - Promotion gate status
    - Micro-paper exploit status
    """
    print("PHASE 5 READINESS PANEL (Phase 5d)")
    print("=" * 70)
    
    # Load all required files (fault-tolerant)
    capital_protection = _safe_load_json(REPORTS_DIR / "risk" / "capital_protection.json") or {}
    capital_plan = _safe_load_json(REPORTS_DIR / "risk" / "capital_plan.json") or {}
    live_candidates = _safe_load_json(REPORTS_DIR / "risk" / "live_candidates.json") or {}
    shadow_state = _safe_load_json(REPORTS_DIR / "reflect" / "shadow_exploit_state.json") or {}
    shadow_pf = _safe_load_json(REPORTS_DIR / "reflect" / "shadow_exploit_pf.json") or {}
    shadow_scores = _safe_load_json(REPORTS_DIR / "reflect" / "shadow_exploit_scores.json") or {}
    shadow_log = _safe_tail_jsonl(REPORTS_DIR / "reflect" / "shadow_exploit_log.jsonl", n=200)
    promotion_candidates = _safe_load_json(REPORTS_DIR / "evolver" / "shadow_promotion_candidates.json") or {}
    exploit_micro_state = _safe_load_json(REPORTS_DIR / "loop" / "exploit_micro_state.json") or {}
    exploit_micro_log = _safe_tail_jsonl(REPORTS_DIR / "loop" / "exploit_micro_log.jsonl", n=50)
    
    # 1. Capital Mode
    capital_mode = capital_protection.get("mode") or _get(capital_protection, "global", "mode") or "unknown"
    reasons = capital_protection.get("reasons", [])
    notes = capital_protection.get("notes", [])
    reason_text = ""
    if reasons:
        reason_text = reasons[0] if isinstance(reasons, list) else str(reasons)
    elif notes:
        reason_text = notes[0] if isinstance(notes, list) else str(notes)
    
    global_pf = capital_protection.get("global", {})
    pf_7d = global_pf.get("pf_7d")
    pf_30d = global_pf.get("pf_30d")
    
    print("Capital Mode:")
    print(f"  Mode: {capital_mode}")
    if reason_text:
        print(f"  Reason: {reason_text}")
    if pf_7d is not None or pf_30d is not None:
        pf7_str = _fmt_pf(pf_7d)
        pf30_str = _fmt_pf(pf_30d)
        print(f"  Global PF: 7D={pf7_str}, 30D={pf30_str}")
    print()
    
    # 2. Exploit Gate Summary
    print("Exploit Gate Summary:")
    allowed = []
    blocked = []
    
    # Get exploit-intent symbols from capital plan (handle multiple formats)
    by_symbol = capital_plan.get("by_symbol", {})
    if not by_symbol:
        by_symbol = capital_plan.get("symbols", {})
    if not by_symbol and isinstance(capital_plan.get("symbols"), list):
        # Handle list format: convert to dict
        symbols_list = capital_plan.get("symbols", [])
        by_symbol = {s.get("symbol", ""): s for s in symbols_list if isinstance(s, dict)}
    
    live_by_symbol = live_candidates.get("by_symbol", {})
    if not live_by_symbol:
        live_by_symbol = live_candidates.get("symbols", {})
    
    for symbol, plan_data in by_symbol.items():
        lane_intent = plan_data.get("lane_intent", "")
        if lane_intent != "exploit":
            continue
        
        weight = plan_data.get("weight", 0.0) or plan_data.get("capital_weight", 0.0)
        policy_level = plan_data.get("policy_level", "")
        
        live_data = live_by_symbol.get(symbol, {})
        ready_now = live_data.get("ready_now", False)
        if ready_now in ("Y", "yes", True):
            ready_now = True
        else:
            ready_now = False
        
        # Gate logic (read-only, diagnostic)
        if capital_mode != "normal":
            blocked.append((symbol, f"capital_mode={capital_mode}"))
        elif weight < 0.15:
            blocked.append((symbol, f"weight={weight:.3f}<0.15"))
        elif not ready_now:
            blocked.append((symbol, "ready_now=N"))
        elif policy_level == "blocked":
            blocked.append((symbol, "policy_blocked"))
        else:
            allowed.append(symbol)
    
    if allowed:
        print(f"  ALLOW: {', '.join(allowed[:10])}")
        if len(allowed) > 10:
            print(f"         ... and {len(allowed) - 10} more")
    else:
        print("  ALLOW: (none)")
    
    if blocked:
        print(f"  BLOCKED (top 5):")
        for symbol, reason in blocked[:5]:
            print(f"    {symbol}: {reason}")
        if len(blocked) > 5:
            print(f"    ... and {len(blocked) - 5} more")
    else:
        print("  BLOCKED: (none)")
    print()
    
    # 2.5. Quarantine Status (Phase 5g)
    quarantine_path = REPORTS_DIR / "risk" / "quarantine.json"
    quarantine_active = False
    quarantine_count = 0
    if quarantine_path.exists():
        try:
            quarantine = _safe_load_json(quarantine_path) or {}
            if quarantine.get("enabled", False):
                quarantine_active = True
                quarantine_count = len(quarantine.get("quarantined", []))
        except Exception:
            pass
    
    print("Quarantine:")
    if quarantine_active:
        print(f"  Status: ON ({quarantine_count} symbols)")
    else:
        print(f"  Status: OFF")
    print()
    
    # 3. Shadow Exploit Health
    print("Shadow Exploit Health:")
    positions = shadow_state.get("positions", {})
    open_count = len(positions)
    
    if open_count > 0:
        print(f"  Open Positions: {open_count}")
        for symbol, pos in list(positions.items())[:5]:
            direction = "LONG" if pos.get("direction", 0) == 1 else "SHORT"
            entry_price = pos.get("entry_price", 0)
            bars_open = pos.get("bars_open", 0)
            entry_ts = pos.get("entry_ts", "")
            print(f"    {symbol}: {direction} @ {entry_price:.4f} (bars={bars_open})")
        if open_count > 5:
            print(f"    ... and {open_count - 5} more")
    else:
        print("  Open Positions: 0")
    
    # Count exits
    exits = [e for e in shadow_log if e.get("action") == "would_exit"]
    exit_count = len(exits)
    print(f"  Total Exits: {exit_count}")
    
    if exits:
        last_exit = exits[-1]
        exit_symbol = last_exit.get("symbol", "?")
        exit_reason = last_exit.get("reason", "?")
        exit_ts = last_exit.get("ts", "?")
        pnl_pct = last_exit.get("pnl_pct")
        pnl_str = f", PnL={pnl_pct:.4f}%" if pnl_pct is not None else ""
        print(f"  Last Exit: {exit_symbol} ({exit_reason}){pnl_str} @ {exit_ts[:19]}")
    print()
    
    # 4. Shadow PF Display (use pf_display)
    print("Shadow PF Display:")
    global_pf_data = shadow_pf.get("global", {}) or shadow_scores.get("global", {})
    
    pf_1d = global_pf_data.get("pf_1d_display") or global_pf_data.get("pf_1d")
    pf_7d = global_pf_data.get("pf_7d_display") or global_pf_data.get("pf_7d")
    pf_30d = global_pf_data.get("pf_30d_display") or global_pf_data.get("pf_30d")
    trades_1d = global_pf_data.get("trades_1d", 0)
    trades_7d = global_pf_data.get("trades_7d", 0)
    trades_30d = global_pf_data.get("trades_30d", 0)
    
    pf1_str = _fmt_pf(pf_1d)
    pf7_str = _fmt_pf(pf_7d)
    pf30_str = _fmt_pf(pf_30d)
    
    print(f"  PF_1D:  {pf1_str:<8} (trades: {trades_1d})")
    print(f"  PF_7D:  {pf7_str:<8} (trades: {trades_7d})")
    print(f"  PF_30D: {pf30_str:<8} (trades: {trades_30d})")
    print()
    
    # 5. Promotion Gate Summary
    print("Promotion Gate:")
    if not promotion_candidates:
        print("  Status: missing")
    else:
        actionable_list = promotion_candidates.get("actionable_candidates", [])
        pending_list = promotion_candidates.get("candidates_pending_mode", [])
        blocked_list = promotion_candidates.get("blocked", [])
        
        if actionable_list:
            print(f"  Actionable: {len(actionable_list)} candidates")
            for cand in actionable_list[:3]:
                symbol = cand.get("symbol", "?")
                print(f"    {symbol}")
        else:
            print("  Actionable: 0 candidates")
        
        if pending_list:
            print(f"  Pending (mode): {len(pending_list)} candidates")
        
        # Check for sample-min blockers
        sample_blockers = [b for b in blocked_list if "shadow_trades" in str(b.get("fails", []))]
        if sample_blockers:
            print(f"  Blocked (sample mins): {len(sample_blockers)} symbols")
            for blocker in sample_blockers[:3]:
                symbol = blocker.get("symbol", "?")
                fails = blocker.get("fails", [])
                sample_fails = [f for f in fails if "shadow_trades" in str(f)]
                if sample_fails:
                    print(f"    {symbol}: {sample_fails[0]}")
    print()
    
    # 6. Micro-Paper Exploit Status
    print("Micro-Paper Exploit:")
    enabled = os.getenv("ENABLE_MICRO_PAPER_EXPLOIT", "false").lower() == "true"
    print(f"  Enabled: {enabled}")
    
    if exploit_micro_state:
        open_positions = exploit_micro_state.get("positions", {}) or exploit_micro_state.get("open_positions", {})
        if isinstance(open_positions, dict):
            micro_open_count = len(open_positions)
        else:
            micro_open_count = 0
        
        if micro_open_count > 0:
            print(f"  Open Positions: {micro_open_count}")
            for symbol, pos in list(open_positions.items())[:3]:
                print(f"    {symbol}: {pos}")
        else:
            print("  Open Positions: 0")
    else:
        print("  Open Positions: —")
    
    if exploit_micro_log:
        last_action = exploit_micro_log[-1]
        action = last_action.get("action", "?")
        reason = last_action.get("reason", "?")
        action_ts = last_action.get("ts", "?")
        print(f"  Last Action: {action} ({reason}) @ {action_ts[:19]}")
    else:
        print("  Last Action: —")
    
    print("=" * 70)
    print()


def print_capital_alignment(payload: dict) -> None:
    """
    Small Capital vs Exploration alignment summary for the dashboard.

    This is a condensed version of tools.capital_exploration_alignment,
    showing only symbols where capital wants more than exploration/risk
    supports (Cap>Exp) or where there are notable flags.
    """
    plan_path = REPORTS_DIR / "risk" / "capital_plan.json"
    policy_path = REPORTS_DIR / "research" / "exploration_policy_v3.json"
    scm_path = REPORTS_DIR / "research" / "scm_state.json"
    risk_path = REPORTS_DIR / "risk" / "risk_snapshot.json"

    if not plan_path.exists():
        return

    try:
        with plan_path.open("r", encoding="utf-8") as f:
            capital_plan = json.load(f)
    except Exception:
        return

    try:
        with policy_path.open("r", encoding="utf-8") as f:
            policy = json.load(f)
    except Exception:
        policy = {}

    try:
        with scm_path.open("r", encoding="utf-8") as f:
            scm = json.load(f)
    except Exception:
        scm = {}

    try:
        with risk_path.open("r", encoding="utf-8") as f:
            risk = json.load(f)
    except Exception:
        risk = {}

    symbols_plan = capital_plan.get("symbols") or {}
    if not symbols_plan:
        return

    def _get_policy(sym: str) -> dict:
        return (policy.get("symbols") or {}).get(sym, {})

    def _get_scm_level(sym: str) -> str:
        # Handle scm_state.json format: {"state": {symbol: {...}}}
        state = scm.get("state")
        if isinstance(state, dict):
            entry = state.get(sym) or {}
            return entry.get("scm_level") or entry.get("level") or "—"
        
        # Handle other formats: {"symbols": {...}} or direct dict
        symbols = scm.get("symbols") or scm
        if isinstance(symbols, dict):
            entry = symbols.get(sym) or {}
        elif isinstance(symbols, list):
            entry = {}
            for item in symbols:
                if isinstance(item, dict) and item.get("symbol") == sym:
                    entry = item
                    break
        else:
            entry = {}
        return entry.get("scm_level") or entry.get("level") or "—"

    def _get_blocked(sym: str) -> bool:
        symbols = risk.get("symbols") or risk
        entry = {}
        if isinstance(symbols, dict):
            entry = symbols.get(sym) or {}
        elif isinstance(symbols, list):
            for item in symbols:
                if isinstance(item, dict) and item.get("symbol") == sym:
                    entry = item
                    break
        blocked = entry.get("blocked")
        if isinstance(blocked, bool):
            return blocked
        if isinstance(blocked, str):
            return blocked.lower() == "yes"
        return False

    def _weight_bucket(w: float) -> str:
        if w >= 0.15:
            return "high"
        if w >= 0.05:
            return "med"
        return "low"

    def _exploration_support(policy_level: str, scm_level: str, blocked: bool) -> float:
        if blocked or policy_level == "blocked":
            return 0.0
        if scm_level == "off":
            return 0.0
        if policy_level == "reduced":
            if scm_level in ("normal", "high"):
                return 1.3
            return 0.7
        if policy_level == "full":
            if scm_level != "off":
                return 1.8
        return 0.6

    rows = []

    for sym in sorted(symbols_plan.keys()):
        entry = symbols_plan[sym] or {}
        try:
            w = float(entry.get("weight", 0.0))
        except Exception:
            w = 0.0
        tier = entry.get("tier") or "—"
        pol_level = entry.get("policy_level") or "—"
        scm_level = _get_scm_level(sym)
        blocked = _get_blocked(sym)

        support = _exploration_support(pol_level, scm_level, blocked)
        wb = _weight_bucket(w)

        align = "OK"
        notes = []

        if wb == "high" and support <= 0.5:
            align = "Cap>Exp"
            notes.append("high_w_low_support")
        elif wb == "low" and support >= 1.5:
            align = "Exp>Cap"
            notes.append("low_w_high_support")

        if tier == "tier3" and w > 0.10:
            notes.append("tier3_high_weight")
        if (pol_level == "blocked" or blocked) and w > 0.02:
            notes.append("blocked_but_weight")
        if scm_level == "off" and w > 0.10:
            notes.append("scm_off_high_weight")

        note_str = ",".join(notes)

        # Only show interesting rows: misaligned or flagged
        if align != "OK" or note_str:
            rows.append((sym, tier, w, pol_level, scm_level, blocked, align, note_str))

    if not rows:
        return

    print()
    print("CAPITAL vs EXPLORATION ALIGNMENT (Summary)")
    print("======================================================================")
    print("Symbol  Tier   Wght   Pol    SCM      Blk  Align    Notes")
    print("----------------------------------------------------------------------")
    for sym, tier, w, pol_level, scm_level, blocked, align, note_str in rows:
        print(
            f"{sym:7s} {tier:6s} {w:5.3f}  {pol_level:6s} {scm_level:8s} "
            f"{'Y' if blocked else 'N':3s} {align:7s}  {note_str}"
        )
    print("======================================================================")


def print_live_candidate_readiness(payload: dict) -> None:
    """
    Print Live-Candidate Readiness summary (Phase 4b).
    """
    lc_path = REPORTS_DIR / "risk" / "live_candidates.json"
    if not lc_path.exists():
        return
    
    try:
        with lc_path.open("r", encoding="utf-8") as f:
            lc = json.load(f)
    except Exception:
        return
    
    meta = lc.get("meta", {})
    symbols = lc.get("symbols", {})
    
    print()
    print("LIVE-CANDIDATE READINESS (Phase 4b - PAPER ONLY)")
    print("======================================================================")
    print(f"Engine      : {meta.get('engine')}")
    print(f"GeneratedAt : {meta.get('generated_at')}")
    print()
    if not symbols:
        print("  No live-candidate data available.")
        print("======================================================================")
        return
    
    print("Symbol  Tier  PF30   PF7   Drift      ExecQL   Policy   Block  Score  ReadyNow LiveReady")
    print("----------------------------------------------------------------------")
    
    items = sorted(
        symbols.items(),
        key=lambda kv: kv[1].get("score", 0.0),
        reverse=True,
    )
    
    for sym, info in items:
        tier = info.get("tier") or "—"
        pf30 = info.get("pf_30d")
        pf7 = info.get("pf_7d")
        drift = info.get("drift") or "—"
        execql = info.get("execql") or "—"
        policy_level = info.get("policy_level") or "—"
        blocked = info.get("blocked")
        score = info.get("score", 0.0)
        ready_now = info.get("ready_now")
        live_ready = info.get("live_ready")
        
        pf30_str = f"{pf30:.3f}" if isinstance(pf30, (int, float)) else "—"
        pf7_str = f"{pf7:.3f}" if isinstance(pf7, (int, float)) else "—"
        
        print(
            f"{sym:7s} {tier:4s} {pf30_str:>5} {pf7_str:>5} "
            f"{drift:10s} {execql:8s} {policy_level:7s} "
            f"{'Y' if blocked else 'N':5s} {score:6.3f} "
            f"{'Y' if ready_now else 'N':8s} {'Y' if live_ready else 'N':9s}"
        )
    
    print("======================================================================")


def print_capital_momentum(payload: dict) -> None:
    """
    Print Capital Momentum summary (Phase 4c).
    """
    cm_path = REPORTS_DIR / "risk" / "capital_momentum.json"
    if not cm_path.exists():
        return
    
    try:
        with cm_path.open("r", encoding="utf-8") as f:
            cm = json.load(f)
    except Exception:
        return
    
    meta = cm.get("meta", {})
    syms = cm.get("symbols", {})
    
    print()
    print("CAPITAL MOMENTUM (Phase 4c)")
    print("======================================================================")
    print(f"Engine      : {meta.get('engine')}")
    print(f"GeneratedAt : {meta.get('generated_at')}")
    print(f"Alpha       : {meta.get('alpha')}")
    print()
    if not syms:
        print("  No capital momentum data.")
        print("======================================================================")
        return
    
    print("Symbol  RawW   Smooth  Delta   Churn")
    print("----------------------------------------------------------------------")
    # Show top by absolute delta or by smoothed weight
    items = sorted(
        syms.items(),
        key=lambda kv: kv[1].get("delta", 0.0),
        reverse=True,
    )
    for sym, info in items:
        rw = info.get("raw_weight", 0.0)
        sw = info.get("smoothed_weight", 0.0)
        delta = info.get("delta", 0.0)
        churn = info.get("churn_tag") or "—"
        print(f"{sym:7s} {rw:5.3f} {sw:7.3f} {delta:6.3f} {churn:12s}")
    print("======================================================================")


def print_pf_validity(payload: dict) -> None:
    """
    Print PF Validity summary (Phase 4d).
    """
    pv_path = REPORTS_DIR / "risk" / "pf_validity.json"
    if not pv_path.exists():
        return
    
    try:
        with pv_path.open("r", encoding="utf-8") as f:
            pv = json.load(f)
    except Exception:
        return
    
    meta = pv.get("meta", {})
    syms = pv.get("symbols", {})
    
    print()
    print("PF VALIDITY (Phase 4d)")
    print("======================================================================")
    print(f"Engine      : {meta.get('engine')}")
    print(f"GeneratedAt : {meta.get('generated_at')}")
    print()
    if not syms:
        print("  No PF validity data.")
        print("======================================================================")
        return
    
    print("Symbol  Score  Label      Sample  Stable  Drift  Exec  Consist")
    print("----------------------------------------------------------------------")
    for sym, info in sorted(syms.items(), key=lambda kv: kv[1].get("validity_score", 0.0), reverse=True):
        score = info.get("validity_score", 0.0)
        label = info.get("label", "")
        comps = info.get("components", {})
        ss = comps.get("sample_size_score", 0.0)
        st = comps.get("stability_score", 0.0)
        ds = comps.get("drift_score", 0.0)
        es = comps.get("exec_score", 0.0)
        cs = comps.get("consistency_score", 0.0)
        print(
            f"{sym:7s} {score:5.3f}  {label:9s} {ss:5.2f}  {st:5.2f}  "
            f"{ds:5.2f}  {es:5.2f}  {cs:7.2f}"
        )
    print("======================================================================")


def print_pf_normalization(payload: dict) -> None:
    """
    Print PF Normalization summary (Phase 4e).
    """
    pn_path = REPORTS_DIR / "risk" / "pf_normalized.json"
    if not pn_path.exists():
        return
    
    try:
        with pn_path.open("r", encoding="utf-8") as f:
            pn = json.load(f)
    except Exception:
        return
    
    meta = pn.get("meta", {})
    syms = pn.get("symbols", {})
    
    print()
    print("PF NORMALIZATION (Phase 4e)")
    print("======================================================================")
    print(f"Engine           : {meta.get('engine')}")
    print(f"GeneratedAt      : {meta.get('generated_at')}")
    print(f"Slippage factor  : {meta.get('slippage_factor')}")
    print()
    if not syms:
        print("  No PF normalization data.")
        print("======================================================================")
        return
    
    print("Symbol  Validity  RawShort  NormShort  RawLong  NormLong")
    print("----------------------------------------------------------------------")
    for sym, info in sorted(syms.items(), key=lambda kv: kv[1].get("validity_score", 0.0), reverse=True):
        v = info.get("validity_score", 0.0)
        rs = info.get("short_exp_pf_raw")
        ns = info.get("short_exp_pf_norm")
        rl = info.get("long_exp_pf_raw")
        nl = info.get("long_exp_pf_norm")
        def _fmt(x):
            return f"{x:.2f}" if isinstance(x, (int, float)) else "—"
        print(f"{sym:7s} {v:8.3f}  {_fmt(rs):>7}   {_fmt(ns):>8}   {_fmt(rl):>7}   {_fmt(nl):>8}")
    print("======================================================================")


def main() -> int:
    """Main entry point with BrokenPipeError handling."""
    # RESEARCH_V2_SAFE_MODE flag
    RESEARCH_V2_SAFE_MODE = os.getenv("RESEARCH_V2_SAFE_MODE", "0") in ("1", "true", "TRUE", "yes", "on")
    
    # Load all data sources
    mode = get_mode()
    symbols = load_symbol_registry()
    
    if not symbols:
        # Fallback to common symbols
        symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
            "LINKUSDT", "DOTUSDT", "ADAUSDT", "ATOMUSDT", "XRPUSDT", "DOGEUSDT"
        ]
    
    # Load reports
    are_snapshot = load_json(RESEARCH_DIR / "are_snapshot.json")
    drift_report = load_json(RESEARCH_DIR / "drift_report.json")
    execution_quality = load_json(RESEARCH_DIR / "execution_quality.json")
    quality_scores = load_json(GPT_DIR / "quality_scores.json")
    reflection_output = load_json(GPT_DIR / "reflection_output.json")
    tuner_output = load_json(GPT_DIR / "tuner_output.json")
    dream_output = load_json(GPT_DIR / "dream_output.json")
    meta_report = load_json(RESEARCH_DIR / "meta_reasoner_report.json")
    
    # Compute PF stats from trades.jsonl (for accurate NormalLanePF)
    pf_stats = compute_pf_from_trades()
    
    # Phase 4k: Load PF normalized data
    pf_norm_path = REPORTS_DIR / "risk" / "pf_normalized.json"
    pf_normalized_data = load_json(pf_norm_path) if pf_norm_path.exists() else None
    
    # Load PF time-series and capital protection data
    pf_ts_path = REPORTS_DIR / "pf" / "pf_timeseries.json"
    cap_path = REPORTS_DIR / "risk" / "capital_protection.json"
    pf_timeseries_data = load_json(pf_ts_path) if pf_ts_path.exists() else {}
    capital_protection_data = load_json(cap_path) if cap_path.exists() else {}
    
    # Build payload for capital overview
    capital_payload = {
        "pf_timeseries": pf_timeseries_data,
        "capital_protection": capital_protection_data,
    }
    
    # Print dashboard
    print_header(mode, len(symbols))
    
    # RESEARCH V2 HEALTH STRIP
    print("RESEARCH V2 HEALTH")
    print("------------------------------------------------------------------")
    micro_h = load_micro_health()
    imb_h = load_imbalance_health()
    sweep_h = load_sweeps_health()
    mstruct_h = load_mstruct_health()
    br_h = load_breakout_health()
    
    def fmt(h):
        if not h:
            return "missing"
        return f"{h.get('status', 'unknown')}"
    
    print(f"Microstructure : {fmt(micro_h)}")
    print(f"VolumeImbalance: {fmt(imb_h)}")
    print(f"Sweeps         : {fmt(sweep_h)}")
    print(f"MarketStruct   : {fmt(mstruct_h)}")
    print(f"BreakoutRel    : {fmt(br_h)}")
    
    # Show reasons if any degraded/stale
    any_degraded = any(
        h and h.get("status") in ("degraded", "stale")
        for h in (micro_h, imb_h, sweep_h, mstruct_h, br_h)
    )
    
    if any_degraded:
        print()
        print("Health Issues:")
        for name, h in [("Microstructure", micro_h), ("VolumeImbalance", imb_h), 
                        ("Sweeps", sweep_h), ("MarketStruct", mstruct_h), 
                        ("BreakoutRel", br_h)]:
            if h and h.get("status") in ("degraded", "stale"):
                reasons = h.get("reasons", [])
                if reasons:
                    print(f"  {name}: {', '.join(reasons[:3])}")  # Show first 3 reasons
    
    print()
    
    print_symbol_summary(symbols, reflection_output, are_snapshot, drift_report, quality_scores, execution_quality, pf_stats, pf_normalized_data)
    print_reflection_snapshot(reflection_output)
    print_tuner_proposals(tuner_output)
    
    # Gate v2 sections with RESEARCH_V2_SAFE_MODE
    if RESEARCH_V2_SAFE_MODE and any_degraded:
        print("Note: RESEARCH_V2_SAFE_MODE=ON and some research modules are degraded.")
        print("      Detailed v2 sections are hidden until health improves.\n")
    else:
        # BREAKOUT RELIABILITY (Phase 1)
        bre = load_breakout_reliability()
        if bre:
            print()
            print("BREAKOUT RELIABILITY")
            print("----------------------------------------------------------------------")
            # Normalize to list of (symbol, score, label)
            rows = []
            if isinstance(bre, dict):
                if "symbols" in bre:
                    symbols_data = bre["symbols"].values()
                else:
                    symbols_data = bre.values()
                for entry in symbols_data:
                    if isinstance(entry, dict):
                        symbol = entry.get("symbol")
                        score = entry.get("score")
                        label = entry.get("label")
                        if symbol is not None and score is not None:
                            rows.append((symbol, score, label))
            elif isinstance(bre, list):
                for entry in bre:
                    if isinstance(entry, dict):
                        symbol = entry.get("symbol")
                        score = entry.get("score")
                        label = entry.get("label")
                        if symbol is not None and score is not None:
                            rows.append((symbol, score, label))
            
            # Sort by score descending
            rows.sort(key=lambda x: x[1], reverse=True)
            
            if rows:
                print("Symbol   Score   Label")
                print("----------------------------------------------------------------------")
                for symbol, score, label in rows:
                    print(f"{symbol:<8} {score:5.2f}   {label}")
            else:
                print("No breakout reliability data available.")
        
        # MICROSTRUCTURE V2 SUMMARY (Phase 1)
        micro_path = RESEARCH_DIR / "microstructure_snapshot_15m.json"
        micro_data = load_json(micro_path)
        # Handle versioned format
        if "symbols" in micro_data:
            micro_symbols = micro_data.get("symbols", {})
        else:
            micro_symbols = micro_data
        if micro_symbols:
            print()
            print("MICROSTRUCTURE V2 SUMMARY")
            print("----------------------------------------------------------------------")
            print("Symbol   Regime         Volatility  Noise   Compression  Expansion")
            print("----------------------------------------------------------------------")
            for sym in sorted(micro_symbols.keys()):
                sym_data = micro_symbols[sym]
                if isinstance(sym_data, dict) and "micro_regime" in sym_data:
                    regime = sym_data.get("micro_regime", "unknown")
                    metrics = sym_data.get("metrics", {})
                    volatility = metrics.get("volatility")
                    noise = metrics.get("noise_score")
                    compression = metrics.get("compression_score")
                    expansion = metrics.get("expansion_score")
                    
                    vol_str = f"{volatility:.6f}" if volatility is not None else " — "
                    noise_str = f"{noise:.2f}" if noise is not None else " — "
                    comp_str = f"{compression:.2f}" if compression is not None else " — "
                    exp_str = f"{expansion:.2f}" if expansion is not None else " — "
                    
                    print(f"{sym:<8} {regime:<15} {vol_str:<11} {noise_str:<7} {comp_str:<13} {exp_str}")
        
        # EXECUTION QUALITY V2 SUMMARY (Phase 1)
        exec_quality_data = execution_quality.get("data", {}) if isinstance(execution_quality, dict) and "data" in execution_quality else execution_quality
        if exec_quality_data and isinstance(exec_quality_data, dict):
            print()
            print("EXECUTION QUALITY V2 SUMMARY")
            print("----------------------------------------------------------------------")
            print("Symbol   Overall Label   Friendly Regimes        Hostile Regimes")
            print("----------------------------------------------------------------------")
            for sym in sorted(exec_quality_data.keys()):
                sym_data = exec_quality_data[sym]
                if isinstance(sym_data, dict):
                    summary = sym_data.get("summary", {})
                    overall_label = summary.get("overall_label", "neutral")
                    friendly = summary.get("friendly_regimes", [])
                    hostile = summary.get("hostile_regimes", [])
                    
                    friendly_str = ", ".join(friendly[:2]) if friendly else "none"
                    if len(friendly) > 2:
                        friendly_str += "..."
                    hostile_str = ", ".join(hostile[:2]) if hostile else "none"
                    if len(hostile) > 2:
                        hostile_str += "..."
                    
                    print(f"{sym:<8} {overall_label:<16} {friendly_str:<23} {hostile_str}")
        
        # LIQUIDITY SWEEPS (already exists, but ensure it's gated)
        liq = load_liquidity_sweeps()
        if liq:
            print()
            print("LIQUIDITY SWEEPS")
            print("----------------------------------------------------------------------")
            print("Symbol   Session   Pool    Sweep5m  Sweep15m  Breaker   Strength")
            print("----------------------------------------------------------------------")
            for sym in sorted(liq.keys()):
                info = liq[sym]
                session = info.get("session", "unknown")
                pool = info.get("htf_pool", "none")
                sweep_5m = "Y" if (info.get("sell_sweep_5m") or info.get("buy_sweep_5m")) else "N"
                sweep_15m = "Y" if (info.get("sell_sweep_15m") or info.get("buy_sweep_15m")) else "N"
                breaker = info.get("breaker", "none")
                strength = info.get("strength", 0.0)
                print(f"{sym:<8} {session:<10} {pool:<7} {sweep_5m:<9} {sweep_15m:<10} {breaker:<9} {strength:<8.2f}")
        
        # VOLUME IMBALANCE (already exists, but ensure it's gated)
        vi = load_volume_imbalance()
        if vi:
            print()
            print("VOLUME IMBALANCE (RECENT)")
            print("----------------------------------------------------------------------")
            print("Symbol   AvgImb  Strength  CVDTrend   Absorb  Exhaust")
            print("----------------------------------------------------------------------")
            for sym, info in vi.items():
                avg_imb = info.get("avg_imbalance")
                strength = info.get("strength") or info.get("imbalance_strength")
                cvd = info.get("cvd_trend", "unknown")
                ab = info.get("absorb_count") or info.get("absorption_count", 0)
                ex = info.get("exhaust_count") or info.get("exhaustion_count", 0)
                if avg_imb is None:
                    avg_str = " — "
                else:
                    avg_str = f"{avg_imb:6.2f}"
                if strength is None:
                    st_str = " — "
                else:
                    st_str = f"{strength:8.2f}"
                print(f"{sym:<8} {avg_str} {st_str} {cvd:<9} {ab:>6} {ex:>8}")
        
        # MARKET STRUCTURE (already exists, but ensure it's gated)
        ms = load_market_structure()
        if ms:
            print()
            print("MARKET STRUCTURE (1h + SESSION)")
            print("----------------------------------------------------------------------")
            print("Symbol   Session Struct1h Conf EqH EqL OB FVG")
            print("----------------------------------------------------------------------")
            for sym, info in ms.items():
                session = info.get("session", "unknown")
                struct = info.get("structure_1h", "neutral")
                conf = info.get("structure_confidence")
                eqh = "Y" if info.get("equal_highs_1h") else "N"
                eql = "Y" if info.get("equal_lows_1h") else "N"
                ob = info.get("order_block_1h", "none")
                fvg = info.get("fvg_1h", "none")
                if conf is None:
                    conf_str = " — "
                else:
                    conf_str = f"{conf:5.2f}"
                print(f"{sym:<8} {session:<8} {struct:<8} {conf_str:<5} {eqh:^3} {eql:^3} {ob:<7} {fvg:<7}")
    
    # Phase 2: Regime V2 and Confidence V2 sections
    print_regime_v2_summary()
    print_confidence_v2_summary()
    
    print_dream_patterns(dream_output)
    print_meta_issues(meta_report)
    print_footer(symbols, reflection_output, are_snapshot, quality_scores, dream_output)
    
    # TUNING SELF-EVAL SUMMARY
    print()
    print("TUNING SELF-EVAL SUMMARY")
    print("----------------------------------------------------------------------")
    self_eval_path = RESEARCH_DIR / "tuning_self_eval.json"
    if not self_eval_path.exists():
        print("No tuning self-eval data yet.")
    else:
        try:
            self_eval_data = load_json(self_eval_path)
            summary = self_eval_data.get("summary", {})
            if not summary:
                print("No tuning self-eval summary available.")
            else:
                print("Symbol   improved  degraded  inconclusive")
                print("-" * 50)
                for sym in sorted(summary.keys()):
                    s = summary[sym]
                    improved = s.get("improved", 0)
                    degraded = s.get("degraded", 0)
                    inconclusive = s.get("inconclusive", 0)
                    print(f"{sym:<8} {improved:>8} {degraded:>9} {inconclusive:>13}")
        except Exception:
            print("Error loading tuning self-eval data.")
    # SYMBOL EDGE PROFILES
    profiles = load_edge_profiles()
    print()
    print("SYMBOL EDGE PROFILES")
    print("----------------------------------------------------------------------")
    if not profiles:
        print("No edge profiles available yet.")
    else:
        print("Symbol   Archetype           ShortPF   LongPF   Drift         ExecQL  Qual")
        print("------------------------------------------------------------------------------")
        for sym in sorted(profiles.keys()):
            p = profiles[sym]
            archetype = p.get("archetype", "unknown")
            short_pf = p.get("short_pf", "—")
            long_pf = p.get("long_pf", "—")
            drift = p.get("drift", "unknown")
            exec_label = p.get("exec_label", "unknown")
            qual_score = p.get("quality_score", "—")
            
            # Format values
            short_str = f"{short_pf:.2f}" if isinstance(short_pf, (int, float)) else str(short_pf)
            long_str = f"{long_pf:.2f}" if isinstance(long_pf, (int, float)) else str(long_pf)
            qual_str = f"{qual_score:.0f}" if isinstance(qual_score, (int, float)) else str(qual_score)
            
            print(f"{sym:<8} {archetype:<18} {short_str:>7} {long_str:>8} {drift:<12} {exec_label:<8} {qual_str:>4}")
    
    # TUNING ADVISOR (PER-SYMBOL)
    advisor = load_tuning_advisor()
    print()
    print("TUNING ADVISOR (PER-SYMBOL)")
    print("----------------------------------------------------------------------")
    if not advisor:
        print("No tuning advisor data available yet.")
    else:
        print("Symbol   Rec       ExplTr  Tier   Archetype           ExecQL    Drift")
        print("------------------------------------------------------------------------")
        for sym in sorted(advisor.keys()):
            info = advisor[sym]
            rec = info.get("recommendation", "observe")
            expl = info.get("samples", {}).get("exploration_closes", 0)
            tier = info.get("tier", "unknown")
            archetype = info.get("archetype", "unknown")
            exec_label = info.get("exec_label", "unknown")
            drift = info.get("drift", "unknown")
            
            print(f"{sym:<8} {rec:<8} {expl:<7} {tier:<6} {archetype:<18} {exec_label:<8} {drift:<12}")
    
    # RISK SNAPSHOT
    risk_snapshot = load_risk_snapshot()
    print()
    print("RISK SNAPSHOT")
    print("----------------------------------------------------------------------")
    if not risk_snapshot:
        print("No risk snapshot data available yet.")
    else:
        print("Symbol   Size    SL      TP      Blocked  Micro         ExecQL  Tier")
        print("------------------------------------------------------------------------")
        for sym in sorted(risk_snapshot.keys()):
            info = risk_snapshot[sym]
            size = info.get("suggested_size", 0.0)
            sl = info.get("suggested_sl", 0.0)
            tp = info.get("suggested_tp", 0.0)
            blocked = "YES" if info.get("blocked", False) else "NO"
            factors = info.get("factors", {})
            micro = factors.get("micro_regime", "unknown")
            exec_label = factors.get("exec_label", "unknown")
            tier = factors.get("tier", "unknown")
            
            print(f"{sym:<8} {size:>5.2f} {sl:>6.4f} {tp:>6.4f} {blocked:<7} {micro:<12} {exec_label:<8} {tier:<6}")
    
    # SCM (Sample Collection Mode) STATE
    scm_state = load_scm_state()
    print()
    print("SCM (Sample Collection Mode) STATE")
    print("----------------------------------------------------------------------")
    if not scm_state:
        print("No SCM state available.")
    else:
        print("Symbol   Level    ExplTr  Tier   ExecQL    Drift         Archetype")
        print("------------------------------------------------------------------------")
        for sym in sorted(scm_state.keys()):
            info = scm_state[sym]
            level = info.get("scm_level", "normal")
            expl = info.get("samples", {}).get("exploration_closes", 0)
            tier = info.get("tier", "unknown")
            exec_label = info.get("exec_label", "unknown")
            drift = info.get("drift", "unknown")
            archetype = info.get("archetype", "unknown")
            
            print(f"{sym:<8} {level:<7} {expl:<7} {tier:<6} {exec_label:<8} {drift:<12} {archetype:<18}")
    
    # LIQUIDITY SWEEPS
    liq_sweeps = load_liquidity_sweeps()
    print()
    print("LIQUIDITY SWEEPS")
    print("----------------------------------------------------------------------")
    if not liq_sweeps:
        print("No liquidity sweeps data available.")
    else:
        print("Symbol   Session   Pool    Sweep5m  Sweep15m  Breaker   Strength")
        print("------------------------------------------------------------------------")
        for sym in sorted(liq_sweeps.keys()):
            info = liq_sweeps[sym]
            session = info.get("session", "Unknown")
            pool = info.get("htf_pool", "none")
            sweep_5m = "Y" if (info.get("sell_sweep_5m") or info.get("buy_sweep_5m")) else "N"
            sweep_15m = "Y" if (info.get("sell_sweep_15m") or info.get("buy_sweep_15m")) else "N"
            breaker = info.get("breaker", "none")
            strength = info.get("strength", 0.0)
            
            print(f"{sym:<8} {session:<8} {pool:<6} {sweep_5m:<8} {sweep_15m:<9} {breaker:<8} {strength:<8.2f}")
    
    # VOLUME IMBALANCE
    vol_imb = load_volume_imbalance()
    print()
    print("VOLUME IMBALANCE (RECENT)")
    print("----------------------------------------------------------------------")
    if not vol_imb:
        print("No volume imbalance data available.")
    else:
        print("Symbol   AvgImb  Strength  CVDTrend   Absorb  Exhaust")
        print("------------------------------------------------------------------------")
        for sym in sorted(vol_imb.keys()):
            info = vol_imb[sym]
            avg_imb = info.get("avg_imbalance")
            strength = info.get("strength") or info.get("imbalance_strength")  # Support both field names
            cvd = info.get("cvd_trend", "neutral")
            ab = info.get("absorb_count") or info.get("absorption_count", 0)  # Support both field names
            ex = info.get("exhaust_count") or info.get("exhaustion_count", 0)  # Support both field names
            
            if avg_imb is None:
                avg_str = "  —  "
            else:
                avg_str = f"{avg_imb:6.2f}"
            
            if strength is None:
                st_str = "  —  "
            else:
                st_str = f"{strength:8.2f}"
            
            print(f"{sym:<8} {avg_str} {st_str} {cvd:<9} {ab:>6} {ex:>8}")
    
    # MARKET STRUCTURE
    mkt_struct = load_market_structure()
    print()
    print("MARKET STRUCTURE (1h + SESSION)")
    print("----------------------------------------------------------------------")
    if not mkt_struct:
        print("No market structure data available.")
    else:
        print("Symbol   Session   Struct1h  Conf   EqH  EqL  OB       FVG")
        print("------------------------------------------------------------------------")
        for sym in sorted(mkt_struct.keys()):
            info = mkt_struct[sym]
            session = info.get("session", "unknown")
            struct = info.get("structure_1h", "neutral")
            conf = info.get("structure_confidence")
            eqh = "Y" if info.get("equal_highs_1h") else "N"
            eql = "Y" if info.get("equal_lows_1h") else "N"
            ob = info.get("order_block_1h", "none")
            fvg = info.get("fvg_1h", "none")
            
            if conf is None:
                conf_str = "  —  "
            else:
                conf_str = f"{conf:5.2f}"
            
            print(f"{sym:<8} {session:<8} {struct:<8} {conf_str}  {eqh:^3}  {eql:^3} {ob:<7} {fvg:<7}")
    
    # CAPITAL OVERVIEW (PF Time-Series + Capital Protection)
    print_capital_overview(capital_payload)
    
    # EXPLORATION POLICY V3 (Phase 3a)
    # Load exploration policy data directly
    exploration_policy_path = REPORTS_DIR / "research" / "exploration_policy_v3.json"
    exploration_payload = {}
    if exploration_policy_path.exists():
        try:
            exploration_data = load_json(exploration_policy_path)
            if exploration_data:
                exploration_payload = {
                    "exploration_policy_v3": {
                        "meta": exploration_data.get("meta", {}),
                        "symbols": exploration_data.get("symbols", {}),
                    }
                }
        except Exception:
            pass
    print_exploration_policy_v3(exploration_payload)
    
    # CAPITAL PLAN (Phase 4a)
    # Load capital plan data directly
    capital_plan_path = REPORTS_DIR / "risk" / "capital_plan.json"
    capital_plan_payload = {}
    if capital_plan_path.exists():
        try:
            capital_plan_data = load_json(capital_plan_path)
            if capital_plan_data:
                capital_plan_payload = {
                    "capital_plan": {
                        "meta": capital_plan_data.get("meta", {}),
                        "symbols": capital_plan_data.get("symbols", {}),
                        "marksman_top5": capital_plan_data.get("marksman_top5", []),
                    }
                }
        except Exception:
            pass
    print_capital_plan(capital_plan_payload)
    print_exploit_lane_gate({})  # Phase 4l: Exploit Lane Gate section
    print_exploit_readiness_summary({})  # Phase 4L+: Exploit Readiness Summary
    print_micro_paper_exploit_status(capital_payload)  # Phase 5c: Micro-Paper Exploit Status
    print_exploit_micro_lane({})  # Phase 5c: Exploit Micro Lane (legacy)
    print_exploit_param_proposals({})  # Exploit Parameter Mutation Proposals
    print_shadow_exploit_lane({})  # Phase 5a: Shadow Exploit Lane
    print_shadow_exploit_scorecard({})  # Phase 5b: Shadow Exploit Scorecard
    print_model_a_timer_compliance()  # Model A: Timer Compliance Check
    print_probe_lane_gate_status()  # Probe Lane Gate: Auto-Enable/Disable
    print_probe_lane_status()  # Probe Lane: Micro-Live Exploration During Halt
    print_promotion_gate_status()  # Promotion Gate: Probe → Exploit
    print_recovery_ramp_status()  # Phase 5H: Recovery Ramp Status
    print_recovery_ramp_v2_status()  # Phase 5H.2: Recovery Ramp V2 (Per-Symbol)
    print_pf_sources_interpretation()  # Phase 5H.2: PF Sources & Interpretation
    print_recovery_lane_v2_status()  # Phase 5H.2: Recovery Lane V2
    print_recovery_v2_score()  # Phase 5H.3: Recovery V2 Performance Score
    print_recovery_assist_status()  # Phase 5H.4: Recovery Assist
    print_micro_core_ramp_status()  # Phase 5H.4: Micro Core Ramp
    print_shadow_promotion_candidates({})  # Phase 5b: Shadow Promotion Candidates
    print_exploit_arming_status()  # Phase 5d: Exploit Auto-Arming Status
    print_quarantine_status()  # Phase 5g: Loss-Contributor Quarantine Status
    print_pf_attribution()  # Phase 5e: PF Attribution & Capital Mode Diagnosis
    print_readynow_trace()  # Phase 5e: ReadyNow Trace
    print_phase5_readiness_panel()  # Phase 5d: Unified Readiness Panel
    print_capital_alignment({})  # Reads files directly, payload not needed
    print_capital_momentum({})  # Reads files directly, payload not needed
    print_pf_validity({})  # Reads files directly, payload not needed
    print_pf_normalization({})  # Reads files directly, payload not needed
    print_live_candidate_readiness({})  # Reads files directly, payload not needed
    
    print()
    print("=" * 70)
    print()
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # Handle broken pipe gracefully (e.g., when piped to head/tail)
        sys.stderr.close()
        sys.exit(0)
