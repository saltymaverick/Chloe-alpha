#!/usr/bin/env python3
"""
Diagnose Why Chloe Isn't Opening Trades

Checks all 5 potential blockers:
1. Regime + threshold tests
2. Quant gate blocking
3. Decision logic not producing signals
4. _try_open() never called
5. No new candles / run_step_live stalled
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

CONFIG_DIR = ROOT_DIR / "config"
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
LOGS_DIR = ROOT_DIR / "logs"
DATA_DIR = ROOT_DIR / "data" / "ohlcv"


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if missing."""
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def check_regime_thresholds() -> Dict[str, Any]:
    """Check 1: Regime + threshold tests."""
    print("\n" + "=" * 80)
    print("🔍 CHECK 1: Regime + Threshold Tests")
    print("=" * 80)
    
    # Check entry_thresholds.json
    thresholds_path = CONFIG_DIR / "entry_thresholds.json"
    thresholds = load_json(thresholds_path)
    
    # Check regime_enable.json
    enable_path = CONFIG_DIR / "regime_enable.json"
    enable = load_json(enable_path)
    
    issues = []
    warnings = []
    
    if not thresholds:
        issues.append("❌ entry_thresholds.json missing or empty")
    else:
        print(f"\n📋 Entry Thresholds ({thresholds_path}):")
        for regime, thresh in thresholds.items():
            if isinstance(thresh, dict):
                enabled = thresh.get("enabled", True)
                entry_min = thresh.get("entry_min_conf", thresh.get("threshold", 0.0))
            else:
                enabled = True
                entry_min = float(thresh) if isinstance(thresh, (int, float)) else 0.0
            
            status = "✅" if enabled else "❌ DISABLED"
            if entry_min > 0.80:
                warnings.append(f"⚠️  {regime}: threshold {entry_min:.2f} is VERY HIGH (>0.80)")
            elif entry_min > 0.70:
                warnings.append(f"⚠️  {regime}: threshold {entry_min:.2f} is high (>0.70)")
            
            print(f"  {status} {regime}: {entry_min:.2f}")
    
    if enable:
        print(f"\n📋 Regime Enable Flags ({enable_path}):")
        for regime, is_enabled in enable.items():
            status = "✅ ENABLED" if is_enabled else "❌ DISABLED"
            if not is_enabled:
                issues.append(f"❌ {regime} is DISABLED")
            print(f"  {status} {regime}")
    
    # Check if any regimes are enabled
    enabled_regimes = [r for r, e in enable.items() if e] if enable else []
    if not enabled_regimes:
        issues.append("❌ NO REGIMES ENABLED - Chloe cannot trade!")
    
    return {
        "thresholds": thresholds,
        "enable": enable,
        "enabled_regimes": enabled_regimes,
        "issues": issues,
        "warnings": warnings,
    }


