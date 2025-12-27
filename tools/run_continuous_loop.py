#!/usr/bin/env python3
"""
Continuous Trading Loop Runner

Runs the trading loop continuously for systemd service.
"""

from __future__ import annotations

import sys
import time
import signal
import random
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import json
from engine_alpha.loop.autonomous_trader import run_step_live_scheduled
from engine_alpha.loop.recovery_lane_v2 import run_recovery_lane_v2
from tools.run_loop_health_snapshot import compute_loop_health
from engine_alpha.core.paths import REPORTS


def main() -> int:
    """Run continuous loop with graceful shutdown."""
    running = True
    
    def signal_handler(sig, frame):
        nonlocal running
        print(f"\nReceived signal {sig}, shutting down gracefully...")
        running = False
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("Starting continuous trading loop...")
    print("Press Ctrl+C or send SIGTERM to stop.")
    
    tick_count = 0
    error_count = 0
    max_errors = 10
    
    while running:
        try:
            # Run one scheduled step (may include multiple symbols)
            run_step_live_scheduled()

            # Evaluate exits for ALL open positions (regardless of symbol/timeframe)
            try:
                from engine_alpha.loop.autonomous_trader import run_exit_evaluation_for_all_positions
                run_exit_evaluation_for_all_positions()
            except Exception:
                traceback.print_exc()

            # Always run recovery lane so exits (TP/SL/timeout) fire even in halt mode
            try:
                run_recovery_lane_v2()
            except Exception:
                traceback.print_exc()

            # Write heartbeat to indicate loop is alive
            try:
                from engine_alpha.core.opportunity_density import write_heartbeat
                write_heartbeat()
            except Exception as e:
                print(f"Failed to write heartbeat: {e}")

            tick_count += 1
            error_count = 0  # Reset error count on success
            
            # Write loop health snapshot after each tick (both legacy + new canonical path)
            try:
                health = compute_loop_health()
                legacy_path = REPORTS / "loop_health.json"
                loop_path = REPORTS / "loop" / "loop_health.json"
                for hp in (legacy_path, loop_path):
                    hp.parent.mkdir(parents=True, exist_ok=True)
                    with hp.open("w", encoding="utf-8") as f:
                        json.dump(health, f, indent=2, sort_keys=True)
            except Exception as e:
                # Don't fail loop on health snapshot errors
                print(f"Warning: Failed to write health snapshot: {e}", file=sys.stderr)
            
            # Sleep between ticks with jitter to avoid timer alignment
            # Base 60s + random jitter ±3s = 57-63s range
            base_sleep = 60
            jitter = random.uniform(-3, 3)
            sleep_time = max(1, base_sleep + jitter)  # Ensure at least 1 second
            time.sleep(sleep_time)
            
        except KeyboardInterrupt:
            print("\nReceived KeyboardInterrupt, shutting down...")
            running = False
        except Exception as e:
            error_count += 1
            print(f"Error in loop tick {tick_count}: {e}", file=sys.stderr)
            
            if error_count >= max_errors:
                print(f"Too many errors ({error_count}), exiting...", file=sys.stderr)
                return 1
            
            # Exponential backoff on errors
            time.sleep(min(60 * error_count, 300))  # Max 5 minutes
    
    print(f"Loop stopped after {tick_count} ticks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

