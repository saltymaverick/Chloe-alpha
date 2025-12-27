#!/usr/bin/env python3
"""
Verify Glassnode integration - check that on-chain metrics are in hybrid datasets.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))


def verify_glassnode_in_dataset(symbol: str = "ETHUSDT"):
    """Check if Glassnode columns are present in hybrid dataset."""
    hybrid_path = ROOT_DIR / "reports" / "research" / symbol / "hybrid_research_dataset.parquet"
    
    if not hybrid_path.exists():
        print(f"❌ Hybrid dataset not found: {hybrid_path}")
        print(f"   Run: python3 -m engine_alpha.reflect.nightly_research")
        return False
    
    try:
        df = pd.read_parquet(hybrid_path)
        gn_cols = [c for c in df.columns if c.startswith("gn_")]
        
        if not gn_cols:
            print(f"⚠️  No Glassnode columns found in {symbol} hybrid dataset")
            print(f"   Available columns: {list(df.columns)[:10]}...")
            print(f"   Make sure:")
            print(f"   1. Glassnode API key is set in config/glassnode_config.json")
            print(f"   2. Data fetched: python3 -m tools.fetch_glassnode_data --symbol {symbol}")
            print(f"   3. Research run: python3 -m engine_alpha.reflect.nightly_research")
            return False
        
        print(f"✅ Found {len(gn_cols)} Glassnode columns: {gn_cols}")
        
        # Check data quality
        for col in gn_cols:
            non_null = df[col].notna().sum()
            total = len(df)
            pct = (non_null / total * 100) if total > 0 else 0
            print(f"   {col}: {non_null}/{total} non-null ({pct:.1f}%)")
        
        # Show sample
        print(f"\n📊 Sample data (last 5 rows):")
        sample_cols = ["ts"] + gn_cols
        available_cols = [c for c in sample_cols if c in df.columns]
        print(df[available_cols].tail(5).to_string())
        
        return True
        
    except Exception as e:
        print(f"❌ Error reading dataset: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Verify Glassnode integration")
    parser.add_argument("--symbol", type=str, default="ETHUSDT", help="Symbol to check")
    args = parser.parse_args()
    
    print(f"🔍 Verifying Glassnode integration for {args.symbol}...\n")
    success = verify_glassnode_in_dataset(args.symbol)
    
    if success:
        print(f"\n✅ Glassnode integration verified!")
    else:
        print(f"\n⚠️  Glassnode integration not complete - see instructions above")
        sys.exit(1)


if __name__ == "__main__":
    main()


