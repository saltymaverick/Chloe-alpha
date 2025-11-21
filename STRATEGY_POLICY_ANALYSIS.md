# Strategy & Policy Threshold Analysis
## Reviewing run_step_live() Entry Triggers and Gating Logic

---

## 1. When does `run_step_live()` trigger `execute_trade`?

### Current Implementation:
**`execute_trade()` is NOT directly called in `run_step_live()`** - instead, the function uses:
- `open_if_allowed()` from `execute_trade.py` (line 416)
- `close_now()` for exits (line 478)

### Entry Trigger Path (lines 436-438):
```python
if policy.get("allow_opens", True) and final["dir"] != 0:
    if not (live_pos and live_pos.get("dir") == final["dir"]):
        _try_open(final["dir"], final["conf"])
```

### Entry Requirements (ALL must pass):

1. **Orchestrator Policy Gate**: `policy.get("allow_opens")` must be `True`
2. **Direction Gate**: `final["dir"] != 0` (must be ±1, not neutral)
3. **Position State Gate**: No existing position in same direction
4. **Confidence Threshold**: `final["conf"] >= entry_min_conf` (inside `_try_open` → `open_if_allowed`)
5. **Position Sizing Gates**: Multiple checks inside `_try_open()`:
   - `risk_r > 0` (line 406)
   - `can_open()` - gross/symbol exposure caps (line 410)
   - `pretrade_check()` - spread/latency limits (line 414)

---

## 2. Confidence Thresholds

### Default Entry Thresholds (by regime):
From `gates.yaml` and `confidence_engine.py`:

| Regime   | Entry Min Conf | Exit Min Conf | Reverse Min Conf |
|----------|----------------|---------------|------------------|
| **trend** | **0.58**       | 0.42          | 0.55             |
| **chop**  | **0.64** ⚠️    | 0.42          | 0.55             |
| **high_vol** | **0.62**    | 0.42          | 0.55             |

### Default Function Parameters (line 347-349):
```python
entry_min_conf: float = 0.58,  # Can be overridden but uses regime-specific gates
exit_min_conf: float = 0.42,
reverse_min_conf: float = 0.55,
```

### Problem: **Chop regime has highest threshold (0.64)**
- Most difficult to enter during chop
- May explain why entries are rare if market is frequently in chop

---

## 3. Direction Filters

### How `final["dir"]` is Computed:

1. **Signal Processing** → `signal_vector: List[float]` (12 signals, normalized -1..+1)

2. **Bucket Scores** → Aggregated into 5 buckets:
   - momentum, meanrev, flow, positioning, timing

3. **Bucket Directions** → Using `DIR_THRESHOLD = 0.05`:
   ```python
   if abs(bucket_score) < 0.05:
       dir = 0  # Neutral
   else:
       dir = 1 if score > 0 else -1
   ```

4. **Council Aggregation** → Weighted by regime:
   - **trend**: momentum=0.45, meanrev=0.10, flow=0.25, positioning=0.15, timing=0.05
   - **chop**: momentum=0.15, meanrev=0.45, flow=0.20, positioning=0.15, timing=0.05
   - **high_vol**: momentum=0.30, meanrev=0.10, flow=0.35, positioning=0.20, timing=0.05

5. **Final Direction** → Aggregated council vote determines `final["dir"]` ∈ {-1, 0, +1}

### Potential Issue: **`final_dir` flipping between 0 and ±1**
- If signals are noisy, `final["dir"]` may frequently be 0 (no signal)
- Entry condition requires `final["dir"] != 0`, so neutral states block entries
- Even when `dir != 0`, if `conf < entry_min_conf`, no entry occurs

---

## 4. Position/Regime Gating

### Position State Gating (lines 436-438):
```python
if policy.get("allow_opens", True) and final["dir"] != 0:
    if not (live_pos and live_pos.get("dir") == final["dir"]):  # Blocks duplicate direction
        _try_open(final["dir"], final["conf"])
```

**Blocks entries if:**
- Already have position in same direction
- Allows entry if flat or opposite direction (for flip)

