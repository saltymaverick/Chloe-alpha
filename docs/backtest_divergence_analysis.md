# Backtest Divergence Analysis & Fixes

## Critical Bug #1: `decide()` Uses Wrong Regime

**Location**: `engine_alpha/loop/autonomous_trader.py:699`

**Problem**:
- `decide()` internally calls `get_regime()` which computes regime from signal data (not price data)
- `_compute_council_aggregation()` inside `decide()` uses this signal-based regime
- But `run_step_live` then overrides the regime with `price_based_regime` (line 702)
- This means council aggregation used the WRONG regime

**Impact**: 
- Council aggregation uses regime from signals (could be different from price-based regime)
- This causes different confidence scores in backtest vs live if signal-based regime differs

**Fix**: Pass price-based regime to `decide()` or skip `decide()` and compute manually

## Critical Bug #2: Manual Aggregation Uses Wrong Weights

**Location**: `engine_alpha/loop/autonomous_trader.py:734`

**Problem**:
- After calling `decide()`, `run_step_live` manually recomputes `final_score` (lines 732-797)
- Manual computation uses `COUNCIL_WEIGHTS` (legacy weights with "trend", "chop", "high_vol" keys)
- But `_compute_council_aggregation()` uses `REGIME_BUCKET_WEIGHTS` (per-regime weights with "trend_up", "trend_down", etc.)
- These are DIFFERENT weight systems!

**Impact**:
- Manual recomputation produces different confidence than `decide()` would with correct regime
- Backtests and live might use different weight systems

**Fix**: Use `REGIME_BUCKET_WEIGHTS` in manual computation, or use `_compute_council_aggregation()` directly

## Critical Bug #3: `decide()` Result Is Ignored

**Location**: `engine_alpha/loop/autonomous_trader.py:699-797`

**Problem**:
- `decide()` is called and returns `decision["final"]` with dir/conf
- But then `run_step_live` manually recomputes `final_score` and creates `effective_final_dir`/`effective_final_conf`
- The `decision["final"]` is never used for entry/exit decisions!
- Only `effective_final_dir`/`effective_final_conf` are used

**Impact**:
- `decide()` computation is wasted
- Two different aggregation paths (one in `decide()`, one manual) could diverge

**Fix**: Use `decision["final"]` directly OR don't call `decide()` and do everything manually

## Proposed Fixes

### Fix 1: Pass Regime to `decide()` (Recommended)

Modify `decide()` to accept optional `regime_override`:

```python
def decide(signal_vector: List[float], raw_registry: Dict[str, Any],
           classifier: Optional[RegimeClassifier] = None,
           regime_override: Optional[str] = None) -> Dict[str, Any]:
    # ...
    if regime_override:
        regime = regime_override
    else:
        regime_result = get_regime(signal_vector, raw_registry, classifier)
        regime = regime_result["regime"]
    # ... rest of function
```

Then in `run_step_live`:
```python
regime_info = classify_regime(window)
price_based_regime = regime_info.get("regime", "chop")

out = get_signal_vector_live(symbol=symbol, timeframe=timeframe, limit=limit)
decision = decide(out["signal_vector"], out["raw_registry"], regime_override=price_based_regime)
final = decision["final"]  # Now uses correct regime!
```

### Fix 2: Use `_compute_council_aggregation()` Directly

Instead of manual recomputation, call `_compute_council_aggregation()` with correct regime:

```python
from engine_alpha.core.confidence_engine import _compute_council_aggregation

# After getting buckets from decide()
buckets = decision.get("buckets", {})
bucket_dirs = {name: buckets.get(name, {}).get("dir", 0) for name in BUCKET_ORDER}
bucket_confs = {name: buckets.get(name, {}).get("conf", 0.0) for name in BUCKET_ORDER}

# Use price-based regime
final_result = _compute_council_aggregation(
    bucket_dirs, 
    bucket_confs, 
    price_based_regime,  # Correct regime!
    IS_PAPER_MODE
)
effective_final_dir = final_result["dir"]
effective_final_conf = final_result["conf"]
```

### Fix 3: Remove Manual Aggregation Entirely

If we fix `decide()` to use correct regime, we can use `decision["final"]` directly:

```python
regime_info = classify_regime(window)
price_based_regime = regime_info.get("regime", "chop")

out = get_signal_vector_live(symbol=symbol, timeframe=timeframe, limit=limit)
decision = decide(out["signal_vector"], out["raw_registry"], regime_override=price_based_regime)
final = decision["final"]

effective_final_dir = final["dir"]
effective_final_conf = final["conf"]
```

## Additional Issues to Check

1. **Mock OHLCV in backtests**: Verify `get_live_ohlcv` mock returns correct current bar
2. **Entry price fetching**: Verify `_try_open` gets entry price from current bar
3. **Exit price fetching**: Verify `close_now` gets exit price from current bar
4. **P&L calculation**: Verify `pct` uses `entry_px` and `exit_px` correctly

## Testing

Use `tools/backtest_step_diagnostic.py` to trace a single step and verify:
- Regime classification matches
- Confidence aggregation matches
- Entry decisions match
- Exit decisions match
- P&L calculation matches


