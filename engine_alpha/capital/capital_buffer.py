"""
Capital Buffer Calculator - Advisory buffer suggestions.

Read-only, advisory-only. No real buffer enforcement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
CAPITAL_DIR = ROOT / "reports" / "capital"


def compute_liquidity_buffer(account_equity: float) -> float:
    """Compute advisory liquidity buffer."""
    # 10% of equity for liquidity
    return account_equity * 0.10


def compute_volatility_buffer(symbol_vol: float) -> float:
    """Compute advisory volatility buffer per symbol."""
    # Scale buffer with volatility (e.g., 2x daily vol)
    return symbol_vol * 2.0


def compute_emergency_buffer(account_equity: float) -> float:
    """Compute advisory emergency buffer."""
    # 15% of equity for emergencies
    return account_equity * 0.15


def summarize_buffers(equity: float, per_symbol_vol: Dict[str, float]) -> Dict[str, Any]:
    """Summarize all buffer calculations."""
    liquidity = compute_liquidity_buffer(equity)
    emergency = compute_emergency_buffer(equity)
    
    symbol_volatility_buffers = {}
    for symbol, vol in per_symbol_vol.items():
        symbol_volatility_buffers[symbol] = compute_volatility_buffer(vol)
    
    total_volatility_buffer = sum(symbol_volatility_buffers.values())
    total_buffers = liquidity + emergency + total_volatility_buffer
    
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "equity": equity,
        "liquidity_buffer": round(liquidity, 2),
        "emergency_buffer": round(emergency, 2),
        "symbol_volatility_buffers": {
            k: round(v, 2) for k, v in symbol_volatility_buffers.items()
        },
        "total_volatility_buffer": round(total_volatility_buffer, 2),
        "total_buffers": round(total_buffers, 2),
        "available_for_allocation": round(equity - total_buffers, 2),
        "notes": [
            "These are advisory buffer calculations only.",
            "No real buffers have been enforced.",
            "Review before implementation.",
        ],
    }


def main() -> None:
    """Generate buffer advice."""
    # Default equity (would come from exchange in real implementation)
    equity = 10000.0
    
    # Default volatility estimates (would come from ARE or market data)
    per_symbol_vol = {
        "ETHUSDT": 0.02,
        "BTCUSDT": 0.015,
        "ATOMUSDT": 0.03,
    }
    
    buffers = summarize_buffers(equity, per_symbol_vol)
    
    # Write to reports
    CAPITAL_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CAPITAL_DIR / "buffers.json"
    output_path.write_text(json.dumps(buffers, indent=2, sort_keys=True))
    
    print(f"✅ Buffer advice written to: {output_path}")
    print(f"   Total buffers: ${buffers['total_buffers']:.2f}")
    print(f"   Available: ${buffers['available_for_allocation']:.2f}")


if __name__ == "__main__":
    main()