### Regime Gating:
- **Regime-specific entry thresholds** (see Section 2)
- **No explicit regime-based blocking** - only affects confidence threshold
- Chop regime requires 0.64 vs 0.58 for trend (10% higher bar)

### Position Sizing Gating (inside `_try_open`, lines 399-434):

1. **Risk R Check** (line 406): `risk_r > 0` - Must have positive risk allocation
2. **Exposure Caps** (line 410): `can_open(gross_after, symbol_after, sizing_cfg)`
   - Default: `max_gross_exposure_r = 4.0`
   - Default: `max_symbol_exposure_r = 2.0`
3. **Pretrade Checks** (line 414): `pretrade_check(spread_bps, latency_ms, sizing_cfg)`
   - Default: `reject_if_spread_bps_gt = 20` (rejects if spread > 20 bps)
   - Default: `reject_if_latency_ms_gt = 2000` (rejects if latency > 2000ms)

---

## 5. Orchestrator Policy Gates

### Policy Source: `orchestrator_snapshot.json` (via `_load_policy()`, lines 222-233)

Current snapshot shows:
```json
{
  "inputs": {
    "rec": "REVIEW",
    "count": 4,
    "pf_weighted": 0.0,
    ...
  },
  "policy": {
    "allow_opens": true,
    "allow_pa": false
  },
  "notes": "paper-only; insufficient sample"
}
```

### Policy Evaluation Logic (`pa_policy.py`):

#### REC=REVIEW Handling:
- **`REC=REVIEW` does NOT block opens by itself** ❌
- Line 21: `else: rsn.append("REC!=GO")` - Just logs reason, doesn't block
- **Only `REC=PAUSE` blocks opens** (line 16)

#### Min-Trade-Count Gating:
- **Line 11**: `if cnt<DEFAULTS["min_sample"] or pf is None: rsn.append("insufficient sample")`
- Default: `min_sample = 30` trades
- **Current state: count=4** → Reason: "insufficient sample"
- **BUT**: `allow_opens` still defaults to `True` unless explicitly blocked

#### PA OFF Impact:
- `allow_pa = False` only affects profit amplifier multiplier
- **Does NOT block entries** - only affects position sizing via `rmult`
- Line 372: `rmult = max(0.5, min(1.25, float(pa_mult) * adapter_mult))`
- When PA off: `pa_mult = 1.0` (line 364), so only risk_adapter affects size

#### Full Policy Blocking Conditions:
From `pa_policy.py`:
1. **`REC=PAUSE`** → Blocks both opens and PA
2. **Insufficient sample** (count < 30) → Logs reason, **doesn't block opens**
3. **PF < 0.98** → Logs reason, **doesn't block opens**
4. **Loss streak >= 7** → Logs reason, **doesn't block opens**
5. **Risk band not A/B** → **Blocks opens** (line 157 in orchestrator.py)

---

## 6. Signal Quality Issues

### Problem: "final_dir keeps flipping between 0 and ±1 but conf rarely > threshold"

#### Root Causes:

1. **DIR_THRESHOLD = 0.05 is low**
   - Small signal changes cause dir to flip 0 ↔ ±1
   - No hysteresis or smoothing

2. **Council aggregation may dilute confidence**
   - If buckets disagree (some +, some -, some 0), final conf can be low
   - Regime weights favor different buckets, so regime changes affect confidence

3. **Confidence rarely exceeds threshold**
   - Entry requires: `conf >= entry_min_conf` (0.58-0.64 depending on regime)
   - If signals are weak/noisy, conf may hover 0.30-0.50, rarely hitting 0.58+

### Diagnostic Questions:
- What is typical `final["conf"]` distribution?
- How often is regime="chop" (requires 0.64)?
- Are signals properly normalized?
- Is council aggregation too conservative?

---

## 7. Position Rules

### Flat Position Requirement:
**YES** - System expects position to be flat before new opens in same direction:
- Line 436-438: Checks `not (live_pos and live_pos.get("dir") == final["dir"])`
- `open_if_allowed()` also checks (line 43 in execute_trade.py):
  ```python
  if pos and pos.get("dir") == final_dir:
      return False  # duplicate-direction guard
  ```

