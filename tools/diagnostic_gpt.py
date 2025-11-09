"""
Diagnostic runner for GPT online components - Phase 26.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine_alpha.core.gpt_client import get_budget_status
from engine_alpha.core import governor
from engine_alpha.news.gpt_news_tone import run_news_tone
from engine_alpha.reflect.gpt_reflection import run_gpt_reflection


def main() -> None:
    print("== GPT Diagnostic ==")
    reflection = run_gpt_reflection()
    print(
        f"Reflection -> tokens: {reflection.get('tokens')} "
        f"cost: {reflection.get('cost_usd')}"
    )

    news = run_news_tone()
    print(
        f"News tone -> score: {news.get('score')} tokens: {news.get('tokens')} "
        f"cost: {news.get('cost_usd')}"
    )

    vote = governor.run_once()
    print(
        f"Governance -> rec: {vote.get('recommendation')} "
        f"sci: {vote.get('sci')} tokens: {vote.get('gpt_tokens')} "
        f"cost: {vote.get('gpt_cost_usd')}"
    )

    budget = get_budget_status()
    print("Budget status:", json.dumps(budget, indent=2))


if __name__ == "__main__":
    main()

