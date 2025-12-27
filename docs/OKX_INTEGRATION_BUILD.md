# OKX Integration Build Prompt for Cursor

## Overview
This document provides a complete Cursor prompt to build the OKX exchange integration for Chloe. The integration includes:
- Exchange client modules (`engine_alpha/exchanges/`)
- Core order models (`engine_alpha/core/models.py`)
- Risk engine for order validation (`engine_alpha/risk/risk_engine.py`)
- Configuration files for risk and venue settings
- Safe DEMO mode by default

## Current State
- ✅ `engine_alpha/exchange/exchange_client.py` exists (stub with commented OKX references)
- ✅ `engine_alpha/risk/` exists (has other risk modules)
- ✅ OKX referenced in config files (funding_feeds.json, live_feeds.json) for data feeds
- ❌ `engine_alpha/exchanges/` directory does NOT exist
- ❌ `engine_alpha/core/models.py` does NOT exist
- ❌ `engine_alpha/risk/risk_engine.py` does NOT exist
- ❌ OKX trading client does NOT exist

## Project Rules to Follow
- Use absolute imports: `from engine_alpha.exchanges.okx_client import OkxClient`
- Write logs/reports to `/reports` and `/logs` only
- Keep MODE=PAPER by default
- Follow canonical structure from CURSOR_PROJECT_RULES.md

---

## CURSOR PROMPT (Copy-Paste This)

You are working on Alpha Chloe, a Python quant trading engine. The project root is `/root/Chloe-alpha`.

**GOAL:** Build a complete OKX exchange integration that is safe, well-structured, and follows Chloe's existing patterns.

**CURRENT STATE:**
- `engine_alpha/exchange/exchange_client.py` exists but has commented-out OKX references
- `engine_alpha/risk/` exists with other risk modules
- OKX is used for data feeds but NOT for trading yet
- No `engine_alpha/exchanges/` directory exists
- No `engine_alpha/core/models.py` exists
- No `engine_alpha/risk/risk_engine.py` exists

**REQUIREMENTS:**
1. Create `engine_alpha/exchanges/` directory (plural) with OKX client modules
2. Create `engine_alpha/core/models.py` with order type definitions
3. Create `engine_alpha/risk/risk_engine.py` for order validation
4. Create config files: `config/risk.yaml` and `config/venues.okx.yaml`
5. Integrate with existing `engine_alpha/exchange/exchange_client.py`
6. Use absolute imports: `from engine_alpha.exchanges.okx_client import OkxClient`
7. Keep DEMO mode ON by default (simulated=True)
8. Write logs to `/reports` and `/logs` only
9. Follow existing code patterns in the codebase

---

## PART 1: Create Core Models

**File:** `engine_alpha/core/models.py`

Create this file with order type definitions:

```python
"""
Core models for order intents and validated orders.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime


class Side(str, Enum):
    """Order side."""
    LONG = "long"
    SHORT = "short"


class OrderType(str, Enum):
    """Order type."""
    MARKET = "market"
    LIMIT = "limit"


class TdMode(str, Enum):
    """Trade mode (cash, margin, isolated, cross)."""
    CASH = "cash"
    MARGIN = "margin"
    ISOLATED = "isolated"
    CROSS = "cross"


class Venue(str, Enum):
    """Exchange venue."""
    OKX = "okx"
    BYBIT = "bybit"
    BINANCE = "binance"
    PAPER = "paper"


@dataclass
class OrderIntent:
    """Order intent before validation."""
    symbol: str
    side: Side
    order_type: OrderType
    size: float  # Base currency units (e.g., BTC for BTCUSDT)
    price: Optional[float] = None  # Required for LIMIT orders
    venue: Venue = Venue.OKX
    td_mode: TdMode = TdMode.CASH
    leverage: Optional[int] = None
    strategy: Optional[str] = None
    client_order_id: Optional[str] = None


@dataclass
class ValidatedOrder:
    """Order after risk engine validation."""
    intent: OrderIntent
    validated_at: datetime
    notional_usd: float
    risk_checks_passed: bool
    rejection_reason: Optional[str] = None
    venue_order_id: Optional[str] = None
    status: str = "pending"  # pending, filled, rejected, cancelled
```

---

## PART 2: Create Exchange Base Class

**File:** `engine_alpha/exchanges/__init__.py`

```python
"""Exchange client modules."""
```

**File:** `engine_alpha/exchanges/base_exchange.py`

