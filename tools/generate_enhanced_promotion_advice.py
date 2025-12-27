#!/usr/bin/env python3
"""
Generate Enhanced Promotion Advice
Uses regime-specific, signal-attributed, and dream-weighted analysis.
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pathlib import Path
import json
from engine_alpha.reflect.enhanced_promotion_advice import (
    EnhancedPromotionAdvisor,
    save_enhanced_promotion_advice
)

def load_trades_jsonl() -> list:
    """Load trades from JSONL file."""
    trades_path = Path("reports/trades.jsonl")
    if not trades_path.exists():
        return []

    trades = []
    with open(trades_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return trades

def main():
    print("Enhanced Promotion Advice Generator")
    print("=" * 50)

    # Load trades data
    print("Loading trade data...")
    trades = load_trades_jsonl()
    print(f"Loaded {len(trades)} trades")
    
    # Generate enhanced advice
    print("Analyzing promotions with regime/signal/dream enhancements...")
    advisor = EnhancedPromotionAdvisor()
    advice = advisor.generate_comprehensive_promotion_advice(trades, lookback_days=7)
    
    # Save to standard location
    output_path = save_enhanced_promotion_advice(advice)
    print(f"Saved enhanced promotion advice to: {output_path}")
    
    # Print summary
    symbols = advice.get('symbols', {})
    promotions = sum(1 for s in symbols.values() if s.get('action') == 'promote')
    demotions = sum(1 for s in symbols.values() if s.get('action') == 'demote')
    holds = sum(1 for s in symbols.values() if s.get('action') == 'hold')
    
    print(f"\nAnalysis Summary:")
    print(f"  Symbols analyzed: {len(symbols)}")
    print(f"  Promotions: {promotions}")
    print(f"  Demotions: {demotions}")
    print(f"  Holds: {holds}")
    
    # Also save to the standard promotion_advice.json location for compatibility
    standard_path = Path("reports/gpt/promotion_advice.json")
    standard_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert enhanced format to standard format for compatibility
    standard_advice = {
        'generated_at': advice['generated_at'],
        'window': advice['window'],
        'symbols': {}
    }
    
    for symbol, data in symbols.items():
        standard_advice['symbols'][symbol] = {
            'action': data['action'],
            'confidence': data['confidence'],
            'reasons': data['factors'][:3],  # Limit reasons for compatibility
            'core': data['analyses']['base'],
            'exploration': data['analyses']['base'],  # Simplified for compatibility
        }
    
    with open(standard_path, 'w') as f:
        import json
        json.dump(standard_advice, f, indent=2, default=str)
    
    print(f"Saved standard promotion advice to: {standard_path}")

if __name__ == "__main__":
    main()
