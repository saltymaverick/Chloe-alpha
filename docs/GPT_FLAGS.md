# GPT Flags Reference Guide

This document explains all GPT-related environment variables and provides recipes for different operational modes.

---

## 🧠 Flag Reference Table

### Reflection Flags

| Env Var | Meaning |
|---------|---------|
| `USE_GPT_REFLECTION` | Turn GPT reflection on at all (v1/v2/v4 stack). If `false` → stub / no GPT reflection. |
| `USE_GPT_REFLECTION_V2` | Use the external prompt file (`reflection_v2.txt`/`reflection_v4.txt`) instead of inline v1 prompt. |
| `USE_GPT_REFLECTION_V4` | Indicates we intend to use v4-style prompt/behavior (microstructure, drift, correlation, alpha/beta, ARE, memory, meta-reasoner). |
| `FORCE_GPT_REFLECTION_V4` | 🚨 **Developer mode**: if `1`, do NOT fallback to v1 — use v4 output or raise error. |

### Tuner Flags

| Env Var | Meaning |
|---------|---------|
| `USE_GPT_TUNER` | Turn GPT tuner on (v1/v2/v4 stack). |
| `USE_GPT_TUNER_V2` | Use the external prompt file (`tuner_v2.txt`/`tuner_v4.txt`) instead of inline v1. |
| `USE_GPT_TUNER_V4` | Indicates we want v4 tuner behavior (bounded deltas ±0.02/±1 + research inputs). |
| `FORCE_GPT_TUNER_V4` | 🚨 **Developer mode**: disable fallback to v1; use v4 tuner output or error. |

### Dream Flags

| Env Var | Meaning |
|---------|---------|
| `USE_GPT_DREAM` | Turn GPT Dream on. |
| `USE_GPT_DREAM_V4` | Use v4 Dream prompt (microstructure-aware, clustering, scenario analysis). |

**Note:** Dream doesn't have a `FORCE` flag yet – v4 Dream is already working solidly.

---

## ✅ Safe Everyday Mode (with fallback)

This is what you want for **normal operation**:

- GPT v4 tries to run
- **BUT** if it emits bad/malformed JSON, Chloe safely falls back to v1
- Nightly orchestrator never crashes from reflection/tuner issues

### Setup Command Block

```bash
cd /root/Chloe-alpha
source venv/bin/activate
set -a; source .env; set +a
export PYTHONPATH=/root/Chloe-alpha

# Turn GPT ON
export USE_GPT_REFLECTION=true
export USE_GPT_REFLECTION_V2=true      # use prompt file (v2/v4)
export USE_GPT_REFLECTION_V4=true      # enable v4 behavior

export USE_GPT_TUNER=true
export USE_GPT_TUNER_V2=true
export USE_GPT_TUNER_V4=true

export USE_GPT_DREAM=true
export USE_GPT_DREAM_V4=true

# Keep fallback ENABLED (safe)
export FORCE_GPT_REFLECTION_V4=0
export FORCE_GPT_TUNER_V4=0
```

### Behavior

- ✅ Chloe uses GPT v4 whenever possible
- ✅ If GPT output is messy → v1 handles it gracefully
- ✅ You get the intelligence **and** safety
- ✅ Safe for automated/nightly runs

---

## 🔬 v4 Testing Mode (no fallback, developer mode)

Use this when you want to see **exactly what v4 is thinking**, even if some JSON is imperfect.

**⚠️ Warning:** Only run this manually while you watch logs and JSON outputs. Do not use in automated/nightly runs.

### Setup Command Block

```bash
cd /root/Chloe-alpha
source venv/bin/activate
set -a; source .env; set +a
export PYTHONPATH=/root/Chloe-alpha

# Keep GPT v4 on
export USE_GPT_REFLECTION=true
export USE_GPT_REFLECTION_V2=true
export USE_GPT_REFLECTION_V4=true

export USE_GPT_TUNER=true
export USE_GPT_TUNER_V2=true
export USE_GPT_TUNER_V4=true

export USE_GPT_DREAM=true
export USE_GPT_DREAM_V4=true

# 🚨 Disable fallback for testing
export FORCE_GPT_REFLECTION_V4=1
export FORCE_GPT_TUNER_V4=1
```

### Run Tests

```bash
python3 -m tools.run_reflection_cycle
python3 -m tools.run_tuner_cycle
python3 -m tools.run_dream_cycle
```

### Behavior

