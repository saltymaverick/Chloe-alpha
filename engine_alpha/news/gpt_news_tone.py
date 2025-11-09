"""
GPT-based news tone summarizer - Phase 26.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from engine_alpha.core.gpt_client import load_prompt, query_gpt
from engine_alpha.core.paths import REPORTS

NEWS_SOURCES = [
    REPORTS / "news_headlines.jsonl",
    REPORTS / "news_headlines.json",
    REPORTS / "news_cache.jsonl",
    REPORTS / "news_cache.json",
]


def _load_headlines(limit: int = 50) -> List[str]:
    headlines: List[str] = []
    for path in NEWS_SOURCES:
        if not path.exists():
            continue
        try:
            if path.suffix == ".jsonl":
                for line in path.read_text().splitlines():
                    if len(headlines) >= limit:
                        break
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    title = obj.get("title") or obj.get("headline")
                    if isinstance(title, str):
                        headlines.append(title.strip())
            else:
                data = json.loads(path.read_text())
                items = data if isinstance(data, list) else data.get("headlines", [])
                for item in items:
                    if len(headlines) >= limit:
                        break
                    if isinstance(item, str):
                        headlines.append(item.strip())
                    elif isinstance(item, dict):
                        title = item.get("title") or item.get("headline")
                        if isinstance(title, str):
                            headlines.append(title.strip())
        except Exception:
            continue
        if len(headlines) >= limit:
            break
    if not headlines:
        headlines = [
            "Markets mixed as traders digest macro data.",
            "Crypto institutional inflows remain steady.",
            "Regulatory outlook uncertain amid policy debates.",
        ]
    return headlines[:limit]


def _parse_score(text: str) -> float:
    matches = re.findall(r"-?\d+(?:\.\d+)?", text)
    for match in matches:
        try:
            value = float(match)
        except ValueError:
            continue
        if -1.5 <= value <= 1.5:
            return max(-1.0, min(1.0, value))
    return 0.0


def run_news_tone(limit: int = 50) -> Dict[str, object]:
    headlines = _load_headlines(limit=limit)
    prompt_template = load_prompt("news_tone")
    if not prompt_template:
        prompt_template = "Provide a tone score between -1 and +1."
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "headlines": headlines,
    }
    prompt = f"{prompt_template}\n\nHeadlines:\n- " + "\n- ".join(headlines)
    result = query_gpt(prompt, "news_tone")
    summary_text = result.get("text") if result else ""
    score = _parse_score(summary_text) if summary_text else 0.0

    news_record = {
        "ts": payload["ts"],
        "score": score,
        "reason": summary_text or "No GPT response",
    }
    news_path = REPORTS / "news_tone.json"
    news_path.write_text(json.dumps(news_record, indent=2))

    log_record = {
        "ts": payload["ts"],
        "score": score,
        "reason": summary_text,
        "cost_usd": result.get("cost_usd") if result else 0.0,
        "tokens": result.get("tokens") if result else 0,
    }
    log_path = REPORTS / "gpt_news_tone.jsonl"
    with log_path.open("a") as f:
        f.write(json.dumps(log_record) + "\n")

    return log_record

