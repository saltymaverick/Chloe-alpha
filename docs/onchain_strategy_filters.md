# On-Chain Strategy Filters

Chloe now supports on-chain (Glassnode) filters in strategy cards, allowing strategies to condition entries on on-chain metrics.

## What Was Added

### 1. On-Chain Filter Evaluation (`engine_alpha/strategies/shadow_eval.py`)

Added `_evaluate_onchain_filters()` function that evaluates conditions like:
- `"<= 0"`, `">= 0"`, `"< 0"`, `"> 0"` - Numeric comparisons
- `"> threshold"`, `"< threshold"` - Custom thresholds
- `"increasing"`, `"decreasing"` - Trend checks (TODO: requires lookback)

### 2. Strategy Context Enhancement (`engine_alpha/loop/autonomous_trader.py`)

Strategy context now automatically includes Glassnode metrics:
- `gn_exchange_netflow` - Latest exchange net flow value
- `gn_addresses_active` - Latest active addresses count
- Any other `gn_*` columns from cached Glassnode data

### 3. Updated Strategy Card (`high_vol_breakout_v1.json`)

Added example on-chain filters:
```json
"onchain": {
  "gn_exchange_netflow": "<= 0",
  "gn_addresses_active": "> 0"
}
```

This means: only take high-vol breakouts when:
- Exchange netflow is not positive (no big inflows → less dump risk)
- Active addresses are positive (on-chain activity present)

## How It Works

1. **Data Flow**:
   - Glassnode metrics cached to `data/glassnode/{SYMBOL}_glassnode.parquet`
   - Latest metrics loaded into strategy context during `run_step_live()`
   - Strategy evaluation checks on-chain conditions

2. **Filter Evaluation**:
   - On-chain filters are evaluated **after** other filters (confidence, spread, etc.)
   - If any on-chain condition fails, entry is blocked
   - Missing metrics fail open (allow trade) - can be made configurable later

3. **Shadow Mode**:
   - Currently runs in shadow mode (logs only)
   - Check logs for `STRATEGY-SHADOW` to see filter decisions
   - Not enforced yet - will be enabled after validation

## Usage

### Add On-Chain Filters to a Strategy

Edit any strategy card in `engine_alpha/config/strategies/`:

```json
{
  "entry_logic": {
    "filters": {
      "confidence_min": 0.80,
      "onchain": {
        "gn_exchange_netflow": "<= 0",
        "gn_addresses_active": "> 10000"
      }
    }
  }
}
```

### Supported Conditions

**Numeric Comparisons**:
- `"<= 0"` - Less than or equal to zero
- `">= 0"` - Greater than or equal to zero
- `"< 0"` - Less than zero
- `"> 0"` - Greater than zero
- `">= 1000"` - Greater than or equal to custom threshold
- `"<= -500"` - Less than or equal to custom threshold

**Trend Checks** (TODO - requires lookback):
- `"increasing"` - Metric is trending up
- `"decreasing"` - Metric is trending down

### Verify On-Chain Filters Are Working

1. **Check Strategy Context**:
   ```bash
   # Look for Glassnode metrics in strategy context
   grep -i "gn_" logs/*.log | tail -20
   ```

2. **Check Strategy Shadow Logs**:
   ```bash
   # See strategy decisions with on-chain context
   grep "STRATEGY-SHADOW" logs/*.log | tail -20
   ```

3. **Verify Glassnode Data**:
   ```bash
   python3 -m tools.verify_glassnode_integration --symbol ETHUSDT
   ```

## Example: High-Vol Breakout with On-Chain Filters

The `high_vol_breakout_v1` strategy now includes:

```json
"onchain": {
  "gn_exchange_netflow": "<= 0",
  "gn_addresses_active": "> 0"
}
```

**Interpretation**:
- Only take long breakouts when exchange netflow is neutral or negative
- Require active addresses to be positive (on-chain activity)

**Rationale**:
- Positive exchange netflow = coins moving TO exchanges = potential sell pressure
- Negative/neutral netflow = coins staying in wallets or moving FROM exchanges = less dump risk
- Active addresses > 0 = basic on-chain activity present

## Next Steps

### 1. Enable Enforcement (After Validation)

Once you've validated on-chain filters in shadow mode, enable enforcement:

In `engine_alpha/loop/autonomous_trader.py`, uncomment:
```python
if not allowed_by_strategy:
    print(f"STRATEGY-GATE: blocked by strategy {strategy.name}")
    return  # skip trade
```

### 2. Add More Metrics

Extend `config/glassnode_config.json` with more metrics:
```json
{
  "metrics": {
    "exchange_netflow": "/flow/exchange/net",
    "addresses_active": "/addresses/active_count",
    "mvrvt_ratio": "/indicators/mvrv",
    "nvt_ratio": "/indicators/nvt"
  }
}
```

### 3. Implement Trend Detection

Add lookback data to strategy context for `"increasing"`/`"decreasing"` checks:
- Load last N values of each metric
- Compute trend (slope, moving average, etc.)
- Evaluate trend conditions

### 4. Meta-Strategy Integration

Include on-chain aggregates in meta-strategy reflection:
- Mean/median netflows
- Trends in active addresses
- On-chain regime classification

## Troubleshooting

### "On-chain metrics not available"

- Check Glassnode API key is set in `config/glassnode_config.json`
- Fetch data: `python3 -m tools.fetch_glassnode_data --symbol ETHUSDT`
- Verify cache exists: `ls -lh data/glassnode/ETHUSDT_glassnode.parquet`

### "Strategy allows entry but on-chain filter should block"

- Check strategy context includes Glassnode metrics (look for `gn_*` in logs)
- Verify filter conditions are correct (check metric values)
- Check if metrics are `None` (fail open behavior)

### "Unknown condition in on-chain filter"

- Check condition syntax matches supported formats
- For custom thresholds, use `">= threshold"` or `"<= threshold"`
- Trend checks (`increasing`/`decreasing`) not yet implemented

## Files Changed

1. `engine_alpha/strategies/shadow_eval.py` - Added `_evaluate_onchain_filters()`
2. `engine_alpha/loop/autonomous_trader.py` - Added Glassnode metrics to strategy context
3. `engine_alpha/config/strategies/high_vol_breakout_v1.json` - Added example on-chain filters
4. `tools/verify_glassnode_integration.py` - Verification script


