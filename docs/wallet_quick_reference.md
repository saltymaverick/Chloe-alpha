# Wallet Quick Reference Card

**One-page cheat sheet for wallet operations**

---

## 🔐 Setup (One-Time)

```bash
# 1. Create .env.real from template
cp .env_template.real .env.real

# 2. Edit .env.real with your actual API keys
nano .env.real

# 3. Load keys into environment
set -a; source .env.real; set +a

# 4. Verify keys loaded
python3 -m tools.wallet_cli status
```

---

## 📊 Check Status

```bash
# CLI
python3 -m tools.wallet_cli status

# Python
from engine_alpha.config.config_loader import load_wallet_config
cfg = load_wallet_config()
print(f"Mode: {cfg.active_wallet_mode}")
```

---

## 🔄 Switch Modes

```bash
# Switch to paper (safe)
python3 -m tools.wallet_cli set paper

# Switch to live (requires keys + confirmation)
python3 -m tools.wallet_cli set live

# Text command (via operator)
handle_wallet_command("wallet set real")
```

---

## 🛡️ Confirmation Settings

```bash
# Enable confirmation (default, safe)
python3 -m tools.wallet_cli confirm on

# Disable confirmation (after testing)
python3 -m tools.wallet_cli confirm off

# Text command
handle_wallet_command("wallet confirm off")
```

---

## 🚀 Go Live Checklist

- [ ] `.env.real` created with real API keys
- [ ] Keys loaded: `source .env.real`
- [ ] Status shows keys configured: `wallet_cli status`
- [ ] Tested in paper mode (50-100 trades)
- [ ] Ready to switch: `wallet_cli set live`
- [ ] After testing: `wallet_cli confirm off`

---

## 📁 Key Files

```
.env.real                          # YOUR keys (never commit)
engine_alpha/config/wallets/
  ├── wallet_config.json           # Active mode + limits
  ├── real_exchange_keys.json      # Template (empty)
  └── real_onchain_keys.json       # Template (empty)
```

---

## 🔍 Verify Keys Loaded

```bash
# Check environment
echo $BYBIT_API_KEY

# Check via CLI
python3 -m tools.wallet_cli status
# Should show "✅ Configured" for your exchange

# Check via Python
from engine_alpha.config.config_loader import load_real_exchange_keys
keys = load_real_exchange_keys()
print(keys["bybit"]["api_key"][:8] + "...")  # First 8 chars
```

---

## ⚙️ Configuration

Edit `engine_alpha/config/wallets/wallet_config.json`:

```json
{
  "active_wallet_mode": "paper",        // "paper" | "real"
  "real_exchange": "bybit",             // "bybit" | "binance" | "okx"
  "confirm_live_trade": true,           // Require confirmation
  "max_live_notional_per_trade_usd": 500,
  "max_live_daily_notional_usd": 5000
}
```

---

## 🚨 Emergency: Switch Back to Paper

```bash
# Quick switch
python3 -m tools.wallet_cli set paper

# Or edit wallet_config.json directly
# Set "active_wallet_mode": "paper"
```

---

## 📝 Exchange Client Usage

```python
from engine_alpha.exchange.exchange_client import get_active_exchange_client

# Automatically uses paper or real based on wallet_config
client = get_active_exchange_client()

# In paper mode: returns None (paper trading handled elsewhere)
# In live mode: returns real exchange client (when implemented)
```

---

## 🎛️ Dashboard Integration

```python
from engine_alpha.dashboard.wallet_panel import wallet_health_panel, get_wallet_health

# Streamlit
wallet_health_panel()

# JSON
health = get_wallet_health()
print(health["mode"], health["status"])
```

---

## ✅ Safety Features

- ✅ Keys never in files (env vars only)
- ✅ Manual confirmation default (`confirm_live_trade: true`)
- ✅ Notional limits enforced (`max_live_notional_per_trade_usd`)
- ✅ Live mode check in `gate_and_size_trade()`
- ✅ CLI commands for safe switching

---

**Print this page and keep it handy when going live!**