```python
"""
Base exchange client interface.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from engine_alpha.core.models import OrderIntent, ValidatedOrder


class BaseExchange(ABC):
    """Base interface for exchange clients."""
    
    @abstractmethod
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get open orders."""
        pass
    
    @abstractmethod
    def place_order(self, order: ValidatedOrder) -> Dict[str, Any]:
        """Place a validated order."""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel an order."""
        pass
    
    @abstractmethod
    def get_account_balance(self) -> Dict[str, Any]:
        """Get account balance."""
        pass
    
    @abstractmethod
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get open positions."""
        pass
```

---

## PART 3: Create OKX Client

**File:** `engine_alpha/exchanges/okx_client.py`

Create a complete OKX client that:
- Uses OKX REST API v5
- Supports DEMO mode (simulated=True)
- Handles authentication (API key, secret, passphrase)
- Implements all BaseExchange methods
- Includes proper error handling
- Logs to `/reports/exchanges/okx_*.jsonl`

Reference OKX API docs:
- Base URL: `https://www.okx.com` (or `https://www.okx.com` for demo)
- Auth: HMAC-SHA256 with timestamp, method, requestPath, body
- Endpoints:
  - `/api/v5/account/balance` - Get balance
  - `/api/v5/trade/order` - Place order
  - `/api/v5/trade/cancel-order` - Cancel order
  - `/api/v5/trade/orders-pending` - Get open orders
  - `/api/v5/account/positions` - Get positions

Key requirements:
- Convert symbol format: `BTCUSDT` → `BTC-USDT` (spot) or `BTC-USDT-SWAP` (perps)
- Support `tdMode`: `cash` (spot), `isolated` (isolated margin), `cross` (cross margin)
- Use `simulated=True` parameter for demo mode
- Include proper error handling and retries
- Log all API calls to `/reports/exchanges/okx_api.jsonl`

---

## PART 4: Create Exchange Router

**File:** `engine_alpha/exchanges/exchange_router.py`

Create a router that:
- Routes orders to the correct exchange client
- Validates orders through risk engine before routing
- Handles DEMO mode (logs to `/reports/exchanges/demo_trades.jsonl`)
- Returns execution results

Key requirements:
- Check `config/venues.okx.yaml` for venue eligibility
- Call `engine_alpha.risk.risk_engine.validate_order()` before routing
- In DEMO mode, simulate execution without real API calls
- Log all routing decisions

---

## PART 5: Create Risk Engine

**File:** `engine_alpha/risk/risk_engine.py`

Create a risk engine that validates orders before execution:

**Checks to implement:**
1. **Notional checks**: Max notional per trade (from `config/risk.yaml`)
2. **Strategy checks**: Is strategy allowed to use this venue? (from `config/venues.okx.yaml`)
3. **Rate limits**: Check per-symbol and per-venue rate limits
4. **Daily drawdown guardrails**: Max daily loss (from `config/risk.yaml`)
5. **Venue eligibility**: Is venue enabled? (from `config/venues.okx.yaml`)
6. **IP restrictions**: (Optional, can be stub for now)
7. **Leverage checks**: Max leverage per symbol (from `config/venues.okx.yaml`)
8. **Per-symbol rules**: Max position size per symbol

**Return:** `ValidatedOrder` with `risk_checks_passed=True/False` and `rejection_reason` if failed

---

## PART 6: Create Configuration Files

**File:** `config/risk.yaml`

```yaml
# Risk engine configuration
max_notional_per_trade_usd: 1000.0
max_daily_loss_usd: 5000.0
max_leverage: 3
rate_limit_per_symbol_per_minute: 10
rate_limit_per_venue_per_minute: 60
enable_ip_restrictions: false
```

**File:** `config/venues.okx.yaml`

```yaml
# OKX venue configuration
enabled: true
demo_mode: true  # Set to false for real trading
base_url: "https://www.okx.com"
allowed_symbols:
  - "BTCUSDT"
  - "ETHUSDT"
  - "SOLUSDT"
  - "AVAXUSDT"
  - "DOGEUSDT"
max_leverage: 3
max_notional_per_symbol_usd: 5000.0
allowed_strategies:
  - "trend_following"
  - "mean_reversion"
  - "volatility"
  - "exploration"
```

---

## PART 7: Update Existing Exchange Client

**File:** `engine_alpha/exchange/exchange_client.py`

Update the `create_real_client()` function to uncomment and implement OKX:

