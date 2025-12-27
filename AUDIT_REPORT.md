# Chloe System Integrity Audit

Date: 2025-12-16  
Scope: /root/Chloe-alpha

## Pass/Fail Snapshot
| Area | Status | Evidence | Notes |
| --- | --- | --- | --- |
| Loop tick chain (continuous) | ✅ | `tools/run_continuous_loop.py` calls `run_step_live()` → `run_recovery_lane_v2()` → loop health writer; jittered sleep + error backoff present | Exits/timeouts run every tick; recovery lane no longer skipped |
| Recovery lane logging → trades.jsonl | ✅ | `engine_alpha/loop/recovery_lane_v2_trades.py` mirrors opens/closes to `reports/trades.jsonl` with strategy `recovery_v2` | Verified natural close at `2025-12-16T00:26:49Z` landed |
| Recovery ramp refresh | ✅ | `tools/policy_refresh.py` now runs `tools.run_recovery_ramp` (1h step), fresh `reports/risk/recovery_ramp.json` | mtime now updates each refresh |
| PF local reporting (scratch windows) | ✅ | `tools/run_pf_local.py` sets `pf=1.0` when gross_profit=gross_loss=0 and adds scratch flags + gross P/L | PF_24h shows neutral instead of null on scratch-only |
| Provider priority & candle semantics | ✅ | `engine_alpha/data/live_prices.py`: default order Bybit→Binance; OKX only if configured; age_s from close time; drops in-progress candle; meta.attempts populated | `config/live_feeds.json` default exchanges `[bybit, binance]`; OKX only via explicit override |
| Provider cooldown backoff | ✅ | `engine_alpha/core/provider_cooldown.py`: progressive 5m→10m→30m→60m (429/timeout), 30m→60m (403); clear_cooldown resets count | Max cap 60m; reason codes carried |
| Recovery ramp gates | ⚠️ | `reports/risk/recovery_ramp.json`: `clean_closes_pass=false` (recent_clean_closes=2 / threshold=12) | pf7d_floor/slope pass; ok_ticks=0 by design until clean_closes passes |

## Key Findings
1) **Loop execution is correct**  
   `tools/run_continuous_loop.py` runs `run_step_live()`, then always `run_recovery_lane_v2()` (with isolated try/except), writes loop_health, uses 57–63s jitter and exponential backoff. Exits/timeouts cannot be skipped in halt modes.

2) **Recovery lane data plumbing fixed**  
   - Lane log: `reports/loop/recovery_lane_v2_log.jsonl`  
   - Global ledger: `reports/trades.jsonl` now receives recovery_v2 opens/closes (strategy/trade_kind set).  
   - PF/ramp now “see” recovery closes.

3) **Recovery ramp refresh un-stuck**  
   `tools/policy_refresh.py` now includes `run_recovery_ramp()`, so `reports/risk/recovery_ramp.json` updates every refresh.

4) **PF local UX improved**  
   Scratch-only windows now report `pf=1.0` with `scratch_only_*` and `gross_profit/loss_*` fields. No more “null PF” confusion when only scratches exist.

5) **Provider pipeline healthy**  
   - Default provider order Bybit→Binance; OKX disabled unless explicitly configured (`config/live_feeds.json`).  
   - `live_prices.py` canonical packet drops in-progress candle, uses close-time for `age_s`, and records `attempts` and cooldown skips.  
   - Cooldown backoff capped at 60m; reason codes handled (429/403/timeout).

6) **Remaining blocker: clean closes**  
   Recovery ramp requires `MIN_CLEAN_CLOSES=12` in the last 24h (`engine_alpha/risk/recovery_ramp.py`). Current `recent_clean_closes=2`, so `clean_closes_pass=false` and `ok_ticks=0/6`. This is expected until more non-scratch closes occur.

## Minimal Patch Plan (already applied)
- `tools/policy_refresh.py`: added `run_recovery_ramp()` step to refresh ramp snapshot.
- `engine_alpha/loop/recovery_lane_v2_trades.py`: mirror recovery_v2 opens/closes into `reports/trades.jsonl`.
- `tools/run_pf_local.py`: neutral PF for scratch-only windows; added scratch flags and gross P/L fields.

## Operator Checklist (host)
- Loop health: `systemctl status chloe_loop --no-pager`
- Recovery lane activity: `tail -n 80 reports/loop/recovery_lane_v2_log.jsonl`
- Recovery closes in ledger: `tail -n 300 reports/trades.jsonl | grep '"strategy": "recovery_v2"' | tail -n 20`
- PF local: `python3 -m tools.run_pf_local && cat reports/pf_local.json | python3 -m json.tool`
- Ramp snapshot: `python3 -m tools.policy_refresh && cat reports/risk/recovery_ramp.json | python3 -m json.tool | head -160`
- Provider cooldowns: `cat reports/provider_cooldown.json 2>/dev/null`

## Risk Notes
- Recovery gating: Until 12 clean (non-scratch) closes land in 24h, `clean_closes_pass` stays false and `ok_ticks` remain 0. This is expected; no code change needed.  
- PF reporting: Scratch-only PF now surfaces as 1.0; downstream gates should continue to rely on PF_7D / clean_closes, not PF_24h alone.  
- Provider behavior: OKX remains disabled by default; ensure any explicit overrides are intentional.

