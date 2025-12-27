"""
Breakout Reliability Engine - Composite score for breakout reliability.

Combines signals from:
- Market structure (1h structure, confidence)
- Microstructure (regime, noise)
- Liquidity sweeps (strength, direction)
- Volume imbalance (CVD trend, imbalance strength)

All outputs are advisory-only and PAPER-safe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS

RESEARCH_DIR = REPORTS / "research"
BREAKOUT_RELIABILITY_PATH = RESEARCH_DIR / "breakout_reliability.json"

# Constants
BREAKOUT_STRONG_THRESHOLD = 0.7
BREAKOUT_MEDIUM_THRESHOLD = 0.5
VOLUME_IMBALANCE_THRESHOLD = 0.6
NOISE_HIGH_THRESHOLD = 0.6


def _load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def compute_breakout_reliability(
    market_struct: Dict[str, Any],
    micro: Dict[str, Any],
    sweeps: Dict[str, Any],
    volume_imbalance: Dict[str, Any],
    drift: Optional[Dict[str, Any]] = None,
    exec_quality: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Compute breakout reliability score for each symbol.
    
    Args:
        market_struct: Market structure data (from market_structure.json)
        micro: Microstructure data (from microstructure_snapshot_15m.json)
        sweeps: Liquidity sweeps data (from liquidity_sweeps.json)
        volume_imbalance: Volume imbalance data (from volume_imbalance.json)
        drift: Optional drift data (from drift_report.json)
        exec_quality: Optional execution quality data (from execution_quality.json)
    
    Returns:
        Dict mapping symbol -> {
            "symbol": str,
            "score": float (0-1),
            "label": "strong" | "medium" | "weak",
            "factors": List[str]
        }
    """
    results: Dict[str, Dict[str, Any]] = {}
    
    # Extract symbols from market_struct (most authoritative source)
    symbols_data = market_struct.get("symbols", {})
    if not symbols_data:
        # Try direct dict format
        symbols_data = market_struct
    
    symbols = set(symbols_data.keys())
    
    # Also collect symbols from other sources
    micro_symbols = micro.get("symbols", {})
    if micro_symbols:
        symbols.update(micro_symbols.keys())
    
    sweep_symbols = sweeps.get("symbols", {})
    if sweep_symbols:
        symbols.update(sweep_symbols.keys())
    elif isinstance(sweeps, dict):
        symbols.update(sweeps.keys())
    
    vi_symbols = volume_imbalance.get("symbols", {})
    if vi_symbols:
        symbols.update(vi_symbols.keys())
    elif isinstance(volume_imbalance, dict):
        symbols.update(volume_imbalance.keys())
    
    for symbol in symbols:
        score = 0.5  # Start at neutral
        factors: List[str] = []
        
        # Get market structure data
        ms_data = symbols_data.get(symbol, {})
        struct_1h = ms_data.get("structure_1h", "neutral")
        struct_conf = ms_data.get("structure_confidence")
        
        # Get microstructure data
        micro_data = micro_symbols.get(symbol, {})
        if isinstance(micro_data, dict) and "metrics" in micro_data:
            micro_regime = micro_data.get("micro_regime", "unknown")
            metrics = micro_data.get("metrics", {})
            noise_score = metrics.get("noise_score")
        else:
            micro_regime = "unknown"
            noise_score = None
        
        # Get liquidity sweeps data
        sweep_data = sweep_symbols.get(symbol, {}) if isinstance(sweep_symbols, dict) else sweeps.get(symbol, {})
        sweep_strength_val = sweep_data.get("strength", 0.0)
        sweep_strength = float(sweep_strength_val) if isinstance(sweep_strength_val, (int, float)) else 0.0
        htf_pool = sweep_data.get("htf_pool", "none")
        
        # Get volume imbalance data
        vi_data = vi_symbols.get(symbol, {}) if isinstance(vi_symbols, dict) else volume_imbalance.get(symbol, {})
        imb_strength = vi_data.get("imbalance_strength", 0.0) if isinstance(vi_data.get("imbalance_strength"), (int, float)) else 0.0
        cvd_trend = vi_data.get("cvd_trend", "neutral")
        
        # Factor 1: Market structure alignment
        if struct_1h == "bullish" and micro_regime == "clean_trend":
            score += 0.1
            factors.append("bullish 1h structure + clean_trend micro regime")
        elif struct_1h == "bearish" and micro_regime == "clean_trend":
            score += 0.1
            factors.append("bearish 1h structure + clean_trend micro regime")
        
        # Factor 2: Structure confidence
        if struct_conf is not None and struct_conf > 0.6:
            score += 0.05
            factors.append(f"high structure confidence ({struct_conf:.2f})")
        elif struct_conf is not None and struct_conf < 0.3:
            score -= 0.05
            factors.append(f"low structure confidence ({struct_conf:.2f})")
        
        # Factor 3: Liquidity sweeps
        if sweep_strength > 0.7:
            if htf_pool == "below" and struct_1h == "bullish":
                score += 0.1
                factors.append("sweep of lows + bullish structure (reclaim)")
            elif htf_pool == "above" and struct_1h == "bearish":
                score += 0.1
                factors.append("sweep of highs + bearish structure (reclaim)")
            else:
                score += 0.05
                factors.append(f"strong liquidity sweep (strength={sweep_strength:.2f})")
        
        # Factor 4: Volume imbalance
        if imb_strength > VOLUME_IMBALANCE_THRESHOLD:
            if cvd_trend == "bullish" and struct_1h == "bullish":
                score += 0.1
                factors.append("bullish CVD trend + bullish structure")
            elif cvd_trend == "bearish" and struct_1h == "bearish":
                score += 0.1
                factors.append("bearish CVD trend + bearish structure")
            else:
                score += 0.05
                factors.append(f"strong volume imbalance (strength={imb_strength:.2f})")
        
        # Factor 5: Noise penalty
        if noise_score is not None and noise_score > NOISE_HIGH_THRESHOLD:
            score -= 0.1
            factors.append(f"high noise score ({noise_score:.2f})")
        
        # Factor 6: Drift (if available)
        if drift:
            drift_data = drift.get("symbols", {}).get(symbol, {})
            drift_status = drift_data.get("drift", "insufficient_data")
            if drift_status == "degrading":
                score -= 0.1
                factors.append("degrading drift")
            elif drift_status == "improving":
                score += 0.05
                factors.append("improving drift")
        
        # Factor 7: Execution quality (if available)
        if exec_quality:
            eq_data = exec_quality.get("data", {}).get(symbol, {})
            if isinstance(eq_data, dict):
                summary = eq_data.get("summary", {})
                overall_label = summary.get("overall_label", "neutral")
                if overall_label == "hostile":
                    score -= 0.05
                    factors.append("hostile execution environment")
                elif overall_label == "friendly":
                    score += 0.05
                    factors.append("friendly execution environment")
        
        # Clamp score to [0, 1]
        score = max(0.0, min(1.0, score))
        
        # Determine label
        if score >= BREAKOUT_STRONG_THRESHOLD:
            label = "strong"
        elif score >= BREAKOUT_MEDIUM_THRESHOLD:
            label = "medium"
        else:
            label = "weak"
        
        results[symbol] = {
            "symbol": symbol,
            "score": round(score, 3),
            "label": label,
            "factors": factors if factors else ["insufficient data"],
        }
    
    return results


