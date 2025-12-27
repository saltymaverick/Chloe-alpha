# Symbol Registry

## Overview

The Symbol Registry provides a centralized, config-driven way to manage tradable assets. Adding or removing coins is as simple as editing `config/symbols.yaml`.

## Configuration

### File: `config/symbols.yaml`

```yaml
symbols:
  - id: BTCUSDT
    enabled: true
    tier_hint: tier1
  - id: ETHUSDT
    enabled: true
    tier_hint: tier1
  - id: SOLUSDT
    enabled: true
    tier_hint: tier2
  # ... more symbols
```

### Fields

- **id**: Symbol identifier (e.g., "ETHUSDT")
- **enabled**: Whether the symbol should be traded (true/false)
- **tier_hint**: Optional tier hint for Reflection/Tuner/Evolver (tier1/tier2/tier3)

## Usage

### Adding a Coin

1. Add entry to `config/symbols.yaml`:
   ```yaml
   - id: OPUSDT
     enabled: true
     tier_hint: tier2
   ```

2. Ensure data feed is configured for that symbol (e.g., in `asset_registry.json` or data source configs)

3. Run system sanity to verify:
   ```bash
   python3 -m tools.system_sanity
   ```

4. The symbol will automatically be included in:
   - Trading loop (if enabled=true)
   - ARE analysis
   - Reflection/Tuner/Dream cycles
   - Quality scores
   - Evolver/Mutation preview

### Disabling a Coin

Set `enabled: false` in `config/symbols.yaml`:

```yaml
- id: MATICUSDT
  enabled: false
  tier_hint: tier2
```

The symbol will:
- Stop being traded
- Continue to be analyzed in research cycles (if data exists)
- Can be re-enabled by setting `enabled: true`

## API

### Load Enabled Symbols

```python
from engine_alpha.core.symbol_registry import load_symbol_registry

enabled_symbols = load_symbol_registry()
# Returns: ["BTCUSDT", "ETHUSDT", "SOLUSDT", ...]
```

### Load Symbol Metadata

```python
from engine_alpha.core.symbol_registry import load_symbol_metadata

metadata = load_symbol_metadata()
# Returns: {
#   "ETHUSDT": {"enabled": True, "tier_hint": "tier1"},
#   ...
# }
```

### Check if Symbol is Enabled

```python
from engine_alpha.core.symbol_registry import is_symbol_enabled

if is_symbol_enabled("ETHUSDT"):
    # Trade ETHUSDT
```

### Get Tier Hint

```python
from engine_alpha.core.symbol_registry import get_symbol_tier_hint

tier = get_symbol_tier_hint("ETHUSDT")
# Returns: "tier1" or None
```

## Integration

### With Trading Loop

The trading loop can use the registry:

```python
from engine_alpha.core.symbol_registry import load_symbol_registry

enabled_symbols = load_symbol_registry()
for symbol in enabled_symbols:
    # Process symbol
```

### With Reflection/Tuner

Tier hints from the registry can inform initial expectations:

- **tier1**: Strong performers - expect high PF, allow looser thresholds
- **tier2**: Neutral/average - standard expectations
- **tier3**: Weak performers - expect lower PF, require stricter thresholds

### With Evolver/Mutation

Tier hints can gate evolution behavior:

- **tier1**: Allow promotion, mutation exploration
- **tier2**: Standard evolution rules
- **tier3**: Restrictive evolution, consider demotion

## Fallback Behavior

If `config/symbols.yaml` is missing or empty, the registry falls back to a default list:

```python
DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT",
    "ATOMUSDT", "BNBUSDT", "DOTUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT"
]
```

This ensures the system continues to work even if the registry file is missing.

## Future Enhancements

The registry can be extended with:

- **risk_bucket**: Risk classification (core/growth/infra)
- **venue**: Exchange preference (bybit/binance)
- **min_notional**: Minimum trade size
- **max_leverage**: Maximum leverage allowed
- **timeframe**: Preferred timeframe for analysis

These can be added to the YAML structure without breaking existing code.

