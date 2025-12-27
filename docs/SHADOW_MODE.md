# Shadow Mode - Safety Layer

## Overview

Shadow mode is a **global safety layer** that prevents any real orders from being sent to exchanges, even if Chloe's trading logic attempts to execute trades.

## How It Works

When `BYBIT_SHADOW_MODE=true` (default), the `ExchangeRouter.route_and_execute()` method:

1. **Checks shadow mode** at the very top of the function
2. **Blocks all orders** before they reach the exchange client
3. **Returns a shadow response** instead of executing

## Configuration

Set in `.env`:

```bash
BYBIT_SHADOW_MODE=true  # Default: true (safe)
```

- `true`, `1`, `yes`, `on` → Shadow mode **ENABLED** (orders blocked)
- `false`, `0`, `no`, `off` → Shadow mode **DISABLED** (orders sent)

## Shadow Response

When an order is blocked, the router returns:

```json
{
  "shadow": true,
  "symbol": "BTCUSDT",
  "side": "buy",
  "qty": 0.001,
  "price": null,
  "strategy": "exploration",
  "message": "Shadow mode active - order not sent to exchange."
}
```

## Safety Guarantees

✅ **Default is SAFE**: Shadow mode is `true` by default
✅ **Blocks ALL orders**: No exceptions, no bypasses
✅ **Early check**: Blocks before any exchange API calls
✅ **Clear logging**: All blocked orders are logged with `[SHADOW-MODE]` prefix

## Testing

```bash
# Test shadow mode is working
python3 << 'EOF'
from engine_alpha.exchanges.exchange_router import ExchangeRouter
# ... create router and intent ...
result = router.route_and_execute(intent)
assert result.get("shadow") == True
