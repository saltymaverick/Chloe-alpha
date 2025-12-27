"""
Hindsight Cycle Tool (Phase 4m)
---------------------------------

Single entry point for continuous hindsight learning.

This tool orchestrates:
  - Reflection: Runs frequently (every 3 hours) - cheap, insight-only
  - Tuner: Runs nightly when conditions allow - proposes parameter changes
  - Dream: Runs nightly when conditions allow - long-horizon pattern synthesis

Safety:
  - Reflection always runs (safe, read-only analysis)
  - Tuner/Dream only run when:
    * capital_mode == "normal"
    * PF_30D >= 1.00
  - Never mutates live configs directly
  - Writes proposals + annotations only

This tool is designed to run via systemd timers:
  - chloe-hindsight-reflection.timer (every 3 hours)
  - chloe-hindsight-nightly.timer (nightly at 03:30 UTC)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS

MODE_REFLECTION_ONLY = "reflection"
MODE_FULL = "full"


def _load_capital_protection() -> dict:
    """Load capital protection data."""
    path = REPORTS / "risk" / "capital_protection.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _log(msg: str) -> None:
    """Log message with timestamp."""
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[hindsight {ts}] {msg}")


def run_reflection(reason: str = "scheduled") -> None:
    """Run reflection on recent trades."""
    try:
        from engine_alpha.reflect.gpt_reflection import reflect_on_batch
        
        _log(f"Running reflection (reason: {reason})...")
        result = reflect_on_batch()
        pf = result.get("pf", 0.0)
        pf_delta = result.get("pf_delta", 0.0)
        n_trades = result.get("n_trades", 0)
        _log(f"Reflection complete: PF={pf:.4f}, delta={pf_delta:+.4f}, trades={n_trades}")
    except Exception as e:
        _log(f"ERROR: Reflection failed: {e!r}")
        import traceback
        traceback.print_exc()


def run_tuner(reason: str = "nightly") -> None:
    """Run confidence tuner to propose parameter changes."""
    try:
        from engine_alpha.core.confidence_tuner import run_once
        
        _log(f"Running tuner (reason: {reason})...")
        entries = run_once()
        if entries:
            _log(f"Tuner complete: {len(entries)} regime entries generated")
            for entry in entries:
                regime = entry.get("regime", "unknown")
                delta = entry.get("delta", 0.0)
                new_gate = entry.get("new_gate", 0.0)
                _log(f"  {regime}: delta={delta:+.4f}, new_gate={new_gate:.4f}")
        else:
            _log("Tuner complete: no entries generated")
    except Exception as e:
        _log(f"ERROR: Tuner failed: {e!r}")
        import traceback
        traceback.print_exc()


def run_dream(reason: str = "nightly") -> None:
    """Run dream mode for long-horizon pattern synthesis."""
    try:
        from engine_alpha.reflect.dream_mode import run_dream
        
        _log(f"Running dream (reason: {reason})...")
        result = run_dream(window_steps=200)
        snapshot = result.get("snapshot", {})
        summary = result.get("summary", {})
        
        proposals = summary.get("proposals_scored", [])
        if proposals:
            _log(f"Dream complete: {len(proposals)} proposals generated")
            # Log top proposal if available
            top = proposals[0] if proposals else {}
            uplift = top.get("uplift", 0.0)
            recommend = top.get("recommend", "unknown")
            _log(f"  Top proposal: uplift={uplift:.4f}, recommend={recommend}")
        else:
            _log("Dream complete: no proposals generated")
    except Exception as e:
        _log(f"ERROR: Dream failed: {e!r}")
        import traceback
        traceback.print_exc()


def main(mode: str = MODE_REFLECTION_ONLY) -> int:
    """
    Main entry point for hindsight cycle.
    
    Args:
        mode: "reflection" (reflection only) or "full" (reflection + tuner + dream)
    
    Returns:
        Exit code (0 = success, 1 = error)
    """
    ts = datetime.now(timezone.utc).isoformat()
    
    # Load capital protection
    cp = _load_capital_protection()
    global_data = cp.get("global", {})
    capital_mode = global_data.get("mode", "unknown")
    pf_30d = global_data.get("pf_30d")
    
    _log(f"mode={mode} capital_mode={capital_mode} pf_30d={pf_30d}")
    
    # Always run reflection (safe, read-only)
    run_reflection(reason="scheduled")
    
    # Guard rails for tuner/dream
    if mode == MODE_FULL:
        # Check capital mode
        if capital_mode != "normal":
            _log(f"Skipping tuner/dream (capital_mode={capital_mode} != normal)")
            return 0
        
        # Check PF_30D
        if pf_30d is None:
            _log("Skipping tuner/dream (PF_30D missing)")
            return 0
        
        try:
            pf_30d_val = float(pf_30d)
        except (ValueError, TypeError):
            _log(f"Skipping tuner/dream (PF_30D invalid: {pf_30d})")
            return 0
        
        if pf_30d_val < 1.00:
            _log(f"Skipping tuner/dream (PF_30D={pf_30d_val:.4f} < 1.00)")
            return 0
        
        # Conditions met - run tuner and dream
        _log("Conditions met: running tuner and dream...")
        run_tuner(reason="nightly")
        run_dream(reason="nightly")
    
    _log("Hindsight cycle complete")
    return 0


if __name__ == "__main__":
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else MODE_REFLECTION_ONLY
    if mode_arg not in (MODE_REFLECTION_ONLY, MODE_FULL):
        print(f"ERROR: Invalid mode '{mode_arg}'. Use '{MODE_REFLECTION_ONLY}' or '{MODE_FULL}'")
        sys.exit(1)
    sys.exit(main(mode_arg))

