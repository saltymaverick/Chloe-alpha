"""
GPT client wrapper - Phase 26 migration to OpenAI v1 SDK.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from engine_alpha.core.paths import CONFIG, REPORTS

try:  # pragma: no cover - optional dependency
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_TOKENS = 500
DEFAULT_TEMPERATURE = 0.4
DEFAULT_BUDGET = 0.50
DEFAULT_PROMPTS_DIR = CONFIG / "prompts"

CONFIG_PATH = CONFIG / "gpt.yaml"
BUDGET_PATH = REPORTS / "gpt_budget.json"

_CLIENT: Optional["OpenAI"] = None


def get_cfg() -> Dict[str, Any]:
    """Load GPT configuration with sensible defaults."""
    cfg: Dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r") as fh:
                cfg = yaml.safe_load(fh) or {}
        except Exception:
            cfg = {}
    cfg.setdefault("model", DEFAULT_MODEL)
    cfg.setdefault("max_tokens", DEFAULT_MAX_TOKENS)
    cfg.setdefault("temperature", DEFAULT_TEMPERATURE)
    cfg.setdefault("daily_budget_usd", DEFAULT_BUDGET)
    cfg.setdefault("prompts_dir", str(DEFAULT_PROMPTS_DIR))
    return cfg


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _load_budget_raw(cfg: Dict[str, Any]) -> Dict[str, Any]:
    today = _today_iso()
    if not BUDGET_PATH.exists():
        data = {"date": today, "spent": 0.0, "limit": float(cfg["daily_budget_usd"]), "ok": True}
        BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
        BUDGET_PATH.write_text(json.dumps(data, indent=2))
        return data
    try:
        data = json.loads(BUDGET_PATH.read_text())
    except Exception:
        data = {}
    if data.get("date") != today:
        data = {"date": today, "spent": 0.0, "limit": float(cfg["daily_budget_usd"]), "ok": True}
        BUDGET_PATH.write_text(json.dumps(data, indent=2))
    return data


def read_write_budget(cost_add: float) -> Dict[str, Any]:
    """
    Update the budget file with an additional cost (may be zero).
    """
    cfg = get_cfg()
    budget = _load_budget_raw(cfg)
    try:
        cost_val = float(cost_add)
    except Exception:
        cost_val = 0.0
    new_spent = float(budget.get("spent", 0.0)) + cost_val
    limit = float(budget.get("limit", cfg["daily_budget_usd"]))
    if new_spent > limit + 1e-9:
        budget["ok"] = False
    else:
        budget["spent"] = round(new_spent, 6)
        budget["ok"] = True
    BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUDGET_PATH.write_text(json.dumps(budget, indent=2))
    return budget


def _get_budget_snapshot() -> Dict[str, Any]:
    cfg = get_cfg()
    return _load_budget_raw(cfg)


def load_prompt(name: str) -> str:
    cfg = get_cfg()
    prompts_dir = Path(cfg.get("prompts_dir") or DEFAULT_PROMPTS_DIR)
    path = prompts_dir / f"{name}.txt"
    try:
        return path.read_text().strip()
    except Exception:
        return ""


def _get_client() -> Optional["OpenAI"]:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if OpenAI is None:
        return None
    try:
        _CLIENT = OpenAI()
    except Exception as exc:  # pragma: no cover
        logging.warning("Failed to initialise OpenAI client: %s", exc)
        _CLIENT = None
    return _CLIENT


def query_gpt(prompt: str, purpose: str) -> Optional[Dict[str, Any]]:
    """
    Execute a GPT query under budget control using the OpenAI v1 SDK.
    """
    cfg = get_cfg()
    budget = _get_budget_snapshot()
    spent = float(budget.get("spent", 0.0))
    limit = float(budget.get("limit", cfg["daily_budget_usd"]))
    if spent >= limit:
        logging.warning("GPT budget exhausted for %s (spent %.4f / %.4f)", purpose, spent, limit)
        return None

    client = _get_client()
    if client is None:
        logging.warning("OpenAI client unavailable; skipping GPT call for %s", purpose)
        return None

    try:
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": "You are Chloe's analyst. Be concise and structured."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=int(cfg["max_tokens"]),
            temperature=float(cfg["temperature"]),
        )
    except Exception as exc:  # pragma: no cover
        logging.warning("GPT call failed for %s: %s", purpose, exc)
        return None

    text = ""
    tokens: Optional[int] = None
    if response and getattr(response, "choices", None):
        try:
            text = response.choices[0].message.content or ""
        except Exception:
            text = ""
    usage = getattr(response, "usage", None)
    if usage is not None:
        try:
            tokens = int(getattr(usage, "total_tokens", None) or usage.get("total_tokens"))
        except Exception:
            tokens = None

    read_write_budget(0.0)
    return {"text": text.strip(), "tokens": tokens, "cost_usd": 0.0}


def get_budget_status() -> Dict[str, Any]:
    """Return the current GPT budget snapshot."""
    return _get_budget_snapshot()

