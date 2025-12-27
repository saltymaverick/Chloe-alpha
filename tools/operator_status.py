#!/usr/bin/env python3
"""
Operator Status Tool - Single command health + intelligence brief.

Shows service status, loop health, primitives, GPT state, and incidents.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.core.paths import REPORTS


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    """Read JSON file, return None on error."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def tail_jsonl(path: Path, n: int = 1) -> List[Dict[str, Any]]:
    """Read last N lines from JSONL file."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
            if not lines:
                return []
            result = []
            for line in lines[-n:]:
                line = line.strip()
                if line:
                    try:
                        result.append(json.loads(line))
                    except Exception:
                        pass
            return result
    except Exception:
        return []


def safe_get(d: Dict[str, Any], path_str: str, default: Any = None) -> Any:
    """Get nested value by dot-separated path."""
    if not isinstance(d, dict):
        return default
    parts = path_str.split(".")
    current = d
    for part in parts:
        if not isinstance(current, dict):
            return default
        current = current.get(part)
        if current is None:
            return default
    return current


def run_cmd(cmd: List[str]) -> Optional[str]:
    """Run command, return stdout or None on error."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_service_info() -> Dict[str, Any]:
    """Get systemd service status."""
    info = {
        "status": "UNKNOWN",
        "pid": None,
        "uptime": None,
    }
    
    # Check if active
    active = run_cmd(["systemctl", "is-active", "chloe_loop"])
    if active:
        info["status"] = active.upper()
    
    # Get PID and timestamp
    show_output = run_cmd([
        "systemctl", "show", "chloe_loop",
        "-p", "MainPID",
        "-p", "ActiveEnterTimestamp",
        "--no-pager",
    ])
    
    if show_output:
        for line in show_output.split("\n"):
            if line.startswith("MainPID="):
                pid = line.split("=", 1)[1]
                if pid and pid != "0":
                    info["pid"] = pid
            elif line.startswith("ActiveEnterTimestamp="):
                ts_str = line.split("=", 1)[1]
                if ts_str:
                    info["uptime"] = ts_str
    
    return info


def format_timestamp(ts: Any) -> str:
    """Format timestamp for display."""
    if ts is None:
        return "none"
    if isinstance(ts, str):
        return ts
    return str(ts)


def get_file_age_seconds(path: Path) -> Optional[float]:
    """Get age of file in seconds since last modification."""
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        now = datetime.now(timezone.utc).timestamp()
        return now - mtime
    except Exception:
        return None


def format_age(age_seconds: Optional[float]) -> str:
    """Format age in human-readable format."""
    if age_seconds is None:
        return "unknown"
    if age_seconds < 60:
        return f"{int(age_seconds)}s"
    elif age_seconds < 3600:
        return f"{int(age_seconds / 60)}m"
    else:
        return f"{int(age_seconds / 3600)}h"


def truncate(s: Any, max_len: int = 80) -> str:
    """Truncate string to max length."""
    if s is None:
        return "none"
    s_str = str(s)
    if len(s_str) <= max_len:
        return s_str
    return s_str[:max_len - 3] + "..."


