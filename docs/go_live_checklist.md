# Go-Live Checklist for Chloe Alpha

## Pre-Flight: Paper Mode Validation

### ✅ Research & Configuration
- [ ] `regime_thresholds.json` exists with real learned values
- [ ] `confidence_map.json` has non-zero expected returns
- [ ] `strategy_strength.json` shows regime edges
- [ ] SWARM verification passes (`analyzer_ok`, `strengths_ok`, `thresholds_ok`, `confidence_map_ok`)
- [ ] Entry thresholds are reasonable (0.48-0.65 range)
- [ ] Exit rules are configured per regime

### ✅ Trading Behavior
- [ ] At least 20-30 paper trades completed
- [ ] PF_local trending positive or stable
- [ ] No excessive scratch trades (>50% scratches)
- [ ] Exits are working (TP/SL/drop/decay all firing)
- [ ] Observation trades behaving as expected (50% size, reasonable PnL)

### ✅ Risk Management
- [ ] Quant gate is blocking bad trades appropriately
- [ ] Position sizing is reasonable (not too large/small)
- [ ] Drawdown is manageable (<15%)
- [ ] No "zombie" positions stuck forever

---

## Phase 1: Bybit Sub-Account Setup

### 1.1 Create Sub-Account
- [ ] Log into Bybit main account
- [ ] Create sub-account named "Chloe_Trader"
- [ ] Fund with small test amount ($500-$2,000 recommended)
- [ ] Verify sub-account is active and funded

### 1.2 Generate API Keys
- [ ] Navigate to API Management → Create API Key
- [ ] Set permissions:
  - ✅ Trade & Read (required)
  - ❌ Withdrawals (disabled for safety)
- [ ] Set IP restriction if possible (your server IP)
- [ ] Copy API Key and Secret (store securely)

### 1.3 Environment Variables
- [ ] Copy `.env_template.real` to `.env.real`
- [ ] Fill in:
  ```bash
  BYBIT_API_KEY=your_subaccount_key_here
  BYBIT_API_SECRET=your_subaccount_secret_here
  ```
- [ ] Verify `.env.real` is NOT committed to git (check `.gitignore`)

---

## Phase 2: Configuration Updates

### 2.1 Wallet Configuration
- [ ] Update `config/wallets/wallet_config.json`:
  ```json
  {
    "active_wallet_mode": "paper",  // Keep as "paper" for now
    "paper_exchange": "paper",
    "real_exchange": "bybit",
    "confirm_live_trade": true,     // Safety: require confirmation
    "max_live_notional_per_trade_usd": 50,
    "max_live_daily_notional_usd": 300
  }
  ```

### 2.2 Observation Mode (Optional)
- [ ] Review `config/observation_mode.json`:
  ```json
  {
    "observation_regimes": ["trend_up", "trend_down"],
    "edge_floor": -0.0015,
    "size_factor": 0.5,
    "max_open_trades": 3
  }
  ```
- [ ] Adjust if needed (more/less aggressive)

### 2.3 Exit Rules
- [ ] Verify `config/exit_rules.json` has `max_hold_bars` for observation regimes (24 bars = 2h on 5m timeframe)
- [ ] Ensure TP/SL targets are reasonable

---

## Phase 3: Safety Switches

### 3.1 Auto-Stop Conditions (Future)
- [ ] Plan for: If `PF_local_live < 0.9` OR `drawdown > 0.15`:
  - Stop opening new trades
  - Optionally switch back to paper mode
- [ ] (Not implemented yet - manual monitoring for now)

### 3.2 Monitoring Setup
- [ ] Set up alerts for:
  - Large drawdowns (>10%)
  - Consecutive losses (>5 in a row)
  - PF dropping below 0.95
- [ ] Dashboard accessible for real-time monitoring

---

## Phase 4: Test Run (Paper Mode with Real Config)

### 4.1 Dry Run
- [ ] Keep `active_wallet_mode: "paper"` 
- [ ] Load real API keys (but wallet mode = paper)
- [ ] Verify service starts without errors
- [ ] Confirm no real trades are attempted

### 4.2 Verification
- [ ] Check logs: `grep -i "live mode\|real\|bybit" logs/*.log`
- [ ] Verify wallet panel shows "paper" mode
- [ ] Confirm `confirm_live_trade: true` is respected

---

## Phase 5: Go Live (Tiny Risk)

### 5.1 Final Checks
- [ ] Paper mode has been stable for at least 1 week
- [ ] PF_local > 1.0 and trending up
- [ ] No critical SWARM warnings
- [ ] Sub-account funded with test amount
- [ ] API keys tested and working

### 5.2 Flip the Switch
- [ ] Update `config/wallets/wallet_config.json`:
  ```json
  {
    "active_wallet_mode": "real",  // ⚠️ CHANGE THIS
    "confirm_live_trade": true,    // Keep true for first trades
    ...
  }
  ```
- [ ] Restart service: `sudo systemctl restart chloe.service`
- [ ] Monitor closely for first few trades

### 5.3 First Live Trades
- [ ] Watch logs: `tail -f logs/chloe.service.log | grep -E "QUANT-GATE|ENTRY|EXIT"`
- [ ] Verify trades appear in Bybit sub-account
- [ ] Check `reports/trades.jsonl` for live trades
- [ ] Confirm notional sizes match expectations

---

## Phase 6: Scaling Up (After Validation)

### 6.1 After 10-20 Successful Trades
- [ ] Review PF and win rate
- [ ] If positive, consider:
  - Increasing `max_live_notional_per_trade_usd` (e.g., 50 → 100)
  - Increasing `max_live_daily_notional_usd` (e.g., 300 → 500)

### 6.2 After 50+ Trades
- [ ] Full performance review
- [ ] Consider disabling `confirm_live_trade` if behavior is stable
- [ ] Adjust observation mode parameters if needed
- [ ] Plan for main account migration (if desired)

---

## Emergency Procedures

### If Something Goes Wrong
1. **Immediate Stop:**
   ```bash
   sudo systemctl stop chloe.service
   ```

2. **Switch Back to Paper:**
   ```bash
   # Edit config/wallets/wallet_config.json
   # Set "active_wallet_mode": "paper"
   sudo systemctl start chloe.service
   ```

3. **Review Logs:**
   ```bash
   tail -n 100 logs/chloe.service.log
   grep -i "error\|exception\|blocked" logs/chloe.service.log
   ```

4. **Check Trades:**
   ```bash
   tail -n 20 reports/trades.jsonl
   cat reports/pf_local.json
   ```

---

## Notes

- **Start Small:** First live trades should be tiny ($10-50 notional)
- **Monitor Closely:** Watch first 10-20 trades in real-time
- **Keep Confirmation:** Leave `confirm_live_trade: true` until proven stable
- **Document Everything:** Keep notes on what works/doesn't work

---

## Current Status

- ✅ Observation mode: Configurable via JSON
- ✅ Exit logging: Enhanced with regime, PnL, bars_open
- ✅ Time-based stop-out: 24 bars max for observation regimes
- ✅ Max open trades: Limited to 3 for observation regimes
- ⏳ Real mode prep: Checklist ready, awaiting validation
