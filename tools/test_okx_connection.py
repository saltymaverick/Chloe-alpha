#!/usr/bin/env python3
"""
Test OKX connection and basic API calls.

⚠️  DEPRECATED: OKX integration is decommissioned.
    This script is kept for reference only.
    Use tools/test_bybit_connection.py instead.
"""

import os
import sys
from pathlib import Path
from decimal import Decimal
from dotenv import load_dotenv

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Load environment variables from .env file
env_path = ROOT_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"✅ Loaded .env from {env_path}")
else:
    print(f"⚠️  .env file not found at {env_path}")

from engine_alpha.exchanges.okx_client import OkxClient, OkxCredentials
from engine_alpha.risk.risk_engine import RiskEngine
from engine_alpha.exchanges.exchange_router import ExchangeRouter
from engine_alpha.core.models import OrderIntent, Side, OrderType, Venue


def dummy_pnl_provider():
    return {"daily_loss_abs": 0.0, "daily_loss_pct": 0.0}


def dummy_position_provider():
    return []


def main():
    # Load credentials from environment
    api_key = os.environ.get("OKX_API_KEY", "")
    secret_key = os.environ.get("OKX_API_SECRET", "")
    passphrase = os.environ.get("OKX_API_PASSPHRASE", "")
    
    # Handle OKX_SIMULATED flag - default to True (DEMO mode) for safety
    simulated_str = os.environ.get("OKX_SIMULATED", "1").strip().lower()
    if simulated_str in ("1", "true", "yes", "on"):
        simulated = True
    elif simulated_str in ("0", "false", "no", "off"):
        simulated = False
    else:
        simulated = True  # Default to DEMO mode for safety
        print(f"⚠️  OKX_SIMULATED='{simulated_str}' not recognized, defaulting to True (DEMO mode)")
    
    if not all([api_key, secret_key, passphrase]):
        print("❌ Missing OKX credentials in environment")
        print("   Set: OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE")
        return 1
    
    # Create client in DEMO mode
    creds = OkxCredentials(
        api_key=api_key,
        secret_key=secret_key,
        passphrase=passphrase,
        simulated=simulated
    )
    
    # Try US domain first if in US, otherwise use global domain
    # US users must use us.okx.com, others use www.okx.com
    base_url = os.environ.get("OKX_BASE_URL", "https://www.okx.com")
    
    client = OkxClient(
        creds=creds,
        rest_base_url=base_url,
        environment="demo",
    )
    
    print("✅ OKX Client created")
    print(f"   Simulated: {creds.simulated} ({'DEMO mode' if creds.simulated else 'LIVE mode'})")
    
    if not creds.simulated:
        print("   ⚠️  WARNING: Running in LIVE mode!")
        print("      If your API key is for DEMO/SIMULATED, set OKX_SIMULATED=1 in .env")
        print("      LIVE mode will place real trades (not simulated)")
    
    print()
    
    # Test: Get open orders
    try:
        orders = client.get_open_orders()
        print(f"✅ get_open_orders() succeeded: {len(orders)} orders")
    except Exception as e:
        print(f"❌ get_open_orders() failed: {e}")
        return 1
    
    # Test: Get positions
    try:
        positions = client.get_positions()
        print(f"✅ get_positions() succeeded: {len(positions)} positions")
    except Exception as e:
        print(f"❌ get_positions() failed: {e}")
        return 1
    
    # Test: Get instrument meta
    try:
        meta = client.get_instrument_meta("BTC-USDT-SWAP")
        print(f"✅ get_instrument_meta() succeeded")
        print(f"   Instrument: {meta.get('instId')}, lotSz: {meta.get('lotSz')}, minSz: {meta.get('minSz')}")
    except Exception as e:
        print(f"❌ get_instrument_meta() failed: {e}")
        return 1
    
    # Test: Create risk engine and router
    try:
        risk_engine = RiskEngine(
            risk_config_path="config/risk.yaml",
            pnl_provider=dummy_pnl_provider,
            position_provider=dummy_position_provider,
        )
        
        router = ExchangeRouter(
            risk_engine=risk_engine,
            okx_client=client,
        )
        print("✅ Risk engine and router created")
    except Exception as e:
        print(f"❌ Risk engine/router creation failed: {e}")
        return 1
    
    # Test: Create order intent (but don't execute)
    try:
        intent = OrderIntent(
            strategy_id="exploration",
            venue=Venue.OKX,
            symbol="BTC-USDT-SWAP",
            side=Side.BUY,
            quantity=Decimal("1"),
            price=None,
            order_type=OrderType.MARKET,
        )
        print("✅ Order intent created")
        print(f"   Strategy: {intent.strategy_id}, Symbol: {intent.symbol}, Side: {intent.side.value}")
    except Exception as e:
        print(f"❌ Order intent creation failed: {e}")
        return 1
    
    print()
    print("✅ All OKX connection tests passed!")
    print()
    print("💡 To test order placement (DEMO mode), uncomment the route_and_execute call below:")
    print("   # resp = router.route_and_execute(intent)")
    print("   # print(resp)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

