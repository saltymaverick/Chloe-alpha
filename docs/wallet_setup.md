# Wallet Setup Guide - Real Exchange Integration

Complete guide for setting up real exchange wallets for Chloe.

## 🎯 Overview

Chloe uses a **safe, environment-variable-based** key management system. Real API keys are **never** stored in files - only in environment variables.

## 📁 File Structure

```
engine_alpha/config/wallets/
  ├── real_exchange_keys.json    # Template (empty keys)
  ├── real_onchain_keys.json     # Template (for future)
  └── wallet_config.json         # Active wallet configuration

.env_template.real               # Template for your .env.real file
.env.real                        # YOUR actual keys (never commit!)
```

## 🔐 Step 1: Create .env.real File

1. Copy the template:
   ```bash
   cp .env_template.real .env.real
   ```

2. Edit `.env.real` and add your real API keys:
   ```bash
   BYBIT_API_KEY=your_key_here
   BYBIT_API_SECRET=your_secret_here
   ```

3. **NEVER commit `.env.real`** - it's in `.gitignore`

## 🔑 Step 2: Load Environment Variables

Before running Chloe, load your keys:

```bash
# Load keys into environment
set -a; source .env.real; set +a

# Or export manually:
export BYBIT_API_KEY=your_key_here
export BYBIT_API_SECRET=your_secret_here
```

## ⚙️ Step 3: Configure Wallet Mode

Edit `engine_alpha/config/wallets/wallet_config.json`:

```json
{
  "active_exchange": "bybit",
  "active_wallet_mode": "paper",  // Keep "paper" until ready
  "paper_exchange": "paper",
  "real_exchange": "bybit",
  "confirm_live_trade": true       // Require confirmation for live trades
}
```

## 🛡️ Step 4: Safety Features

### Manual Confirmation (Default: ON)

By default, `confirm_live_trade: true` means:
- Live trades require manual approval
- `gate_and_size_trade()` will block trades in live mode
- Prevents accidental execution

### Disable Confirmation (Advanced)

Only disable after thorough testing:

```json
{
  "confirm_live_trade": false  // ⚠️ Trades execute automatically
}
```

## 🚀 Step 5: Switch to Live Mode

When ready to go live:

1. **Verify keys are loaded**:
   ```bash
   python3 -m tools.wallet_cli status
   ```

2. **Switch to live mode**:
   ```bash
   python3 -m tools.wallet_cli set live
   ```

3. **Restart Chloe**:
   ```bash
   systemctl restart chloe  # or your restart command
   ```

## 📊 Wallet CLI Commands

### Status
```bash
python3 -m tools.wallet_cli status
```

Shows:
- Current mode (paper/live)
- Active exchange
- API key status (configured/missing)
- Confirmation setting

### Set Mode
```bash
python3 -m tools.wallet_cli set paper  # Switch to paper
python3 -m tools.wallet_cli set live   # Switch to live
```

### Confirmation
```bash
python3 -m tools.wallet_cli confirm on   # Enable confirmation
python3 -m tools.wallet_cli confirm off   # Disable confirmation
```

## 🔍 Verification

### Check Wallet Status
```bash
python3 -m tools.wallet_cli status
```

Expected output:
```
WALLET STATUS
============================================================
Active Mode: PAPER
Active Exchange: paper
Real Exchange: bybit
Confirm Live Trades: True

API Keys Status:
------------------------------------------------------------
  BYBIT      ✅ Configured
    Key: abc12345...xyz9
  BINANCE    ❌ Missing
  OKX        ❌ Missing
```

### Test in Paper Mode First

1. Keep `active_wallet_mode: "paper"` in `wallet_config.json`
2. Run Chloe - should use paper wallet
3. Verify trades are logged but not executed on exchange
4. Check `reports/trades.jsonl` for trade records

### Switch to Live (When Ready)

1. Set `active_wallet_mode: "real"` in `wallet_config.json`
2. Or use CLI: `python3 -m tools.wallet_cli set live`
3. Restart Chloe
4. Monitor logs for "LIVE MODE" warnings
5. First trades will be blocked if `confirm_live_trade: true`

## 🚨 Safety Checklist

Before going live:

- [ ] Keys loaded from `.env.real` (not hardcoded)
- [ ] Tested in paper mode for extended period
- [ ] `confirm_live_trade: true` (manual confirmation enabled)
- [ ] Base notional set to tiny (0.25-0.5%)
- [ ] Monitoring set up (logs, alerts)
- [ ] Emergency stop plan documented
- [ ] Exchange API keys have **read-only** or **trade-only** permissions (not withdraw)

## 🔄 Switching Back to Paper

If you need to switch back:

```bash
python3 -m tools.wallet_cli set paper
# Restart Chloe
```

Or edit `wallet_config.json`:
```json
{
  "active_wallet_mode": "paper"
}
```

## 📝 Supported Exchanges

Currently supported:
- **Bybit** (primary)
- **Binance** (stub)
- **OKX** (stub)

To add a new exchange:
1. Add entry to `real_exchange_keys.json`
2. Implement exchange client in `engine_alpha/wallets/cex_wallet.py`
3. Update `wallet_config.json` with new exchange name

## 🎛️ Dashboard Integration

Wallet health panel available in dashboard:

```python
from engine_alpha.dashboard.wallet_panel import get_wallet_health

health = get_wallet_health()
# Returns: mode, exchange, keys_configured, requires_confirmation, status
```

## 🔐 Security Best Practices

1. **Never commit `.env.real`** - it's in `.gitignore`
2. **Use read-only API keys** when possible (for testing)
3. **Use trade-only keys** (no withdraw permission) for live trading
4. **Rotate keys regularly** (every 90 days)
5. **Monitor API key usage** in exchange dashboard
6. **Keep `confirm_live_trade: true`** until thoroughly tested

## 🆘 Troubleshooting

### "Missing API keys" error
- Check environment variables: `echo $BYBIT_API_KEY`
- Verify `.env.real` is loaded: `source .env.real`
- Check `wallet_cli status` for key status

### "Live mode requires manual confirmation"
- This is expected if `confirm_live_trade: true`
- Set `confirm_live_trade: false` to disable (after testing)

### Wallet not switching modes
- Check `wallet_config.json` permissions
- Verify file is writable
- Check logs for errors

## ✅ Quick Start

```bash
# 1. Create .env.real with your keys
cp .env_template.real .env.real
# Edit .env.real with your actual keys

# 2. Load keys
set -a; source .env.real; set +a

# 3. Check status
python3 -m tools.wallet_cli status

# 4. Stay in paper mode (default)
# wallet_config.json already has "active_wallet_mode": "paper"

# 5. When ready, switch to live
python3 -m tools.wallet_cli set live
```

---

**Remember: Start in paper mode, test thoroughly, then switch to live with tiny risk.**


