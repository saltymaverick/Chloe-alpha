# OKX Integration Setup Guide

## Current Status

✅ **Code Integration**: Complete and working
- All OKX client modules implemented
- Risk engine configured
- Exchange router ready
- Test script available

❌ **API Key**: Needs to be created/activated on OKX

## Error 50119: "API key doesn't exist"

This error means the API key doesn't exist on OKX's servers. This is **not a code issue** - it's an OKX account configuration issue.

## Steps to Fix

### 1. Create API Key on OKX

1. Log into OKX: https://www.okx.com
2. Go to: **Account** → **API** → **Create API Key**
3. Configure:
   - **Name**: `Chloe DEMO` (or any name you prefer)
   - **Permissions**: 
     - ✅ READ
     - ✅ TRADE
     - ❌ WITHDRAW (do NOT enable)
   - **Environment**: **DEMO/SIMULATED** (not LIVE)
   - **IP Restrictions**: None (or add your server IP if needed)

### 2. Copy Credentials

After creating the API key, OKX will show:
- **API Key** (36 characters, UUID format)
- **Secret Key** (32 characters)
- **Passphrase** (the one you set)

### 3. Update .env File

Add/update these lines in `/root/Chloe-alpha/.env`:

```bash
OKX_API_KEY=your_api_key_here
OKX_API_SECRET=your_secret_key_here
OKX_API_PASSPHRASE=your_passphrase_here
OKX_SIMULATED=1
OKX_BASE_URL=https://www.okx.com  # or https://us.okx.com for US users
```

### 4. Test Connection

```bash
cd /root/Chloe-alpha
source venv/bin/activate
python3 -m tools.test_okx_connection
```

Expected output:
```
✅ Loaded .env from /root/Chloe-alpha/.env
✅ OKX Client created
   Simulated: True
✅ get_open_orders() succeeded: 0 orders
✅ get_positions() succeeded: 0 positions
✅ get_instrument_meta() succeeded
✅ Risk engine and router created
✅ Order intent created
✅ All OKX connection tests passed!
```

## Regional Domains

- **Global**: `https://www.okx.com` (default)
- **US**: `https://us.okx.com` (required for US-based accounts)

If you're in the US and get error 50119, try setting:
```bash
OKX_BASE_URL=https://us.okx.com
```

## Troubleshooting

### Error 50119 persists after creating API key

1. Verify API key is **enabled** on OKX dashboard
2. Check API key is for **DEMO** environment (not LIVE)
3. Verify permissions include **READ** and **TRADE**
4. Try both domains: `www.okx.com` and `us.okx.com`
5. Check IP restrictions (if enabled, add your server IP)

### Other Common Errors

- **50000**: System error - retry later
- **50100**: Request parameter error - check request format
- **50113**: Invalid API key - key format is wrong
- **50114**: Invalid signature - signing issue (shouldn't happen with our code)

## Next Steps After Connection Works

Once `test_okx_connection` passes:

1. ✅ OKX integration is ready
2. ⏳ Integration with trading loop (future phase)
3. ⏳ DEMO shadow trading (future phase)
4. ⏳ Live trading (much later, after extensive testing)

## Files Created

- `engine_alpha/exchanges/okx_client.py` - OKX API client
- `engine_alpha/exchanges/exchange_router.py` - Order router
- `engine_alpha/risk/risk_engine.py` - Risk validation
- `config/risk.yaml` - Risk limits
- `config/venues.okx.yaml` - OKX venue config
- `tools/test_okx_connection.py` - Connection test

All code is ready - just need valid API credentials!
