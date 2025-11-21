#!/usr/bin/env python3
"""
Memory Aggregator - Phase 45
Long-term memory system for Chloe that aggregates reflections, trade stats,
and lessons into episodic and long-term memory files.

This is a read-only aggregation tool that does NOT modify trading behavior.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Dict, Any, List, Optional

from engine_alpha.core.paths import REPORTS
from tools.reflect_prep import summarize_recent_trades

REFLECTIONS_LOG = REPORTS / "reflections.jsonl"
EPISODES_LOG = REPORTS / "memory" / "episodes.jsonl"
LONG_TERM_FILE = REPORTS / "memory" / "long_term_lessons.json"


def read_jsonl_tail(path: Path, n: int = 5) -> List[Dict[str, Any]]:
    """
    Read the last n records from a JSONL file.
    Returns empty list if file doesn't exist.
    """
    if not path.exists():
        return []
    
    records = []
    try:
        with path.open("r") as f:
            lines = f.readlines()
        # Take the last n lines
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                records.append(record)
            except json.JSONDecodeError:
                continue
    except Exception:
        return []
    
    return records


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    """
    Append a JSON record to a JSONL file.
    Creates parent directories if needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with path.open("a") as f:
        json_str = json.dumps(record, sort_keys=True)
        f.write(json_str + "\n")


def safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    """
    Safely load a JSON file. Returns None if file doesn't exist or is invalid.
    """
    if not path.exists():
        return None
    
    try:
        with path.open("r") as f:
            return json.load(f)
    except Exception:
        return None


def extract_lessons_from_reflection(text: str) -> Dict[str, Any]:
    """
    Extract lessons and adjustments from GPT reflection text.
    
    Looks for:
    1. "Lessons" section (markdown bullets or numbered list)
    2. JSON-only recommended adjustments block inside ```json ... ```
    
    Returns:
        {
            "lessons": [list of lesson strings],
            "adjustments": {dict of adjustments}
        }
    """
    lessons = []
    adjustments = {}
    
    if not text:
        return {"lessons": [], "adjustments": {}}
    
    # Try to extract lessons section
    # Look for patterns like "### Lessons", "## Lessons", "Lessons:", etc.
    lessons_patterns = [
        r"(?:###|##|#)\s*Lessons?\s*(?:Learned)?\s*\n(.*?)(?=\n(?:###|##|#|Recommended|\Z))",
        r"Lessons?\s*(?:Learned)?\s*[:\-]\s*\n(.*?)(?=\n(?:###|##|#|Recommended|\Z))",
        r"lessons?\s*learned\s*[:\-]\s*\n(.*?)(?=\n(?:###|##|#|Recommended|\Z))",
    ]
    
    for pattern in lessons_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
        if match:
            lessons_text = match.group(1)
            # Extract bullet points or numbered items
            # Match bullets at start of line (with optional whitespace)
            bullet_pattern = r"^[\s]*[-*•]\s+(.+?)(?=\n[\s]*[-*•]|\n[\s]*\d+\.|\n\n|\Z)"
            numbered_pattern = r"^[\s]*\d+\.\s+(.+?)(?=\n[\s]*[-*•]|\n[\s]*\d+\.|\n\n|\Z)"
            
            for bullet_match in re.finditer(bullet_pattern, lessons_text, re.MULTILINE | re.DOTALL):
                lesson = bullet_match.group(1).strip()
                if lesson and len(lesson) > 5:  # Filter out very short matches
                    lessons.append(lesson)
            
            for num_match in re.finditer(numbered_pattern, lessons_text, re.MULTILINE | re.DOTALL):
                lesson = num_match.group(1).strip()
                if lesson and len(lesson) > 5:
                    lessons.append(lesson)
            
            # If no bullets found, try to split by newlines and look for bullet-like patterns
            if not lessons:
                lines = [line.strip() for line in lessons_text.split("\n") if line.strip()]
                for line in lines:
                    # Skip markdown headers
                    if line.startswith("#"):
                        continue
                    # Check if line looks like a bullet point
                    bullet_match = re.match(r"^[-*•]\s+(.+)", line)
                    if bullet_match:
                        lesson = bullet_match.group(1).strip()
                        if lesson:
                            lessons.append(lesson)
                    # Check if line looks like a numbered item
                    num_match = re.match(r"^\d+\.\s+(.+)", line)
                    if num_match:
                        lesson = num_match.group(1).strip()
                        if lesson:
                            lessons.append(lesson)
            
            if lessons:
                break
    
    # Try to extract JSON adjustments block
    json_patterns = [
        r"```json\s*\n(.*?)\n```",
        r"```\s*\n(.*?)\n```",
        r"Recommended Adjustments.*?(\{.*?\})",
    ]
    
    for pattern in json_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
        if match:
            json_str = match.group(1).strip()
            try:
                adjustments = json.loads(json_str)
                if isinstance(adjustments, dict):
                    break
            except json.JSONDecodeError:
                # Try to find JSON object in the text
                json_obj_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", json_str, re.DOTALL)
                if json_obj_match:
                    try:
                        adjustments = json.loads(json_obj_match.group(0))
                        if isinstance(adjustments, dict):
                            break
                    except json.JSONDecodeError:
                        continue
                continue
    
    return {
        "lessons": lessons,
        "adjustments": adjustments if adjustments else {},
    }


