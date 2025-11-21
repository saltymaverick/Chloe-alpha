#!/usr/bin/env python3
"""
Backtest Reflection GPT - Phase 45
Calls GPT to analyze a backtest run's results.
Writes reflection to <run-dir>/reflections.jsonl (separate from live reflections).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.gpt_reflection_template import build_example_prompt_bundle
from tools import backtest_reflect_prep


def call_gpt_api(system_prompt: str, user_prompt: str, model: str = "gpt-4o") -> str:
    """
    Call the OpenAI Chat Completions API with the given SYSTEM and USER prompts.
    Returns the assistant content as a string.
    
    NOTE: This assumes OPENAI_API_KEY is set in the environment.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
    
    client = OpenAI(api_key=api_key)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )
    
    content = response.choices[0].message.content
    return content


def main() -> None:
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Backtest Reflection GPT - Analyze backtest run with GPT"
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="Path to backtest run directory (e.g., reports/backtest/ETHUSDT_1h_<run_id>)",
    )
    
    args = parser.parse_args()
    
    # Resolve run_dir path
    run_dir_path = Path(args.run_dir)
    if not run_dir_path.is_absolute():
        # If path starts with "reports/", strip it first
        run_dir_str = str(run_dir_path)
        if run_dir_str.startswith("reports/"):
            run_dir_str = run_dir_str[8:]  # Remove "reports/" prefix
            run_dir_path = Path(run_dir_str)
        
        # Try relative to REPORTS/backtest first
        backtest_dir = REPORTS / "backtest" / run_dir_path
        if backtest_dir.exists():
            run_dir_path = backtest_dir
        else:
            # Try relative to REPORTS
            run_dir_path = REPORTS / run_dir_path
    
    # Validate directory exists
    if not run_dir_path.exists():
        print(f"❌ Error: Backtest run directory does not exist: {run_dir_path}")
        exit(1)
    
    if not run_dir_path.is_dir():
        print(f"❌ Error: Path is not a directory: {run_dir_path}")
        exit(1)
    
    print("Backtest Reflection GPT - Phase 45")
    print("=" * 60)
    print(f"Run directory: {run_dir_path}")
    print()
    
    # Build reflection input
    print("1. Building reflection input from backtest run...")
    try:
        reflection_data = backtest_reflect_prep.build_backtest_reflection_input(run_dir_path)
        print("   ✅ Reflection input built")
    except ValueError as e:
        print(f"   ❌ Error: {e}")
        exit(1)
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")
        exit(1)
    
    # Build SYSTEM + USER prompts
    print("2. Building GPT prompts...")
    try:
        bundle = build_example_prompt_bundle(reflection_data)
        system_prompt = bundle["system"]
        user_prompt = bundle["user"]
        print("   ✅ Prompts built")
    except Exception as e:
        print(f"   ❌ Error building prompts: {e}")
        exit(1)
    
    # Call GPT
    print("3. Calling GPT API...")
    try:
        gpt_response = call_gpt_api(system_prompt, user_prompt)
        print("   ✅ GPT response received")
    except RuntimeError as e:
        print(f"   ❌ Error: {e}")
        exit(1)
    except Exception as e:
        print(f"   ❌ Error calling GPT: {e}")
        exit(1)
    
    # Append reflection to run directory
    print("4. Writing reflection to run directory...")
    backtest_reflections_path = run_dir_path / "reflections.jsonl"
    
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "reflection_input": reflection_data,
        "prompts": {
            "system": system_prompt,
            "user": user_prompt,
        },
        "gpt_response": gpt_response,
    }
    
    try:
        with backtest_reflections_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        print(f"   ✅ Reflection written to: {backtest_reflections_path}")
    except Exception as e:
        print(f"   ❌ Error writing reflection: {e}")
        exit(1)
    
    # Print summary
    print()
    print("✅ Backtest reflection complete!")
    print(f"   Reflection saved to: {backtest_reflections_path}")
    print()
    print("=== BACKTEST GPT RESPONSE START ===")
    print(gpt_response)
    print("=== BACKTEST GPT RESPONSE END ===")


if __name__ == "__main__":
    main()

