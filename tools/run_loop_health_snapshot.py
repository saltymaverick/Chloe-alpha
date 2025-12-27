#!/usr/bin/env python3
"""
Loop Health Snapshot Writer

Writes reports/loop_health.json with canonical "one-glance" status.
Called from both loop ticks and policy_refresh runs.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS
from engine_alpha.core.opportunity_density import is_loop_alive, load_state, HEARTBEAT_PATH


def _parse_ts(ts_str: str) -> datetime | None:
    """Parse ISO timestamp string."""
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def _get_heartbeat_age_seconds() -> float | None:
    """Get heartbeat file age in seconds, or None if not found."""
    if not HEARTBEAT_PATH.exists():
        return None
    
    try:
        heartbeat_data = json.loads(HEARTBEAT_PATH.read_text())
        heartbeat_ts_str = heartbeat_data.get("ts")
        if not heartbeat_ts_str:
            return None
        
        heartbeat_ts = _parse_ts(heartbeat_ts_str)
        if not heartbeat_ts:
            return None
        
        now = datetime.now(timezone.utc)
        age_seconds = (now - heartbeat_ts).total_seconds()
        return max(0, age_seconds)
    except Exception:
        return None


def _get_last_trade_ts() -> str | None:
    """Get timestamp of last trade event from trades.jsonl."""
    trades_path = REPORTS / "trades.jsonl"
    if not trades_path.exists():
        return None
    
    try:
        with trades_path.open("r") as f:
            lines = f.readlines()
            # Read backwards to find last trade
            for line in reversed(lines):
                try:
                    evt = json.loads(line.strip())
                    ts = evt.get("ts") or evt.get("timestamp") or evt.get("time")
                    if ts:
                        return ts
                except Exception:
                    continue
    except Exception:
        pass
    
    return None


def compute_loop_health() -> dict:
    """Compute canonical loop health snapshot."""
    now = datetime.now(timezone.utc)
    now_ts = now.isoformat()
    
    # Loop alive status
    loop_alive = is_loop_alive(max_age_seconds=90)
    heartbeat_age = _get_heartbeat_age_seconds()
    
    # Last tick TS (from heartbeat if available)
    last_tick_ts = None
    if HEARTBEAT_PATH.exists():
        try:
            heartbeat_data = json.loads(HEARTBEAT_PATH.read_text())
            last_tick_ts = heartbeat_data.get("ts")
        except Exception:
            pass
    
    # Capital mode and PF
    capital_mode = "unknown"
    pf_local = {"24h": None, "7d": None, "30d": None}
    
    capital_protection_path = REPORTS / "risk" / "capital_protection.json"
    if capital_protection_path.exists():
        try:
            cp_data = json.loads(capital_protection_path.read_text())
            global_data = cp_data.get("global", {})
            capital_mode = global_data.get("mode", "unknown")
        except Exception:
            pass
    
    pf_local_path = REPORTS / "pf_local.json"
    if pf_local_path.exists():
        try:
            pf_data = json.loads(pf_local_path.read_text())
            pf_local["24h"] = pf_data.get("pf_24h")
            pf_local["7d"] = pf_data.get("pf_7d")
            pf_local["30d"] = pf_data.get("pf_30d")
        except Exception:
            pass
    
    # Regime
    regime = "unknown"
    regime_path = REPORTS / "regime_snapshot.json"
    if regime_path.exists():
        try:
            regime_data = json.loads(regime_path.read_text())
            regime = regime_data.get("regime", "unknown")
        except Exception:
            pass
    
    # Opportunity density
    density_current = None
    density_floor = None
    eligible_now = None
    
    opportunity_snapshot_path = REPORTS / "opportunity_snapshot.json"
    if opportunity_snapshot_path.exists():
        try:
            opp_data = json.loads(opportunity_snapshot_path.read_text())
            density_current = opp_data.get("density_current")
            density_floor = opp_data.get("density_floor")
            eligible_now = opp_data.get("eligible_now")
        except Exception:
            pass
    
    # Issues from reflection packet
    issues = []
    reflection_packet_path = REPORTS / "reflection_packet.json"
    if reflection_packet_path.exists():
        try:
            pkt_data = json.loads(reflection_packet_path.read_text())
            issues = (pkt_data.get("meta") or {}).get("issues", [])
        except Exception:
            pass
    
    # Last trade TS
    last_trade_ts = _get_last_trade_ts()
    
    # Symbol universe counts (optional)
    symbol_universe_counts = {}
    recovery_ramp_path = REPORTS / "risk" / "recovery_ramp_v2.json"
    if recovery_ramp_path.exists():
        try:
            ramp_data = json.loads(recovery_ramp_path.read_text())
            symbols = ramp_data.get("symbols", {})
            symbol_universe_counts = {
                "total": len(symbols),
                "eligible": sum(1 for s in symbols.values() if s.get("eligible") is True),
            }
        except Exception:
            pass
    
    ok = True
    fatal_markers = {"LOOP_CRASH", "FEED_STALE", "CONFIDENCE_MISSING"}
    if any(issue in fatal_markers for issue in issues):
        ok = False

    return {
        "ts": now_ts,
        "loop_alive": loop_alive,
        "heartbeat_age_seconds": heartbeat_age,
        "last_tick_ts": last_tick_ts,
        "capital_mode": capital_mode,
        "pf_local": pf_local,
        "regime": regime,
        "density_current": density_current,
        "density_floor": density_floor,
        "eligible_now": eligible_now,
        "issues": issues,
        "ok": ok,
        "last_trade_ts": last_trade_ts,
        "symbol_universe_counts": symbol_universe_counts,
    }


def main() -> int:
    """Write loop health snapshot."""
    health = compute_loop_health()
    
    legacy_path = REPORTS / "loop_health.json"
    loop_path = REPORTS / "loop" / "loop_health.json"

    for output_path in (legacy_path, loop_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(health, f, indent=2, sort_keys=True)
        print(f"Loop health snapshot written: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

