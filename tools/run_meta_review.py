"""
Run Meta-Review - Phase 3
CLI tool to run meta-reasoner analysis and print summary.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.research.meta_reasoner import analyze


def main() -> int:
    """Run meta-reasoner analysis and print summary."""
    print("🔍 Running Meta-Reasoner analysis...")
    print()
    
    report = analyze(n=5)
    
    issue_count = len(report.get("issues", []))
    recommendations = report.get("recommendations", [])
    
    print(f"📊 Analyzed {report.get('memory_entries_analyzed', 0)} memory entries")
    print(f"⚠️  Found {issue_count} issues")
    print()
    
    if issue_count > 0:
        print("ISSUES:")
        print("-" * 70)
        for issue in report.get("issues", []):
            print(f"  [{issue.get('type', 'unknown')}] {issue.get('symbol', 'unknown')}")
            print(f"    {issue.get('details', 'No details')}")
            print()
    
    print("RECOMMENDATIONS:")
    print("-" * 70)
    for rec in recommendations:
        print(f"  • {rec}")
    print()
    
    print(f"✅ Meta-reasoner report written to: {report.get('_report_path', 'reports/research/meta_reasoner_report.json')}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

