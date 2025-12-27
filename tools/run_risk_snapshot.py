"""
Run Risk Snapshot - Generate per-symbol risk posture snapshot.

This tool computes position sizing, SL/TP, and risk filters for each symbol
based on all available research intelligence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.risk.position_sizer import compute_position_size
from engine_alpha.risk.regime_risk_filters import should_block_trade
from engine_alpha.risk.dynamic_sl_tp import compute_dynamic_sl_tp
from engine_alpha.research.symbol_edge_profiler import load_symbol_edge_profiles
from engine_alpha.research.trade_stats import load_trade_counts
from engine_alpha.core.paths import REPORTS

RISK_DIR = REPORTS / "risk"
RISK_SNAPSHOT_PATH = RISK_DIR / "risk_snapshot.json"


def _load_json_or_empty(path: Path) -> Dict[str, Any]:
    """Load JSON file or return empty dict if missing/invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def build_risk_snapshot() -> Dict[str, Dict[str, Any]]:
    """
    Build per-symbol risk snapshot with sizing, SL/TP, and filters.
    
    Returns:
        Dict mapping symbol -> risk snapshot dict
    """
    # Load edge profiles (contains tier, archetype, drift, micro_regime, exec_label, etc.)
    edge_profiles = load_symbol_edge_profiles()
    
    # Load trade counts for sample-size verification
    trade_counts = load_trade_counts()
    
    # Load rotation recommendations
    rotation_path = REPORTS / "research" / "auto_rotation_recs.json"
    rotation = _load_json_or_empty(rotation_path)
    
    # Load microstructure snapshot for volatility
    micro_path = REPORTS / "research" / "microstructure_snapshot_15m.json"
    micro_data = _load_json_or_empty(micro_path)
    if "symbols" in micro_data:
        micro_symbols = micro_data.get("symbols", {})
    else:
        micro_symbols = micro_data
    
    # Phase 12: Load ASE data for advisory risk flags
    liq_sweeps_path = REPORTS / "research" / "liquidity_sweeps.json"
    liq_sweeps_data = _load_json_or_empty(liq_sweeps_path)
    liq_sweeps = liq_sweeps_data.get("symbols", {}) if "symbols" in liq_sweeps_data else liq_sweeps_data
    
    vol_imb_path = REPORTS / "research" / "volume_imbalance.json"
    vol_imb_data = _load_json_or_empty(vol_imb_path)
    vol_imb = vol_imb_data.get("symbols", {}) if "symbols" in vol_imb_data else vol_imb_data
    
    mkt_struct_path = REPORTS / "research" / "market_structure.json"
    mkt_struct_data = _load_json_or_empty(mkt_struct_path)
    mkt_struct = mkt_struct_data.get("symbols", {}) if "symbols" in mkt_struct_data else mkt_struct_data
    
    snapshot: Dict[str, Dict[str, Any]] = {}
    
    for sym, profile in edge_profiles.items():
        if not isinstance(profile, dict):
            continue
        
        # Extract inputs from edge profile
        tier = profile.get("tier", "tier3")
        archetype = profile.get("archetype", "unknown")
        drift_status = profile.get("drift", "insufficient_data")
        micro_regime = profile.get("micro_regime", "unknown")
        exec_label = profile.get("exec_label", "unknown")
        short_pf = profile.get("short_pf")
        long_pf = profile.get("long_pf")
        samples = profile.get("samples", {})
        expl_closes = samples.get("exploration_closes", 0)
        
        # Get rotation signal
        rot_info = rotation.get(sym, {})
        if isinstance(rot_info, dict):
            rotation_signal = rot_info.get("rotation", "hold")
        else:
            rotation_signal = "hold"
        
        # Get volatility from microstructure
        micro_info = micro_symbols.get(sym, {})
        volatility = 0.002  # Default
        if isinstance(micro_info, dict):
            if "metrics" in micro_info:
                volatility = micro_info.get("metrics", {}).get("volatility", volatility)
            elif "volatility" in micro_info:
                volatility = micro_info.get("volatility", volatility)
        
        # Build risk inputs
        risk_inputs = {
            "tier": tier,
            "exploration_pf": short_pf,
            "normal_pf": long_pf,
            "drift_status": drift_status,
            "micro_regime": micro_regime,
            "execution_label": exec_label,
            "archetype": archetype,
            "rotation_signal": rotation_signal,
            "confidence": 0.7,  # Default confidence (could be enhanced later)
            "volatility": volatility,
            "exploration_closes": expl_closes,
        }
        
        # Compute position size
        size, size_notes = compute_position_size(sym, risk_inputs)
        
        # Check risk filters
        blocked, block_reasons = should_block_trade(sym, risk_inputs)
        
        # Compute dynamic SL/TP
        sl_tp = compute_dynamic_sl_tp(sym, volatility, micro_regime, archetype)
        
        # Phase 12: Add ASE-based advisory risk flags
        advisory_risk_flags: list[str] = []
        
        liq_info = liq_sweeps.get(sym, {})
        vi_info = vol_imb.get(sym, {})
        ms_info = mkt_struct.get(sym, {})
        
        # Liquidity sweep risk
        swept_high = liq_info.get("sell_sweep_5m") or liq_info.get("sell_sweep_15m")
        swept_low = liq_info.get("buy_sweep_5m") or liq_info.get("buy_sweep_15m")
        breaker = liq_info.get("breaker", "none")
        
        if swept_high and breaker == "bearish":
            advisory_risk_flags.append("Sweep of highs + bearish breaker: HIGH RISK for longs")
        if swept_low and breaker == "bullish":
            advisory_risk_flags.append("Sweep of lows + bullish breaker: HIGH RISK for shorts")
        
        # Volume imbalance risk
        absorption = vi_info.get("absorption_count", 0) > 0
        exhaustion = vi_info.get("exhaustion_count", 0) > 0
        
        if absorption:
            advisory_risk_flags.append("Absorption detected: REDUCE SIZE")
        if exhaustion:
            advisory_risk_flags.append("Exhaustion: TAKE PROFITS EARLY")
        
        # Market structure risk
        struct_conf = ms_info.get("structure_confidence")
        order_block = ms_info.get("order_block_1h", "none")
        structure = ms_info.get("structure_1h", "neutral")
        
        if struct_conf is not None and struct_conf < 0.3:
            advisory_risk_flags.append("Low structure confidence: CONSERVATIVE SIZING")
        
        if order_block != "none" and structure != "neutral":
            if order_block == "bearish" and structure == "bullish":
                advisory_risk_flags.append("HTF order block overhead: EXPECT REJECTION")
            elif order_block == "bullish" and structure == "bearish":
                advisory_risk_flags.append("HTF order block below: EXPECT SUPPORT")
        
        snapshot[sym] = {
            "symbol": sym,
            "suggested_size": size,
            "suggested_sl": sl_tp["sl"],
            "suggested_tp": sl_tp["tp"],
            "blocked": blocked,
            "block_reasons": block_reasons,
            "size_notes": size_notes,
            "sl_tp_notes": sl_tp["notes"],
            "advisory_risk_flags": advisory_risk_flags,  # Phase 12: ASE-based advisory flags
            "factors": {
                "tier": tier,
                "archetype": archetype,
                "drift": drift_status,
                "micro_regime": micro_regime,
                "exec_label": exec_label,
                "rotation": rotation_signal,
                "volatility": volatility,
                "exploration_closes": expl_closes,
            },
        }
    
    # Save snapshot
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": snapshot,
    }
    
    RISK_DIR.mkdir(parents=True, exist_ok=True)
    RISK_SNAPSHOT_PATH.write_text(json.dumps(output, indent=2))
    
    return snapshot