```python
elif venue_l == "okx":
    from engine_alpha.exchanges.okx_client import OkxClient, OkxCredentials
    from engine_alpha.config.config_loader import load_venue_config
    
    # Load OKX venue config
    venue_cfg = load_venue_config("okx")
    
    creds_obj = OkxCredentials(
        api_key=creds.get("api_key", ""),
        secret_key=creds.get("api_secret", ""),
        passphrase=creds.get("passphrase", ""),
        simulated=venue_cfg.get("demo_mode", True)  # Default to demo mode
    )
    
    base_url = venue_cfg.get("base_url", "https://www.okx.com")
    return OkxClient(creds_obj, base_url, environment="demo" if venue_cfg.get("demo_mode", True) else "live")
```

---

## PART 8: Create Helper Functions

**File:** `engine_alpha/config/config_loader.py`

Add helper functions (if not already present):

```python
def load_venue_config(venue: str) -> Dict[str, Any]:
    """Load venue-specific configuration."""
    from pathlib import Path
    import yaml
    
    config_path = Path(__file__).parent.parent.parent / "config" / f"venues.{venue}.yaml"
    if not config_path.exists():
        return {}
    
    with config_path.open() as f:
        return yaml.safe_load(f) or {}
```

---

## PART 9: Integration Points

**File:** `engine_alpha/loop/execute_trade.py`

Add integration point (stub for now, will be wired later):

```python
# At the top, add imports:
from engine_alpha.exchanges.exchange_router import ExchangeRouter
from engine_alpha.core.models import OrderIntent, Side, OrderType, Venue

# In open_if_allowed() or similar function, add:
# router = ExchangeRouter()
# result = router.route_and_execute(order_intent)
# This will be fully integrated in a later phase
```

---

## PART 10: Test Script

**File:** `tools/test_okx_connection.py`

Create a test script:

```python
#!/usr/bin/env python3
"""Test OKX connection and basic API calls."""

import os
import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from engine_alpha.exchanges.okx_client import OkxClient, OkxCredentials

def main():
    # Load credentials from environment
    api_key = os.environ.get("OKX_API_KEY", "")
    secret_key = os.environ.get("OKX_API_SECRET", "")
    passphrase = os.environ.get("OKX_API_PASSPHRASE", "")
    
    if not all([api_key, secret_key, passphrase]):
        print("❌ Missing OKX credentials in environment")
        print("   Set: OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE")
        return 1
    
    # Create client in DEMO mode
    creds = OkxCredentials(
        api_key=api_key,
        secret_key=secret_key,
        passphrase=passphrase,
        simulated=True  # DEMO mode
    )
    
    client = OkxClient(creds, "https://www.okx.com", environment="demo")
    
    print("✅ OKX Client created")
    print(f"   Simulated: {creds.simulated}")
    print()
    
    # Test: Get open orders
    try:
        orders = client.get_open_orders()
        print(f"✅ get_open_orders() succeeded: {len(orders)} orders")
    except Exception as e:
        print(f"❌ get_open_orders() failed: {e}")
        return 1
    
    # Test: Get account balance
    try:
        balance = client.get_account_balance()
        print(f"✅ get_account_balance() succeeded")
        print(f"   Balance data: {balance}")
    except Exception as e:
        print(f"❌ get_account_balance() failed: {e}")
        return 1
    
    print()
    print("✅ All OKX connection tests passed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

---

## VERIFICATION CHECKLIST

After building, verify:

1. ✅ `engine_alpha/exchanges/` directory exists with all files
2. ✅ `engine_alpha/core/models.py` exists
3. ✅ `engine_alpha/risk/risk_engine.py` exists
4. ✅ `config/risk.yaml` exists
5. ✅ `config/venues.okx.yaml` exists
6. ✅ `engine_alpha/exchange/exchange_client.py` updated
7. ✅ All imports use absolute paths: `from engine_alpha.exchanges.okx_client import ...`
8. ✅ DEMO mode is ON by default (`simulated=True`)
9. ✅ Logs write to `/reports/exchanges/` only
10. ✅ Test script runs: `python3 -m tools.test_okx_connection`

---

## NEXT STEPS (After Build)

1. Set environment variables:
   ```bash
   export OKX_API_KEY="your_key"
   export OKX_API_SECRET="your_secret"
   export OKX_API_PASSPHRASE="your_passphrase"
   ```

2. Run test:
   ```bash
   python3 -m tools.test_okx_connection
   ```

3. Verify logs:
   ```bash
   ls -la reports/exchanges/
   cat reports/exchanges/okx_api.jsonl | tail -n 5
   ```

4. Integration with trading loop will happen in a later phase (not part of this build).

---

**END OF CURSOR PROMPT**

