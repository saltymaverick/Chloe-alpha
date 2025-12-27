"""
Run Correlation Scan - Phase 5
CLI tool to compute and display correlation matrix.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.research.correlation_engine import compute_correlation_matrix


def main() -> int:
    """Run correlation scan and print summary."""
    print("CORRELATION SCAN")
    print("=" * 70)
    print()
    
    report = compute_correlation_matrix()
    matrix = report.get("matrix", {})
    symbols = report.get("symbols", [])
    
    if not matrix or not symbols:
        print("⚠️  No correlation data found")
        print("   Run some trades first to generate correlation analysis")
        return 0
    
    # Collect all pairs with correlations
    pairs: List[Tuple[str, str, float]] = []
    seen_pairs = set()
    
    for sym1 in symbols:
        for sym2 in symbols:
            if sym1 >= sym2:  # Only upper triangle
                continue
            corr = matrix.get(sym1, {}).get(sym2, 0.0)
            pairs.append((sym1, sym2, corr))
            seen_pairs.add((sym1, sym2))
    
    # Sort by correlation (descending)
    pairs.sort(key=lambda x: x[2], reverse=True)
    
    print(f"TOP 5 MOST CORRELATED PAIRS:")
    print("-" * 70)
    for sym1, sym2, corr in pairs[:5]:
        print(f"  {sym1} ↔ {sym2}: {corr:+.3f}")
    
    print()
    print(f"TOP 5 LEAST CORRELATED PAIRS:")
    print("-" * 70)
    for sym1, sym2, corr in pairs[-5:]:
        print(f"  {sym1} ↔ {sym2}: {corr:+.3f}")
    
    print()
    print(f"✅ Correlation matrix written to: reports/research/correlation_matrix.json")
    print(f"   Common timestamps: {report.get('common_timestamps_count', 0)}")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