def print_status() -> None:
    """Print human-readable status."""
    print("=" * 60)
    print("CHLOE OPERATOR STATUS")
    print("=" * 60)
    
    # Service info
    svc = get_service_info()
    pid_str = f"PID: {svc['pid']}" if svc.get("pid") else ""
    uptime_str = f"Uptime: {svc['uptime']}" if svc.get("uptime") else ""
    print(f"Service: {svc['status']}   {pid_str}   {uptime_str}")
    
    # Loop health
    health_path_primary = REPORTS / "loop" / "loop_health.json"
    health_path_fallback = REPORTS / "loop_health.json"
    health = read_json(health_path_primary) or read_json(health_path_fallback)
    health_age = get_file_age_seconds(health_path_primary if health else health_path_fallback)
    issues = []
    loop_ok = None
    loop_ts = None
    loop_ms = None
    loop_action = "?"
    loop_reason = "none"
    if health:
        issues = health.get("issues") or []
        loop_ok = health.get("ok")
        if loop_ok is None:
            loop_ok = not bool(issues)
        loop_ts = format_timestamp(health.get("last_tick_ts") or health.get("ts"))
        loop_ms = health.get("last_tick_ms")
        loop_action = health.get("last_action", "?")
        loop_reason = truncate(health.get("last_reason"), 60)
    age_str = format_age(health_age)
    if health:
        print(f"Loop: ok={loop_ok}   last_tick_ts={loop_ts}   last_tick_ms={loop_ms}   action={loop_action}   reason={loop_reason}   age={age_str}")
    else:
        print(f"Loop: health file not found (age={age_str})")
    
    # Issues
    packet = read_json(REPORTS / "reflection_packet.json")
    refl_issues = safe_get(packet, "meta.issues", []) if packet else []
    all_issues = refl_issues or issues
    if all_issues:
        print(f"Issues: {', '.join(all_issues)}")
    else:
        print("Issues: none")
        
    # Market info
    packet_path = REPORTS / "reflection_packet.json"
    packet_age = get_file_age_seconds(packet_path)
    symbol = packet.get("symbol", "?") if packet else "?"
    timeframe = packet.get("timeframe", "?") if packet else "?"
    price = safe_get(packet, "market.price") if packet else None
    ohlcv_source = safe_get(packet, "market.ohlcv_source", "?") if packet else "?"
    ohlcv_age_s = safe_get(packet, "market.ohlcv_age_s") if packet else None
    ohlcv_stale = safe_get(packet, "market.ohlcv_is_stale", False) if packet else False
    print(f"Market: symbol={symbol} tf={timeframe} price={price} ohlcv_source={ohlcv_source} age_s={ohlcv_age_s} stale={ohlcv_stale} packet_age={format_age(packet_age)}")
    
    # Primitives
    print("\nPrimitives:")
    # Self-trust (from reflection packet if present)
    if packet and packet.get("primitives"):
        st = packet["primitives"].get("self_trust", {})
        st_score = st.get("self_trust_score")
        n_samples = st.get("n_samples", 0)
        samples_proc = st.get("samples_processed", 0)
        print(f"  SelfTrust: score={st_score} n={n_samples} samples_processed={samples_proc}")
    else:
        print("  SelfTrust: (no reflection packet)")
    
    # Opportunity from opportunity_snapshot.json
    opp_path = REPORTS / "opportunity_snapshot.json"
    opp_data = read_json(opp_path) or {}
    eff_regime = opp_data.get("effective_regime", opp_data.get("symbol_regime", "unknown"))
    opp_eligible = opp_data.get("eligible_now")
    opp_reason = opp_data.get("eligible_now_reason")
    dens_cur = opp_data.get("density_current")
    dens_floor = opp_data.get("density_floor_effective") or opp_data.get("density_floor")
    events_24h = opp_data.get("events_24h")
    eligible_24h = opp_data.get("eligible_24h")
    print(
        f"  Opportunity: regime={eff_regime} eligible_now={opp_eligible} "
        f"reason={opp_reason} density_current={dens_cur} density_floor_effective={dens_floor} "
        f"events_24h={events_24h} eligible_24h={eligible_24h}"
    )
    
    # Invalidation (reflection packet if present)
    if packet and packet.get("primitives"):
        inv = packet["primitives"].get("invalidation", {})
        print(f"  Invalidation: health={inv.get('thesis_health_score')} soft={inv.get('soft_invalidation_score')} flags={inv.get('invalidation_flags', [])}")
    else:
        print("  Invalidation: (no reflection packet)")
    
    # Compression (reflection packet if present)
    if packet and packet.get("primitives"):
        comp = packet["primitives"].get("compression", {})
        print(f"  Compression: score={comp.get('compression_score')} is_compressed={comp.get('is_compressed', False)} time_in={comp.get('time_in_compression_s')}")
    else:
        print("  Compression: (no reflection packet)")
    
    # Decay (reflection packet if present)
    if packet and packet.get("primitives"):
        decay = packet["primitives"].get("decay", {})
        print(f"  Decay: conf_decayed={decay.get('confidence_decayed')} refreshed={decay.get('confidence_refreshed', False)} pci_decayed={decay.get('pci_decayed')} refreshed={decay.get('pci_refreshed', False)}")
    else:
        print("  Decay: (no reflection packet)")
    
    # Velocity (reflection packet if present)
    if packet and packet.get("primitives"):
        vel = packet["primitives"].get("velocity", {})
        print(f"  Velocity: conf_per_s={vel.get('confidence_per_s')} pci_per_s={vel.get('pci_per_s')}")
    else:
        print("  Velocity: (no reflection packet)")
    
    # PCI Snapshot (if any)
    if packet and packet.get("pre_candle"):
        print("  PCI Snapshot: present")
    
    # GPT
    print("\nGPT:")
    engine_cfg = read_json(Path(__file__).parent.parent / "config" / "engine_config.json")
    if engine_cfg:
        enabled = engine_cfg.get("enable_gpt_reflection", False)
        close_gated = engine_cfg.get("gpt_reflection_on_close_only", True)
        print(f"  Enabled: {enabled}   Close-gated: {close_gated}")
    
    gpt_state = read_json(REPORTS / "gpt_state.json")
    if gpt_state:
        last_run = format_timestamp(gpt_state.get("last_run_ts"))
        last_offset = gpt_state.get("last_gpt_trade_log_offset", 0)
        print(f"  Last run: {last_run}   last_offset={last_offset}")
    
    gpt_reflection = read_json(REPORTS / "gpt_reflection_latest.json")
    if gpt_reflection:
        ts = format_timestamp(gpt_reflection.get("ts"))
        model = gpt_reflection.get("model", "?")
        changes = gpt_reflection.get("proposed_changes", [])
        print(f"  Latest reflection: EXISTS (ts={ts}, model={model}, proposed_changes={len(changes)})")
    else:
        print("  Latest reflection: none")
    
    gpt_diff = read_json(REPORTS / "gpt_tuner_diff.json")
    if gpt_diff:
        risk = gpt_diff.get("risk")
        changes = gpt_diff.get("changes", [])
        print(f"  Latest diff: EXISTS (risk={risk}, changes={len(changes)})")
    else:
        print("  Latest diff: none")
    
    # Tuner dry-run
    print("\nTuner (dry-run):")
    tuner = read_json(REPORTS / "tuner_dryrun.json")
    if tuner:
        status = tuner.get("status", "?")
        blocked_by = tuner.get("blocked_by", [])
        needed = tuner.get("needed", {})
        print(f"  status={status} blocked_by={blocked_by} needed={needed}")
    else:
        print("  status: file not found")
    
    # Last incident (scan last 50 lines for most recent valid one)
    print("\nLast incident:")
    incidents = tail_jsonl(REPORTS / "incidents.jsonl", n=50)
    if incidents:
        most_recent = None
        most_recent_ts = None
        for inc in reversed(incidents):
            ts_str = inc.get("ts")
            if ts_str:
                try:
                    ts_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if most_recent_ts is None or ts_dt > most_recent_ts:
                        most_recent = inc
                        most_recent_ts = ts_dt
                except Exception:
                    pass
        if most_recent:
            ts = format_timestamp(most_recent.get("ts"))
            where = most_recent.get("where", "?")
            error_type = most_recent.get("error_type", "?")
            error = truncate(most_recent.get("error", ""), 60)
            if most_recent_ts:
                age_sec = (datetime.now(timezone.utc) - most_recent_ts.replace(tzinfo=timezone.utc)).total_seconds()
                age_str = format_age(age_sec)
                print(f"  ts={ts} ({age_str} ago) where={where} error_type={error_type} error={error}")
            else:
                print(f"  ts={ts} where={where} error_type={error_type} error={error}")
        else:
            print("  none (no valid incidents found)")
    else:
        print("  none")
    
    print("=" * 60)