def main() -> int:
    """Main entry point."""
    print("RISK SNAPSHOT")
    print("=" * 70)
    print()
    
    try:
        snapshot = build_risk_snapshot()
        
        if not snapshot:
            print("⚠️  No risk snapshot generated; check inputs.")
            print()
            print("Ensure the following files exist:")
            print("  - reports/research/symbol_edge_profile.json")
            print("  - reports/research/microstructure_snapshot_15m.json")
            print("  - reports/research/auto_rotation_recs.json")
            return 0
        
        print("Symbol   Size    SL      TP      Blocked  Micro         ExecQL  Tier")
        print("-" * 90)
        
        for sym in sorted(snapshot.keys()):
            info = snapshot[sym]
            size = info.get("suggested_size", 0.0)
            sl = info.get("suggested_sl", 0.0)
            tp = info.get("suggested_tp", 0.0)
            blocked = "YES" if info.get("blocked", False) else "NO"
            factors = info.get("factors", {})
            micro = factors.get("micro_regime", "unknown")
            exec_label = factors.get("exec_label", "unknown")
            tier = factors.get("tier", "unknown")
            
            print(f"{sym:<8} {size:>5.2f} {sl:>6.4f} {tp:>6.4f} {blocked:<7} {micro:<12} {exec_label:<8} {tier:<6}")
        
        print()
        print("=" * 70)
        print(f"✅ Risk snapshot written to: {RISK_SNAPSHOT_PATH}")
        print()
        print("Note: All risk outputs are advisory-only and PAPER-safe.")
        print("No configs or live trading logic are changed.")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Risk snapshot failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