def check_quant_gate() -> Dict[str, Any]:
    """Check 2: Quant gate blocking."""
    print("\n" + "=" * 80)
    print("🔍 CHECK 2: Quant Gate Blocking")
    print("=" * 80)
    
    issues = []
    warnings = []
    
    # Check PF_local
    pf_path = REPORTS_DIR / "pf_local.json"
    pf = load_json(pf_path)
    pf_val = float(pf.get("pf", pf.get("pf_local", 1.0)))
    
    print(f"\n📊 PF Local: {pf_val:.3f}")
    if pf_val < 0.90:
        issues.append(f"🚨 PF_local={pf_val:.3f} < 0.90 (HARD BLOCK)")
    elif pf_val < 0.95:
        warnings.append(f"⚠️  PF_local={pf_val:.3f} < 0.95 (WARNING)")
    else:
        print("  ✅ PF_local OK")
    
    # Check drawdown
    dd = float(pf.get("drawdown", 0.0))
    print(f"📉 Drawdown: {dd:.2%}")
    if dd > 0.25:
        issues.append(f"🚨 Drawdown={dd:.2%} > 25% (HARD BLOCK)")
    elif dd > 0.15:
        warnings.append(f"⚠️  Drawdown={dd:.2%} > 15% (WARNING)")
    else:
        print("  ✅ Drawdown OK")
    
    # Check strategy strength
    strength_path = RESEARCH_DIR / "strategy_strength.json"
    strengths = load_json(strength_path)
    
    if strengths:
        print(f"\n📊 Strategy Strengths ({strength_path}):")
        negative_regimes = []
        for regime, info in strengths.items():
            edge = float(info.get("edge", 0.0))
            status = "✅" if edge > 0 else "❌"
            if edge < -0.0005:
                negative_regimes.append(f"{regime} (edge={edge:.5f})")
            print(f"  {status} {regime}: edge={edge:.5f}")
        
        if negative_regimes:
            warnings.append(f"⚠️  Negative edge regimes: {', '.join(negative_regimes)}")
    else:
        warnings.append("⚠️  strategy_strength.json missing")
    
    # Check confidence map
    conf_map_path = CONFIG_DIR / "confidence_map.json"
    conf_map = load_json(conf_map_path)
    
    if conf_map:
        print(f"\n📊 Confidence Map ({conf_map_path}):")
        negative_buckets = []
        for bucket, info in conf_map.items():
            expected_ret = float(info.get("expected_return", 0.0))
            if expected_ret < -0.0005:
                negative_buckets.append(f"bucket_{bucket} (ret={expected_ret:.5f})")
        
        if negative_buckets:
            warnings.append(f"⚠️  Negative expected return buckets: {', '.join(negative_buckets[:5])}")
        else:
            print("  ✅ Confidence map OK")
    else:
        warnings.append("⚠️  confidence_map.json missing")
    
    # Check blind spots
    blind_spot_path = RESEARCH_DIR / "blind_spots.jsonl"
    blind_spot_count = 0
    if blind_spot_path.exists():
        try:
            with blind_spot_path.open("r") as f:
                blind_spot_count = sum(1 for _ in f)
        except Exception:
            pass
    
    print(f"\n👁️  Blind Spots: {blind_spot_count}")
    if blind_spot_count > 0:
        warnings.append(f"⚠️  {blind_spot_count} blind spot alerts logged")
    
    return {
        "pf_local": pf_val,
        "drawdown": dd,
        "strengths": strengths,
        "conf_map": conf_map,
        "blind_spots": blind_spot_count,
        "issues": issues,
        "warnings": warnings,
    }


