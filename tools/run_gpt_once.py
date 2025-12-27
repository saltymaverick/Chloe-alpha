#!/usr/bin/env python3
"""
Manual GPT reflection runner (operator tool).

Runs GPT reflection on the latest reflection packet without touching offset gates.
Useful for:
- Smoke testing GPT integration
- Manual diagnosis requests
- Validating GPT outputs without waiting for a close event

This tool bypasses the offset gate but still respects other safety checks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.gpt_reflection_runner import (
    load_engine_config,
    run_gpt_reflection,
    _load_gpt_state,
)
from engine_alpha.reflect.gpt_tuner_diff import compute_diff, write_diff, load_tuner_config
from engine_alpha.reflect.reflection_packet import build_reflection_packet
from engine_alpha.core.atomic_io import atomic_write_json, atomic_append_jsonl
from engine_alpha.core.snapshot import snapshot_get


def main() -> int:
    """Run GPT reflection once on latest packet."""
    print("=" * 60)
    print("GPT Reflection Smoke Test / Manual Runner")
    print("=" * 60)
    
    # Load config
    cfg = load_engine_config()
    
    if not cfg.get("enable_gpt_reflection", False):
        print("❌ GPT reflection is disabled in config")
        print("   Set enable_gpt_reflection: true in config/engine_config.json")
        return 1
    
    # Load latest snapshot
    snapshot_path = REPORTS / "latest_snapshot.json"
    if not snapshot_path.exists():
        print(f"❌ Latest snapshot not found: {snapshot_path}")
        print("   Run the main loop at least once to generate a snapshot")
        return 1
    
    try:
        with snapshot_path.open("r", encoding="utf-8") as f:
            snapshot = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load snapshot: {e}")
        return 1
    
    print(f"✅ Loaded snapshot: {snapshot.get('ts', 'unknown')}")
    
    # Build reflection packet
    print("\n📦 Building reflection packet...")
    packet = build_reflection_packet(snapshot)
    
    # Check self-trust state
    self_trust = packet.get("primitives", {}).get("self_trust", {})
    samples_processed = self_trust.get("samples_processed", 0)
    n_samples = self_trust.get("n_samples", 0)
    
    print(f"   samples_processed: {samples_processed}")
    print(f"   n_samples: {n_samples}")
    
    # Check GPT state
    gpt_state = _load_gpt_state()
    print(f"\n📊 GPT State:")
    print(f"   last_gpt_trade_log_offset: {gpt_state.get('last_gpt_trade_log_offset')}")
    print(f"   last_run_ts: {gpt_state.get('last_run_ts', 'never')}")
    
    # Warn if no new samples
    if samples_processed == 0:
        print("\n⚠️  WARNING: No new closes processed (samples_processed=0)")
        print("   GPT will analyze historical data only")
        print("   This is fine for smoke testing, but real runs require new closes")
    
    # Run GPT reflection (bypass offset gate for manual runs)
    print("\n🤖 Running GPT reflection...")
    try:
        gpt_result = run_gpt_reflection(packet, cfg)
        
        if not gpt_result:
            print("❌ GPT reflection returned None (check logs for errors)")
            return 1
        
        print("✅ GPT reflection completed")
        print(f"   Model: {gpt_result.get('model')}")
        print(f"   Tokens: {gpt_result.get('tokens')}")
        print(f"   Observations: {len(gpt_result.get('observations', []))}")
        print(f"   Proposed changes: {len(gpt_result.get('proposed_changes', []))}")
        
        # Write outputs
        print("\n💾 Writing outputs...")
        
        # Write to JSONL
        reflect_dir = Path(__file__).parent.parent / "engine_alpha" / "reflect"
        reflect_dir.mkdir(parents=True, exist_ok=True)
        gpt_reflection_path = reflect_dir / "gpt_reflection.jsonl"
        atomic_append_jsonl(gpt_reflection_path, gpt_result)
        print(f"   ✅ Appended to: {gpt_reflection_path}")
        
        # Write latest reflection
        latest_reflection_path = REPORTS / "gpt_reflection_latest.json"
        atomic_write_json(latest_reflection_path, gpt_result)
        print(f"   ✅ Written to: {latest_reflection_path}")
        
        # Compute and write diff
        tuner_cfg = load_tuner_config()
        ts = packet.get("ts") or snapshot.get("ts", "")
        diff = compute_diff(tuner_cfg, gpt_result.get("proposed_changes", []), ts)
        write_diff(diff)
        print(f"   ✅ Diff written to: reports/gpt_tuner_diff.json")
        
        # Show summary
        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"✅ GPT reflection completed successfully")
        print(f"✅ Outputs written to:")
        print(f"   - {gpt_reflection_path}")
        print(f"   - {latest_reflection_path}")
        print(f"   - reports/gpt_tuner_diff.json")
        print(f"   - reports/gpt_tuner_diff.jsonl")
        
        # Show proposed changes from the actual diff file (not GPT raw output)
        diff_path = REPORTS / "gpt_tuner_diff.json"
        if diff_path.exists():
            try:
                with diff_path.open("r", encoding="utf-8") as f:
                    diff = json.load(f)
                changes = diff.get("changes", [])
                if changes:
                    print(f"\n📝 Proposed changes ({len(changes)}):")
                    for change in changes[:5]:  # Show first 5
                        key = change.get("key", "unknown")
                        current = change.get("current", "?")
                        proposed = change.get("proposed", "?")
                        reason = change.get("reason", "")[:60]
                        print(f"   - {key}: {current} → {proposed} ({reason}...)")
                    
                    # Show stats
                    if diff.get("noop_count", 0) > 0:
                        print(f"   (Note: {diff['noop_count']} no-op changes filtered)")
                    if diff.get("invalid_count", 0) > 0:
                        print(f"   (Note: {diff['invalid_count']} invalid changes rejected)")
                    if diff.get("risk"):
                        print(f"   ⚠️  Risk: {diff['risk']}")
                else:
                    print("\n📝 No proposed changes (GPT found no tuning opportunities)")
            except Exception as e:
                print(f"\n⚠️  Could not read diff file: {e}")
                # Fallback to GPT raw output
                if gpt_result.get("proposed_changes"):
                    print(f"\n📝 Proposed changes (from GPT output):")
                    for change in gpt_result["proposed_changes"][:5]:
                        key = change.get("key", "unknown")
                        proposed = change.get("proposed", "?")
                        reason = change.get("reason", "")[:60]
                        print(f"   - {key}: ? → {proposed} ({reason}...)")
        else:
            print("\n📝 No diff file found (check if GPT reflection completed)")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error running GPT reflection: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