def build_episode() -> Dict[str, Any]:
    """
    Build a new episodic memory record from recent reflections and trade stats.
    
    Returns:
        Episode dict with:
            - ts: timestamp
            - trade_stats: summary from reflect_prep
            - parsed_reflections: list of parsed reflection records
            - derived_lessons: union of all lesson bullets
            - derived_adjustments: merged JSON adjustment blocks
    """
    now = datetime.now(timezone.utc).isoformat()
    
    # Get recent trade stats
    recent_trade_stats = summarize_recent_trades(max_trades=50)
    
    # Load recent reflections
    reflections = read_jsonl_tail(REFLECTIONS_LOG, n=5)
    
    parsed_reflections = []
    all_lessons = []
    all_adjustments = {}
    
    for reflection in reflections:
        # Extract text from reflection (could be in various fields)
        reflection_text = ""
        reflection_ts = reflection.get("timestamp") or reflection.get("ts") or now
        
        # Try common field names for GPT response text
        for field in ["response", "text", "content", "output", "reflection", "analysis"]:
            if field in reflection:
                if isinstance(reflection[field], str):
                    reflection_text = reflection[field]
                    break
                elif isinstance(reflection[field], dict):
                    # Try nested fields
                    for nested_field in ["text", "content", "message"]:
                        if nested_field in reflection[field]:
                            reflection_text = str(reflection[field][nested_field])
                            break
                    if reflection_text:
                        break
        
        # If no text field found, try to stringify the whole reflection
        if not reflection_text:
            reflection_text = json.dumps(reflection, indent=2)
        
        # Extract lessons and adjustments
        extracted = extract_lessons_from_reflection(reflection_text)
        lessons = extracted["lessons"]
        adjustments = extracted["adjustments"]
        
        parsed_reflections.append({
            "ts": reflection_ts,
            "lessons": lessons,
            "adjustments": adjustments,
        })
        
        # Accumulate lessons (deduplicate)
        for lesson in lessons:
            if lesson and lesson not in all_lessons:
                all_lessons.append(lesson)
        
        # Merge adjustments (later ones override earlier ones)
        if adjustments:
            all_adjustments.update(adjustments)
    
    episode = {
        "ts": now,
        "trade_stats": recent_trade_stats,
        "parsed_reflections": parsed_reflections,
        "derived_lessons": all_lessons,
        "derived_adjustments": all_adjustments,
    }
    
    return episode


def append_episode() -> Dict[str, Any]:
    """
    Build and append a new episode to episodes.jsonl.
    Returns the episode that was appended.
    """
    episode = build_episode()
    append_jsonl(EPISODES_LOG, episode)
    return episode