def check_logs_for_signals() -> Dict[str, Any]:
    """Check 3: Decision logic producing signals."""
    print("\n" + "=" * 80)
    print("🔍 CHECK 3: Decision Logic (Signal Production)")
    print("=" * 80)
    
    issues = []
    warnings = []
    
    # Search logs for decision-related entries
    log_files = list(LOGS_DIR.glob("*.log")) if LOGS_DIR.exists() else []
    
    if not log_files:
        warnings.append("⚠️  No log files found in logs/")
        return {"issues": issues, "warnings": warnings, "log_files": []}
    
    print(f"\n📋 Found {len(log_files)} log files")
    
    # Search for decision-related patterns
    patterns = {
        "decision": [],
        "gate": [],
        "blocked": [],
        "try_open": [],
        "ENTRY": [],
        "regime": [],
        "confidence": [],
    }
    
    for log_file in sorted(log_files, key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
        try:
            with log_file.open("r") as f:
                lines = f.readlines()
                for i, line in enumerate(lines):
                    line_lower = line.lower()
                    for pattern in patterns.keys():
                        if pattern in line_lower:
                            patterns[pattern].append((log_file.name, i+1, line.strip()[:100]))
        except Exception:
            continue
    
    # Show recent entries
    for pattern, entries in patterns.items():
        if entries:
            print(f"\n📌 Recent '{pattern}' entries (last 3):")
            for log_name, line_num, line_text in entries[-3:]:
                print(f"  {log_name}:{line_num} - {line_text}")
    
    # Check for "blocked" entries
    if patterns["blocked"]:
        issues.append(f"🚨 Found {len(patterns['blocked'])} 'blocked' entries in logs")
    
    # Check for "try_open" entries
    if not patterns["try_open"]:
        warnings.append("⚠️  No 'try_open' entries found - _try_open() may not be called")
    
    # Check for "ENTRY" entries
    if not patterns["ENTRY"]:
        warnings.append("⚠️  No 'ENTRY' entries found - no trades opened recently")
    
    return {
        "log_files": [f.name for f in log_files[:5]],
        "patterns": {k: len(v) for k, v in patterns.items()},
        "issues": issues,
        "warnings": warnings,
    }


def check_candle_updates() -> Dict[str, Any]:
    """Check 5: New candles / run_step_live stalled."""
    print("\n" + "=" * 80)
    print("🔍 CHECK 5: Candle Updates / run_step_live Status")
    print("=" * 80)
    
    issues = []
    warnings = []
    
    # Check live candle file
    live_candle_path = DATA_DIR / "ETHUSDT_1h_live.csv"
    
    if not live_candle_path.exists():
        issues.append("❌ ETHUSDT_1h_live.csv missing - no live candles recorded")
        return {"issues": issues, "warnings": warnings}
    
    # Read last few lines
    try:
        with live_candle_path.open("r") as f:
            lines = f.readlines()
            if len(lines) < 2:
                issues.append("❌ Live candle file has < 2 lines (no data)")
                return {"issues": issues, "warnings": warnings}
            
            # Parse last line (JSONL format)
            last_line = lines[-1].strip()
            if last_line.startswith("{"):
                import json
                last_candle = json.loads(last_line)
                ts_str = last_candle.get("ts", "")
                
                # Parse timestamp
                try:
                    if "T" in ts_str:
                        last_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    else:
                        last_ts = datetime.fromtimestamp(float(ts_str), tz=timezone.utc)
                    
                    now = datetime.now(timezone.utc)
                    age = now - last_ts
                    
                    print(f"\n📅 Last Candle:")
                    print(f"  Timestamp: {last_ts.isoformat()}")
                    print(f"  Age: {age}")
                    
                    if age > timedelta(hours=2):
                        issues.append(f"🚨 Last candle is {age} old (> 2 hours) - run_step_live may be stalled")
                    elif age > timedelta(hours=1.5):
                        warnings.append(f"⚠️  Last candle is {age} old (> 1.5 hours)")
                    else:
                        print("  ✅ Candle updates recent")
                    
                    print(f"  Total candles: {len(lines) - 1}")
                    
                except Exception as e:
                    warnings.append(f"⚠️  Could not parse timestamp: {e}")
            else:
                warnings.append("⚠️  Last line is not JSON format")
    
    except Exception as e:
        issues.append(f"❌ Error reading live candle file: {e}")
    
    return {
        "live_candle_path": str(live_candle_path),
        "candle_count": len(lines) - 1 if live_candle_path.exists() else 0,
        "last_candle_age": str(age) if 'age' in locals() else None,
        "issues": issues,
        "warnings": warnings,
    }


def main():
    """Run all diagnostic checks."""
    print("=" * 80)
    print("🔍 CHLOE NO-TRADES DIAGNOSTIC")
    print("=" * 80)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    
    results = {}
    
    # Check 1: Regime + thresholds
    results["regime_thresholds"] = check_regime_thresholds()
    
    # Check 2: Quant gate
    results["quant_gate"] = check_quant_gate()
    
    # Check 3: Decision logic
    results["decision_logic"] = check_logs_for_signals()
    
    # Check 5: Candle updates
    results["candle_updates"] = check_candle_updates()
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    
    all_issues = []
    all_warnings = []
    
    for check_name, check_result in results.items():
        all_issues.extend(check_result.get("issues", []))
        all_warnings.extend(check_result.get("warnings", []))
    
    if all_issues:
        print("\n🚨 CRITICAL ISSUES:")
        for issue in all_issues:
            print(f"  {issue}")
    
    if all_warnings:
        print("\n⚠️  WARNINGS:")
        for warning in all_warnings:
            print(f"  {warning}")
    
    if not all_issues and not all_warnings:
        print("\n✅ No obvious blockers found!")
        print("  Check logs for 'gate_and_size', 'blocked', 'decision', 'try_open'")
        print("  Run: grep -Ei 'gate|blocked|decision|try_open' logs/*.log | tail -n 40")
    
    print("\n" + "=" * 80)
    print("💡 NEXT STEPS")
    print("=" * 80)
    
    if all_issues:
        print("\n1. Fix critical issues above")
        print("2. Check logs: grep -Ei 'gate|blocked|decision|try_open' logs/*.log | tail -n 40")
        print("3. Re-run diagnostic: python3 -m tools.diagnose_no_trades")
    else:
        print("\n1. Check recent logs for 'gate_and_size' or 'blocked' entries")
        print("2. Verify run_step_live is running: check systemd/cron")
        print("3. Check DEBUG_SIGNALS output for decision flow")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()


