"""
Withdrawal Adapter Stub - Advisory withdrawal planning.

No real withdrawals or exchange operations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
CAPITAL_DIR = ROOT / "reports" / "capital"


def validate_withdrawal(amount: float, address: str) -> Dict[str, Any]:
    """Validate withdrawal request (advisory only)."""
    # Always return shadow mode for now
    return {
        "shadow": True,
        "allowed": False,
        "reason": "Stub mode - no real withdrawals allowed",
        "amount": amount,
        "address": address,
        "notes": [
            "This is a stub validation - no real checks performed.",
            "Real implementation would check:",
            "- Account balance",
            "- Withdrawal limits",
            "- Address whitelist",
            "- Daily withdrawal limits",
            "- Risk thresholds",
        ],
    }


def generate_withdrawal_plan(amount: float, address: str) -> Dict[str, Any]:
    """Generate advisory withdrawal plan."""
    validation = validate_withdrawal(amount, address)
    
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "shadow": True,
        "reason": "advisory only",
        "allowed": False,
        "amount": amount,
        "address": address,
        "validation": validation,
        "api_request_sample": {
            "endpoint": "/v5/asset/withdraw",
            "method": "POST",
            "body": {
                "coin": "USDT",
                "chain": "TRC20",
                "address": address,
                "amount": str(amount),
            },
            "note": "This is a sample request structure - NOT executed",
        },
        "notes": [
            "This is an advisory withdrawal plan only.",
            "No real withdrawal has been initiated.",
            "Review all safety checks before real implementation.",
            "Requires human approval and explicit enablement.",
        ],
    }


def main() -> None:
    """Generate withdrawal plan (stub)."""
    # Example withdrawal request
    amount = 100.0
    address = "TExampleAddress123456789"
    
    plan = generate_withdrawal_plan(amount, address)
    
    # Write to reports
    CAPITAL_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CAPITAL_DIR / "withdrawal_plan.json"
    output_path.write_text(json.dumps(plan, indent=2, sort_keys=True))
    
    print(f"✅ Withdrawal plan written to: {output_path}")
    print(f"   Allowed: {plan['allowed']}")
    print(f"   Reason: {plan['reason']}")


if __name__ == "__main__":
    main()


