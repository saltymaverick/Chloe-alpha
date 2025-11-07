"""
GPT Operator - Phase 4
Natural language command interpreter.
"""

import json
from pathlib import Path
from typing import Dict, Any

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.gpt_reflection import reflect_on_batch


def interpret_command(text: str) -> Dict[str, Any]:
    """
    Parse short NL strings and map to internal calls.
    
    Args:
        text: Natural language command string
    
    Returns:
        Dictionary with "action" and "output" keys
    """
    text_lower = text.lower().strip()
    
    # Parse commands
    if "show pf" in text_lower or "profit factor" in text_lower:
        # Read pf_local.json
        pf_local_path = REPORTS / "pf_local.json"
        if pf_local_path.exists():
            with open(pf_local_path, "r") as f:
                pf_data = json.load(f)
            output = f"PF_local: {pf_data.get('pf', 'N/A'):.4f} (trades: {pf_data.get('count', 0)})"
        else:
            output = "PF_local.json not found"
        return {"action": "show_pf", "output": output}
    
    elif "safe mode" in text_lower or "safety" in text_lower:
        # Read incidents.jsonl
        incidents_path = REPORTS / "incidents.jsonl"
        safe_mode_active = False
        if incidents_path.exists():
            with open(incidents_path, "r") as f:
                lines = f.readlines()
                # Check last incident
                for line in reversed(lines):
                    line = line.strip()
                    if line:
                        try:
                            incident = json.loads(line)
                            if incident.get("safe_mode", False):
                                safe_mode_active = True
                                output = f"Safe mode: ACTIVE (reason: {incident.get('reason', 'unknown')})"
                                break
                        except json.JSONDecodeError:
                            continue
        
        if not safe_mode_active:
            output = "Safe mode: INACTIVE"
        return {"action": "safe_mode_status", "output": output}
    
    elif "reflect" in text_lower or "reflection" in text_lower:
        # Run reflection
        reflection = reflect_on_batch()
        output = f"Reflection complete. PF: {reflection.get('pf', 'N/A'):.4f}, Delta: {reflection.get('pf_delta', 0):.4f}"
        return {"action": "reflect", "output": output, "reflection": reflection}
    
    elif "why" in text_lower and "exit" in text_lower:
        # Read last exit from trades.jsonl
        trades_path = REPORTS / "trades.jsonl"
        output = "No exit events found"
        if trades_path.exists():
            with open(trades_path, "r") as f:
                lines = f.readlines()
                # Find last CLOSE event
                for line in reversed(lines):
                    line = line.strip()
                    if line:
                        try:
                            trade = json.loads(line)
                            if trade.get("event") == "CLOSE":
                                reason = trade.get("reason", "unknown")
                                direction = trade.get("direction", "unknown")
                                pnl = trade.get("pnl_pct", 0.0)
                                output = f"Last exit: {direction} position closed. Reason: {reason}. P&L: {pnl:.4f}"
                                break
                        except json.JSONDecodeError:
                            continue
        return {"action": "why_exit", "output": output}
    
    else:
        return {"action": "unknown", "output": f"Unknown command: {text}"}
