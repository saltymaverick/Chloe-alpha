"""
GPT client wrapper - Phase 26
Handles budgeted access to GPT models in a paper-safe manner.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from engine_alpha.core.paths import CONFIG, REPORTS

try:  # optional dependency for OpenAI client
    import openai  # type: ignore
except Exception:  # pragma: no cover
    openai = None  # type: ignore

DEFAULT_MODEL = "gpt-4-turbo"
DEFAULT_MAX_TOKENS = 500
DEFAULT_BUDGET = 0.50
DEFAULT_TEMPERATURE = 0.4
DEFAULT_PROMPTS_DIR = CONFIG / "prompts"

BUDGET_PATH = REPORTS / "gpt_budget.json"
CONFIG_PATH = CONFIG / "gpt.yaml"

# Rough blended pricing per 1K tokens (USD)
PRICING_PER_1K = {
    "gpt-4-turbo": 0.01,  # simplified blended estimate
}


class BudgetExceeded(Exception):
    """Raised when the daily GPT budget would be exceeded."""


def _load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {
            "model": DEFAULT_MODEL,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "daily_budget_usd": DEFAULT_BUDGET,
            "temperature": DEFAULT_TEMPERATURE,
            "prompts_dir": str(DEFAULT_PROMPTS_DIR),
        }
    try:
        with CONFIG_PATH.open("r") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    cfg.setdefault("model", DEFAULT_MODEL)
    cfg.setdefault("max_tokens", DEFAULT_MAX_TOKENS)
    cfg.setdefault("daily_budget_usd", DEFAULT_BUDGET)
    cfg.setdefault("temperature", DEFAULT_TEMPERATURE)
    cfg.setdefault("prompts_dir", str(DEFAULT_PROMPTS_DIR))
    return cfg


def _load_budget() -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    if not BUDGET_PATH.exists():
        data = {"date": today, "spent": 0.0, "limit": DEFAULT_BUDGET, "ok": True}
        BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
        BUDGET_PATH.write_text(json.dumps(data, indent=2))
        return data
    try:
        data = json.loads(BUDGET_PATH.read_text())
    except Exception:
        data = {}
    if data.get("date") != today:
        cfg = _load_config()
        limit = float(cfg.get("daily_budget_usd", DEFAULT_BUDGET))
        data = {"date": today, "spent": 0.0, "limit": limit, "ok": True}
        BUDGET_PATH.write_text(json.dumps(data, indent=2))
    return data


def _save_budget(data: Dict[str, Any]) -> None:
    BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUDGET_PATH.write_text(json.dumps(data, indent=2))


def _estimate_cost(tokens: int, model: str) -> float:
    rate = PRICING_PER_1K.get(model, 0.01)
    return round((tokens / 1000.0) * rate, 6)


def _ensure_budget_headroom(estimate_cost: float) -> Dict[str, Any]:
    budget = _load_budget()
    limit = float(budget.get("limit", DEFAULT_BUDGET))
    spent = float(budget.get("spent", 0.0))
    if spent + estimate_cost > limit:
        budget["ok"] = False
        _save_budget(budget)
        raise BudgetExceeded(f"Daily GPT budget exceeded: {spent + estimate_cost:.4f} > {limit:.4f}")
    return budget


def _read_api_key() -> Optional[str]:
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key
    env_path = CONFIG.parent / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text().splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            return None
    return None


def load_prompt(name: str) -> str:
    cfg = _load_config()
    prompts_dir = Path(cfg.get("prompts_dir") or DEFAULT_PROMPTS_DIR)
    path = prompts_dir / f"{name}.txt"
    try:
        return path.read_text().strip()
    except Exception:
        return ""


def query_gpt(prompt: str, purpose: str) -> Optional[Dict[str, Any]]:
    """
    Query GPT with budget enforcement.

    Returns:
        dict with keys {text, cost_usd, tokens} or None on failure.
    """
    cfg = _load_config()
    model = cfg.get("model", DEFAULT_MODEL)
    max_tokens = int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS))
    temperature = float(cfg.get("temperature", DEFAULT_TEMPERATURE))
    estimate = _estimate_cost(max_tokens, model)

    try:
        budget = _ensure_budget_headroom(estimate)
    except BudgetExceeded as exc:
        logging.warning("GPT budget exceeded for %s: %s", purpose, exc)
        return None

    if openai is None:
        logging.warning("openai package not available; skipping GPT call for %s", purpose)
        return None

    api_key = _read_api_key()
    if not api_key:
        logging.warning("OPENAI_API_KEY missing; cannot execute GPT call for %s", purpose)
        return None

    openai.api_key = api_key

    try:
        response = openai.ChatCompletion.create(  # type: ignore
            model=model,
            messages=[{"role": "system", "content": f"Purpose: {purpose}"}, {"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:  # pragma: no cover
        logging.warning("GPT call failed for %s: %s", purpose, exc)
        return None

    text = ""
    if response and response.choices:
        text = response.choices[0].message.get("content", "").strip()  # type: ignore

    usage = getattr(response, "usage", None)
    tokens_val: Any = max_tokens
    if isinstance(usage, dict):
        tokens_val = usage.get("total_tokens", max_tokens)
    elif usage is not None:
        tokens_val = getattr(usage, "total_tokens", max_tokens)
    try:
        tokens = int(tokens_val)
    except Exception:
        tokens = max_tokens
    cost = _estimate_cost(tokens, model)

    limit = float(budget.get("limit", DEFAULT_BUDGET))
    new_total = float(budget.get("spent", 0.0)) + cost
    if new_total > limit + 1e-9:
        budget["ok"] = False
        _save_budget(budget)
        logging.warning("GPT budget exceeded after call for %s (%.4f > %.4f)", purpose, new_total, limit)
        return None

    budget["spent"] = round(new_total, 6)
    budget["ok"] = True
    _save_budget(budget)

    return {"text": text, "cost_usd": cost, "tokens": tokens}


def get_budget_status() -> Dict[str, Any]:
    """Return the current GPT budget snapshot."""
    return _load_budget()