- ✅ v4 is always used unless something catastrophic happens
- ✅ v1 fallback is disabled, so you see the real v4 behavior
- ✅ If there's anything wrong with v4, you'll get explicit errors instead of silent v1 fallback
- ⚠️ **Not safe for automated runs** - errors will propagate

### Return to Safe Mode

```bash
export FORCE_GPT_REFLECTION_V4=0
export FORCE_GPT_TUNER_V4=0
```

---

## 🧪 Recommended v4 Testing Sequence (step-by-step)

Here's a clean full sequence when you want to properly test v4 using your current data:

### Step 1: Ensure All Research Inputs Are Fresh

```bash
cd /root/Chloe-alpha
source venv/bin/activate
set -a; source .env; set +a
export PYTHONPATH=/root/Chloe-alpha

# Refresh all research data
python3 -m tools.run_are_cycle
python3 -m tools.run_microstructure_scan
python3 -m tools.run_drift_scan
python3 -m tools.run_correlation_scan
python3 -m tools.run_alpha_beta_scan
python3 -m tools.run_memory_snapshot
python3 -m tools.run_meta_review
```

### Step 2: Enable GPT v4 + Force Mode (for testing)

```bash
export USE_GPT_REFLECTION=true USE_GPT_REFLECTION_V2=true USE_GPT_REFLECTION_V4=true FORCE_GPT_REFLECTION_V4=1
export USE_GPT_TUNER=true USE_GPT_TUNER_V2=true USE_GPT_TUNER_V4=true FORCE_GPT_TUNER_V4=1
export USE_GPT_DREAM=true USE_GPT_DREAM_V4=true
```

### Step 3: Run the v4 Cycle

```bash
python3 -m tools.run_reflection_cycle
python3 -m tools.run_tuner_cycle
python3 -m tools.run_dream_cycle
```

### Step 4: Inspect Outputs

```bash
cat reports/gpt/reflection_output.json | less
cat reports/gpt/tuner_output.json | less
cat reports/gpt/dream_output.json | less
```

### Step 5: Return to Safe Mode

```bash
export FORCE_GPT_REFLECTION_V4=0
export FORCE_GPT_TUNER_V4=0
```

---

## 🧾 Quick Reference Cheat Sheet

### Safe Everyday Mode
```bash
FORCE_GPT_REFLECTION_V4=0
FORCE_GPT_TUNER_V4=0
```

### Dev Test Mode
```bash
FORCE_GPT_REFLECTION_V4=1
FORCE_GPT_TUNER_V4=1
```
⚠️ **Only use when manually testing v4 behavior**

### Enable GPT v4
```bash
USE_GPT_REFLECTION=true
USE_GPT_REFLECTION_V2=true
USE_GPT_REFLECTION_V4=true

USE_GPT_TUNER=true
USE_GPT_TUNER_V2=true
USE_GPT_TUNER_V4=true

USE_GPT_DREAM=true
USE_GPT_DREAM_V4=true
```

---

## 📝 Notes

- **v4 Features**: Reflection/Tuner/Dream v4 consume microstructure, drift, correlation, alpha/beta, ARE, memory, meta-reasoner, and symbol registry data.
- **Validation**: v4 validation is lenient - it only fails on severe errors (missing `tiers`/`symbol_insights` for Reflection, missing `proposals` for Tuner). Optional fields are auto-synthesized if missing.
- **Fallback Behavior**: With `FORCE_*_V4=0`, v4 outputs are used when JSON is mostly correct. Fallback to v1/stub only occurs on severe errors. With `FORCE_*_V4=1`, no fallback occurs - errors are re-raised.
- **Nightly Orchestrator**: Always use safe mode (`FORCE_*_V4=0`) for automated nightly runs to prevent crashes.

---

## 🔍 Interpreting v4 Outputs

When testing v4, look for:

- **Reflection v4**: Tier assignments based on microstructure patterns, drift state, alpha/beta profiles, and correlation clusters
- **Tuner v4**: Proposals that respect drift trends, microstructure regimes, and meta-reasoner warnings (deltas clamped to ±0.02 for `conf_min_delta`, ±1 for `exploration_cap_delta`)
- **Dream v4**: Scenario clustering by microstructure patterns (clean_trend, noisy, reversal_hint, indecision) and recurring failure mode detection

If you see unexpected behavior, check:
1. Are all research inputs fresh? (run the research scans first)
2. Is the prompt file present? (`config/prompts/reflection_v4.txt`, `tuner_v4.txt`, `dream_v4.txt`)
3. Are you in force mode? (check `FORCE_*_V4` flags)

