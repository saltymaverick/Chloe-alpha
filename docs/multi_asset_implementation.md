# Multi-Asset Implementation - Phase 1

## Overview

Chloe now supports trading multiple assets (12 coins) through a clean asset registry system. Currently, only ETHUSDT is enabled, preserving existing behavior.

## Architecture

### Asset Registry (`config/asset_registry.json`)

Single source of truth for all tradable assets:
- **12 coins**: BTC, ETH, SOL, AVAX, LINK, MATIC, ATOM, BNB, DOT, ADA, XRP, DOGE
- **Per-asset config**: timeframe, venue, risk_bucket, leverage, min_notional
- **Enable/disable**: `enabled: true/false` flag per asset

### Asset Loader (`engine_alpha/config/assets.py`)

- `load_all_assets()`: Loads all assets from registry
- `get_enabled_assets()`: Returns only enabled assets
- `get_asset(symbol)`: Get config for specific symbol
- `AssetConfig`: Dataclass with all asset properties

### Multi-Asset Runner (`engine_alpha/loop/multi_asset_runner.py`)

- `run_all_live_symbols()`: Iterates over enabled assets
- Calls `run_step_live(symbol, timeframe)` for each asset
- Error handling: continues with next asset if one fails
- Logs: `MULTI-ASSET: running live step for {symbol} @ {timeframe}`

## Current Status

### Enabled Assets
- ✅ **ETHUSDT** @ 1h (core risk bucket)

### Disabled Assets (ready to enable)
- ⏸️ BTCUSDT, SOLUSDT, AVAXUSDT, LINKUSDT, MATICUSDT, ATOMUSDT, BNBUSDT, DOTUSDT, ADAUSDT, XRPUSDT, DOGEUSDT

## Usage

### Manual Run

```bash
# Run multi-asset tick (processes all enabled assets)
python3 -m engine_alpha.loop.multi_asset_runner

# Should see:
# MULTI-ASSET: tick at ... for 1 assets
# MULTI-ASSET: running live step for ETHUSDT @ 1h
# ... existing run_step_live logs ...
```

### Enable Additional Assets

1. Edit `config/asset_registry.json`:
```json
"BTCUSDT": {
  "enabled": true,  // Change from false to true
  ...
}
```

2. Run multi-asset runner:
```bash
python3 -m engine_alpha.loop.multi_asset_runner
```

3. Verify logs show both assets:
```
MULTI-ASSET: running live step for ETHUSDT @ 1h
MULTI-ASSET: running live step for BTCUSDT @ 1h
```

### Systemd Integration (Optional)

Update `/etc/systemd/system/chloe.service`:

```ini
ExecStart=/usr/bin/env bash -lc 'source venv/bin/activate && python -m engine_alpha.loop.multi_asset_runner'
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl restart chloe.service
```

## Verification

### Test Asset Loading

```bash
python3 << 'EOF'
from engine_alpha.config.assets import get_enabled_assets

assets = get_enabled_assets()
print(f"Enabled: {len(assets)}")
for a in assets:
    print(f"  {a.symbol} @ {a.base_timeframe}")
EOF
```

### Test Multi-Asset Runner

```bash
python3 -m engine_alpha.loop.multi_asset_runner
```

Expected output:
- `MULTI-ASSET: tick at ... for 1 assets`
- `MULTI-ASSET: running live step for ETHUSDT @ 1h`
- Existing `run_step_live` logs for ETHUSDT

## Backward Compatibility

✅ **Fully backward compatible:**
- Only ETHUSDT enabled by default
- Existing `run_step_live()` works unchanged
- All existing gates, strategies, PF logic unchanged
- Can still call `run_step_live()` directly for ETHUSDT

## Next Steps

1. **Watch multi-asset runner** for a few days with ETHUSDT only
2. **Enable BTCUSDT** when ready to test second asset
3. **Per-asset research**: Extend nightly research to build per-symbol datasets
4. **Per-asset PF**: Track PF per symbol (already structured for this)
5. **Per-asset strategies**: Strategy cards can specify which symbols they apply to

## Safety

- **Non-destructive**: Existing ETH pipeline unchanged
- **Fail-safe**: Errors in one asset don't crash others
- **Gradual rollout**: Enable assets one at a time
- **Easy rollback**: Set `enabled: false` to disable any asset