def run_breakout_reliability_scan() -> Dict[str, Dict[str, Any]]:
    """
    Run breakout reliability scan for all symbols.
    
    Loads required JSON files and computes breakout reliability scores.
    
    Returns:
        Dict mapping symbol -> breakout reliability data
    """
    # Load required data files
    market_struct_path = RESEARCH_DIR / "market_structure.json"
    micro_path = RESEARCH_DIR / "microstructure_snapshot_15m.json"
    sweeps_path = RESEARCH_DIR / "liquidity_sweeps.json"
    vi_path = RESEARCH_DIR / "volume_imbalance.json"
    drift_path = RESEARCH_DIR / "drift_report.json"
    exec_quality_path = RESEARCH_DIR / "execution_quality.json"
    
    market_struct = _load_json(market_struct_path)
    micro = _load_json(micro_path)
    sweeps = _load_json(sweeps_path)
    volume_imbalance = _load_json(vi_path)
    drift = _load_json(drift_path) if drift_path.exists() else None
    exec_quality = _load_json(exec_quality_path) if exec_quality_path.exists() else None
    
    # Compute breakout reliability
    results = compute_breakout_reliability(
        market_struct=market_struct,
        micro=micro,
        sweeps=sweeps,
        volume_imbalance=volume_imbalance,
        drift=drift,
        exec_quality=exec_quality,
    )
    
    # Compute health
    health_status = "ok"
    health_reasons = []
    
    if results:
        all_scores_low = all(r.get("score", 0.0) < 0.4 for r in results.values())
        if all_scores_low:
            health_status = "degraded"
            health_reasons.append("no_strong_breakout_candidates")
    
    # Save results
    output = {
        "version": "v2.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "health": {
            "status": health_status,
            "reasons": health_reasons,
        },
        "symbols": results,
    }
    
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    BREAKOUT_RELIABILITY_PATH.write_text(json.dumps(output, indent=2))
    
    return results
