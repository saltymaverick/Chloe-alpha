# Strategy Card System

## Overview

Chloe now has a strategy card system that allows her to operate with named, configurable strategies instead of just threshold tuning. Strategies are defined as JSON configs and can be selected, evaluated, and eventually enforced.

## Architecture

### Strategy Configs (`engine_alpha/config/strategies/*.json`)

Each strategy is a JSON file defining:
- **Scope**: Which symbols, regimes, timeframes, directions it applies to
- **Entry Logic**: Conditions for entering trades (confidence, filters, triggers)
- **Exit Logic**: TP/SL levels, max hold time
- **Risk**: Position sizing, limits, observation mode overrides
- **Activation**: PF thresholds, drawdown limits, manual approval requirements

### Loader (`engine_alpha/strategies/loader.py`)

- `load_all_strategies()`: Loads all strategy configs from disk
- `filter_strategies()`: Filters strategies by symbol/regime/timeframe/direction
- `StrategyConfig`: Dataclass representing a strategy

### Selector (`engine_alpha/strategies/selector.py`)

- `choose_strategy()`: Picks highest-priority strategy matching current context
- Caches strategies at module level for performance

### Shadow Evaluator (`engine_alpha/strategies/shadow_eval.py`)

- `strategy_allows_entry()`: Evaluates whether a strategy would allow entry given context
- Runs in **shadow mode** - logs decisions but doesn't enforce them yet

## Current Strategies

### 1. `high_vol_breakout_v1`
- **Scope**: ETHUSDT, high_vol regime, 1h timeframe, long only
- **Entry**: Confidence ≥ 0.80, breakout above Bollinger upper band
- **Priority**: 10 (highest)

### 2. `trend_observation_short_v1`
- **Scope**: ETHUSDT, trend_down/trend_up, 5m timeframe, short only
- **Entry**: Confidence ≥ 0.63, observation mode allowed
- **Priority**: 5
- **Risk**: 50% size factor (observation mode)

## Integration

### Shadow Mode Hook

In `run_step_live()`, right before `gate_and_size_trade()`:

```python
# Strategy selection (shadow mode)
strategy = choose_strategy(symbol, regime, timeframe, side)
if strategy:
    strategy_ctx = {...}  # Build context from current signal
    allowed_by_strategy = strategy_allows_entry(strategy, strategy_ctx)
    
    # Log only - doesn't change behavior
    print(f"STRATEGY-SHADOW: strategy={strategy.name} ... allowed={allowed_by_strategy}")
```

### Log Output

You'll now see lines like:

```
STRATEGY-SHADOW: strategy=trend_observation_short_v1 regime=trend_down side=short conf=0.6700 allowed=True
QUANT-GATE: checking trade regime=trend_down dir=-1 conf=0.67 side=short
QUANT-GATE: Trade allowed (notional=39.11): Observational trade allowed...
ENTRY: mode=PAPER ...
```

## Verification

### Test Strategy Loading

```bash
python3 << 'EOF'
from engine_alpha.strategies import load_all_strategies, choose_strategy

strategies = load_all_strategies()
print(f"Loaded {len(strategies)} strategies")

# Test selection
strategy = choose_strategy("ETHUSDT", "trend_down", "5m", "short")
print(f"Selected: {strategy.name if strategy else 'None'}")
EOF
```

### Monitor Shadow Mode

```bash
# Watch for strategy shadow logs
tail -f logs/chloe.service.log | grep -E "STRATEGY-SHADOW|QUANT-GATE|ENTRY"
```

### Expected Behavior

- **Shadow mode is active**: Strategy decisions are logged but not enforced
- **No behavior changes**: All existing gates still work as before
- **Strategy selection works**: Correct strategies selected for each context
- **Evaluation works**: Strategies correctly evaluate entry conditions

## Next Steps

1. **Watch shadow logs** for a few days to see strategy decisions
2. **Compare strategy vs quant gate**: See where they agree/disagree
3. **Gradually enforce**: Start enforcing strategy gate for specific strategies
4. **Add more strategies**: Create new strategy cards based on meta-strategy reflections
5. **Track per-strategy PF**: Add strategy name to trade logs for performance tracking

## Future Enhancements

- **Strategy Governor**: Auto-create strategies from meta-strategy reflections
- **Per-Strategy PF Tracking**: Track performance per strategy card
- **Strategy Evolution**: Auto-promote/demote strategies based on performance
- **Multi-Strategy Support**: Allow multiple strategies to run simultaneously

## Safety

- **Shadow mode**: Currently log-only, no enforcement
- **Non-destructive**: Existing gates still work
- **Fail-safe**: If strategy system fails, trading continues normally
- **Manual approval**: Can require manual approval for new strategies