### Chop Rejection:
**NO explicit chop rejection**, but:
- **Chop regime has highest entry threshold (0.64)**
- Effectively makes entries harder during chop
- This may be intentional (avoid trading in uncertain conditions)

### PF Window Requirements:
**NO explicit PF window gating for entries**, but:
- Orchestrator checks `pf_weighted` and `count` for policy reasons
- If count < 30, logs "insufficient sample" but doesn't block
- If PF < thresholds, logs reasons but doesn't block entries (unless REC=PAUSE)

### Other Position Rules:

1. **Exit Conditions** (lines 446-456):
   - Take profit: `same_dir and final["conf"] >= take_profit_conf` (default 0.28)
   - Stop loss: `opposite_dir and final["conf"] >= stop_loss_conf` (default 0.12)
   - Flip: `opposite_dir and final["conf"] >= reverse_min_conf` (0.55)
   - Drop: `final["conf"] < exit_min_conf` (0.42)
   - Decay: `bars_open >= decay_bars` (default 8)

2. **Reopen After Flip** (line 488):
   - If exit was flip, automatically tries to open in new direction
   - Requires `policy.get("allow_opens", True)` still true

---

## 8. Summary of Entry Blocking Points

### All gates that can block entries:

1. ✅ **Orchestrator Policy**: `allow_opens = False` (from REC=PAUSE or risk_band not A/B)
2. ✅ **Direction Gate**: `final["dir"] == 0` (no signal)
3. ✅ **Confidence Gate**: `final["conf"] < entry_min_conf` (regime-specific: 0.58-0.64)
4. ✅ **Duplicate Position**: Already have position in same direction
5. ✅ **Risk R**: `risk_r <= 0` (no risk allocation)
6. ✅ **Exposure Caps**: Gross or symbol exposure exceeds limits
7. ✅ **Pretrade Checks**: Spread > 20bps OR Latency > 2000ms

### Gates that do NOT block (but affect size/reasons):
- ❌ REC=REVIEW (only logs reason)
- ❌ Count < 30 (only logs "insufficient sample")
- ❌ PF < thresholds (only logs reason)
- ❌ Loss streak < 7 (only logs if >= 7)
- ❌ PA OFF (only affects position size multiplier)

---

## 9. Recommendations

### To Increase Entry Frequency:

1. **Lower Entry Thresholds** (especially chop):
   - Current: trend=0.58, chop=0.64, high_vol=0.62
   - Suggested: trend=0.55, chop=0.60, high_vol=0.58
   - **Risk**: More false signals, need to monitor win rate

2. **Add Hysteresis to Direction**:
   - Smooth `final["dir"]` with moving average or threshold bands
   - Reduce flipping between 0 ↔ ±1

3. **Diagnose Signal Quality**:
   - Log `final["conf"]` distribution to understand why it's low
   - Check if regime classifier is too aggressive (too much chop)
   - Verify signal normalization and bucket aggregation

4. **Review Pretrade Checks**:
   - Current: reject if spread > 20bps
   - May be too strict for some market conditions
   - Consider dynamic thresholds based on volatility

5. **Consider REC=GO Requirement**:
   - Currently only REC=PAUSE blocks
   - Could require REC=GO to enable entries (adds safety but reduces frequency)

---

## Files Referenced:

- `/root/engine_alpha/engine_alpha/loop/autonomous_trader.py` (run_step_live)
- `/root/engine_alpha/engine_alpha/loop/execute_trade.py` (open_if_allowed)
- `/root/engine_alpha/engine_alpha/core/confidence_engine.py` (decide, thresholds)
- `/root/engine_alpha/engine_alpha/core/pa_policy.py` (policy evaluation)
- `/root/engine_alpha/engine_alpha/loop/orchestrator.py` (policy orchestration)
- `/root/engine_alpha/engine_alpha/config/gates.yaml` (threshold config)
- `/root/engine_alpha/engine_alpha/core/position_sizing.py` (sizing gates)




























