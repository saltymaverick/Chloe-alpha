# Asset Audit Tool - Multi-Asset Readiness Checker

## Overview

`tools/asset_audit.py` is a read-only diagnostic tool that checks each symbol's readiness for paper and live trading. It validates:

1. **Config** - Asset registry entry completeness
2. **Data** - Live OHLCV CSV and hybrid research dataset
3. **Research** - Analyzer stats, strategy strength, confidence map
4. **Thresholds** - Per-symbol regime thresholds
5. **PF** - Profit factor and trade history

## Usage

### Audit all assets (paper readiness)

```bash
python3 -m tools.asset_audit --all
```

### Audit enabled assets only

```bash
python3 -m tools.asset_audit --enabled-only
```

### Audit a single symbol

```bash
python3 -m tools.asset_audit --symbol ETHUSDT
python3 -m tools.asset_audit --symbol BTCUSDT
```

### Audit for LIVE readiness (stricter PF/trade checks)

```bash
python3 -m tools.asset_audit --enabled-only --for-live
```

## Output Format

The tool outputs JSON with per-symbol audit results:

```json
[
  {
    "symbol": "ETHUSDT",
    "config_ok": true,
    "data_ok": true,
    "research_ok": true,
    "thresholds_ok": true,
    "pf_ok": false,
    "ready_for_paper": true,
    "ready_for_live": false,
    "details": {
      "config": { "symbol": "ETHUSDT", "base_timeframe": "1h", ... },
      "data": { "live_rows": 1345, "hybrid_rows": ">= 1", ... },
      "research": { "has_strength": true, "has_conf_map": true, ... },
      "thresholds": { "enabled_regimes": ["high_vol", "trend_down"], ... },
      "pf": { "pf_val": 0.98, "total_trades": 10, ... }
    },
    "issues": [
      "PF (0.980) below minimum of 0.90."
    ]
  }
]
```

## Readiness Criteria

### `ready_for_paper`
- ✅ `config_ok` - Asset config is valid
- ✅ `data_ok` - Live OHLCV CSV exists with ≥200 rows
- ✅ `research_ok` - Analyzer stats exist
- ✅ `thresholds_ok` - Per-symbol thresholds exist with enabled regimes

### `ready_for_live`
- ✅ All `ready_for_paper` criteria
- ✅ `pf_ok` - PF ≥ 0.90 and ≥10 trades
- ✅ Asset is enabled in registry

## Common Issues

### "Live OHLCV CSV not found"
- **Cause**: Multi-asset runner hasn't started collecting candles yet
- **Fix**: Enable asset in `config/asset_registry.json` and run `multi_asset_runner`

### "Hybrid research dataset parquet not found yet"
- **Cause**: Nightly research hasn't run yet
- **Fix**: Run `python3 -m engine_alpha.reflect.nightly_research`

### "Analyzer stats missing or empty"
- **Cause**: Nightly research failed or insufficient data (<200 candles)
- **Fix**: Wait for more live candles, then rerun nightly research

### "No thresholds found for this symbol"
- **Cause**: Tuner hasn't generated per-symbol thresholds yet
- **Fix**: Run nightly research with `run_tuning=True`

### "Too few trades (X < 10) to trust PF"
- **Cause**: Not enough trade history for live readiness
- **Fix**: Wait for more trades to accumulate (paper mode is fine)

### "PF (X.XXX) below minimum of 0.90"
- **Cause**: Profit factor is too low for live trading
- **Fix**: Review strategy, thresholds, or wait for better market conditions

## Workflow Integration

### Before enabling a new coin

1. Add coin to `config/asset_registry.json` with `enabled: false`
2. Run multi-asset runner to start collecting candles
3. Wait for ≥200 candles
4. Run nightly research
5. Check readiness:
   ```bash
   python3 -m tools.asset_audit --symbol BTCUSDT
   ```
6. If `ready_for_paper: true`, set `enabled: true` in registry

### Before moving from paper → live

1. Ensure asset has been trading in paper mode
2. Check live readiness:
   ```bash
   python3 -m tools.asset_audit --symbol ETHUSDT --for-live
   ```
3. Verify:
   - `ready_for_live: true`
   - `pf_ok: true` (PF ≥ 0.90, ≥10 trades)
   - No critical issues

## Quick Status Summary

Get a quick overview of all assets:

```bash
python3 -m tools.asset_audit --all | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'Total assets: {len(d)}')
print(f'Ready for paper: {sum(1 for r in d if r[\"ready_for_paper\"])}')
print(f'Ready for live: {sum(1 for r in d if r[\"ready_for_live\"])}')
print('\nPer-symbol status:')
for r in sorted(d, key=lambda x: x['symbol']):
    print(f'  {r[\"symbol\"]:12} | paper={r[\"ready_for_paper\"]:5} | live={r[\"ready_for_live\"]:5} | issues={len(r[\"issues\"])}')
"
```

## Integration with CI/CD

The tool can be integrated into automated checks:

```bash
# Fail if any enabled asset is not ready for paper
python3 -m tools.asset_audit --enabled-only | python3 -c "
import sys, json
d = json.load(sys.stdin)
not_ready = [r for r in d if not r['ready_for_paper']]
if not_ready:
    print('❌ Assets not ready for paper:', file=sys.stderr)
    for r in not_ready:
        print(f'  {r[\"symbol\"]}: {r[\"issues\"]}', file=sys.stderr)
    sys.exit(1)
"
```

## Notes

- **Read-only**: This tool never modifies files or configs
- **Non-destructive**: Safe to run anytime
- **Fast**: Uses lightweight checks (row counts, file existence)
- **JSON output**: Easy to parse and integrate with other tools


