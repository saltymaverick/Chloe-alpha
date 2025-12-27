"""
Run Alpha/Beta Scan - Phase 5
CLI tool to compute and display alpha/beta decomposition.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.research.alpha_beta_decomposition import compute_alpha_beta, BENCHMARK_SYMBOL


def main() -> int:
    """Run alpha/beta scan and print summary."""
    print("ALPHA/BETA DECOMPOSITION")
    print("=" * 70)
    print()
    print(f"Benchmark: {BENCHMARK_SYMBOL}")
    print()
    
    report = compute_alpha_beta()
    symbols_data = report.get("symbols", {})
    
    if not symbols_data:
        print("⚠️  No symbol data found")
        print("   Run some trades first to generate alpha/beta analysis")
        return 0
    
    print("ALPHA/BETA BY SYMBOL:")
    print("-" * 70)
    print(f"{'Symbol':<12} {'Alpha':>10} {'Beta':>10} {'Sample':>8}")
    print("-" * 70)
    
    for symbol, data in sorted(symbols_data.items()):
        alpha = data.get("alpha")
        beta = data.get("beta")
        sample_size = data.get("sample_size", 0)
        
        alpha_str = f"{alpha:+.4f}" if alpha is not None else "N/A"
        beta_str = f"{beta:.2f}" if beta is not None else "N/A"
        
        print(f"{symbol:<12} {alpha_str:>10} {beta_str:>10} {sample_size:>8}")
    
    print()
    print("Interpretation:")
    print("  Alpha: Idiosyncratic return (positive = outperforms market)")
    print("  Beta: Market sensitivity (1.0 = moves with market, >1.0 = more volatile)")
    print()
    print(f"✅ Alpha/beta report written to: reports/research/alpha_beta.json")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