def print_json_status() -> Dict[str, Any]:
    """Return machine-readable status dict."""
    result = {}
    
    # Service
    svc = get_service_info()
    result["service"] = svc
    
    # Loop health
    health = read_json(REPORTS / "loop_health.json")
    if health:
        result["loop_health"] = health.get("last", {})
    
    # Packet
    packet = read_json(REPORTS / "reflection_packet.json")
    if packet:
        result["packet"] = {
            "ts": packet.get("ts"),
            "symbol": packet.get("symbol"),
            "timeframe": packet.get("timeframe"),
            "issues": safe_get(packet, "meta.issues", []),
            "market": {
                "price": safe_get(packet, "market.price"),
                "ohlcv_source": safe_get(packet, "market.ohlcv_source"),
                "ohlcv_age_s": safe_get(packet, "market.ohlcv_age_s"),
                "ohlcv_is_stale": safe_get(packet, "market.ohlcv_is_stale"),
            },
            "primitives": packet.get("primitives", {}),
        }
    
    # GPT state
    gpt_state = read_json(REPORTS / "gpt_state.json")
    if gpt_state:
        result["gpt_state"] = gpt_state
    
    gpt_reflection = read_json(REPORTS / "gpt_reflection_latest.json")
    if gpt_reflection:
        result["gpt_reflection"] = {
            "ts": gpt_reflection.get("ts"),
            "model": gpt_reflection.get("model"),
            "proposed_changes_count": len(gpt_reflection.get("proposed_changes", [])),
        }
    
    gpt_diff = read_json(REPORTS / "gpt_tuner_diff.json")
    if gpt_diff:
        result["gpt_diff"] = {
            "ts": gpt_diff.get("ts"),
            "risk": gpt_diff.get("risk"),
            "changes_count": len(gpt_diff.get("changes", [])),
        }
    
    # Tuner
    tuner = read_json(REPORTS / "tuner_dryrun.json")
    if tuner:
        result["tuner"] = tuner
    
    # Last incident
    incidents = tail_jsonl(REPORTS / "incidents.jsonl", n=1)
    if incidents:
        result["last_incident"] = incidents[-1]
    
    return result


def main() -> int:
    """Main entry point."""
    json_output = "--json" in sys.argv
    
    if json_output:
        status = print_json_status()
        print(json.dumps(status, indent=2, default=str))
    else:
        print_status()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