def update_long_term_knowledge() -> Dict[str, Any]:
    """
    Update long_term_lessons.json by aggregating all episodes.
    
    Returns the updated long-term knowledge dict.
    """
    # Load existing long-term knowledge (if any)
    existing = safe_load_json(LONG_TERM_FILE)
    
    # Initialize structure
    long_term = existing or {
        "global_lessons": [],
        "bucket_memory": {},
        "regime_memory": {},
        "performance_history": {
            "episode_count": 0,
            "avg_pf_last_10": None,
        },
    }
    
    # Load all episodes
    episodes = read_jsonl_tail(EPISODES_LOG, n=1000)  # Read many episodes
    
    if not episodes:
        # If no episodes, ensure file exists with baseline structure
        EPISODES_LOG.parent.mkdir(parents=True, exist_ok=True)
        with LONG_TERM_FILE.open("w") as f:
            json.dump(long_term, f, indent=2, sort_keys=True)
        return long_term
    
    # Aggregate lessons (frequency-based)
    lesson_counts: Dict[str, int] = {}
    for episode in episodes:
        for lesson in episode.get("derived_lessons", []):
            lesson_counts[lesson] = lesson_counts.get(lesson, 0) + 1
    
    # Keep lessons that appear in multiple episodes (threshold: 2+)
    frequent_lessons = [
        lesson for lesson, count in lesson_counts.items()
        if count >= 2
    ]
    # Merge with existing, avoiding duplicates
    existing_lessons = set(long_term.get("global_lessons", []))
    all_lessons = list(existing_lessons | set(frequent_lessons))
    long_term["global_lessons"] = sorted(all_lessons)
    
    # Aggregate bucket adjustments (from adjustments dicts)
    bucket_memory = long_term.get("bucket_memory", {})
    for episode in episodes:
        adjustments = episode.get("derived_adjustments", {})
        # Look for bucket-related adjustments
        for key, value in adjustments.items():
            if "bucket" in key.lower() or "weight" in key.lower():
                bucket_memory[key] = value
    long_term["bucket_memory"] = bucket_memory
    
    # Aggregate regime memory
    regime_memory = long_term.get("regime_memory", {})
    for episode in episodes:
        adjustments = episode.get("derived_adjustments", {})
        # Look for regime-related adjustments
        for key, value in adjustments.items():
            if "regime" in key.lower():
                regime_memory[key] = value
    long_term["regime_memory"] = regime_memory
    
    # Update performance history
    pfs = []
    for episode in episodes[-10:]:  # Last 10 episodes
        trade_stats = episode.get("trade_stats", {})
        pf = trade_stats.get("pf")
        if pf and isinstance(pf, (int, float)) and pf != float("inf"):
            pfs.append(float(pf))
    
    long_term["performance_history"]["episode_count"] = len(episodes)
    if pfs:
        long_term["performance_history"]["avg_pf_last_10"] = mean(pfs)
    else:
        long_term["performance_history"]["avg_pf_last_10"] = None
    
    # Write updated long-term knowledge
    LONG_TERM_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LONG_TERM_FILE.open("w") as f:
        json.dump(long_term, f, indent=2, sort_keys=True)
    
    return long_term


def main() -> None:
    """
    Main entry point: build episode, append it, update long-term knowledge.
    """
    print("Memory Aggregator - Phase 45")
    print("=" * 50)
    
    # Build and append episode
    print("\n1. Building episode...")
    episode = append_episode()
    print(f"   ✅ Episode appended: {episode['ts']}")
    print(f"   - Trade stats: {episode['trade_stats'].get('count', 0)} closes, PF={episode['trade_stats'].get('pf', 0.0):.2f}")
    print(f"   - Reflections parsed: {len(episode['parsed_reflections'])}")
    print(f"   - Lessons extracted: {len(episode['derived_lessons'])}")
    print(f"   - Adjustments: {len(episode['derived_adjustments'])} keys")
    
    # Update long-term knowledge
    print("\n2. Updating long-term knowledge...")
    long_term = update_long_term_knowledge()
    print(f"   ✅ Long-term knowledge updated")
    print(f"   - Global lessons: {len(long_term.get('global_lessons', []))}")
    print(f"   - Episode count: {long_term['performance_history']['episode_count']}")
    print(f"   - Avg PF (last 10): {long_term['performance_history']['avg_pf_last_10']}")
    
    print("\n✅ Memory aggregation complete")
    print(f"   Episodes: {EPISODES_LOG}")
    print(f"   Long-term: {LONG_TERM_FILE}")


if __name__ == "__main__":
    main()

