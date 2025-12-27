import os
import json
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI  # new OpenAI client

from engine_alpha.core.paths import REPORTS
from tools import reflect_prep
from engine_alpha.reflect.gpt_reflection_template import build_example_prompt_bundle


REFLECTION_INPUT_PATH = REPORTS / "reflection_input.json"
REFLECTIONS_LOG_PATH = REPORTS / "reflections.jsonl"


def build_reflection_input() -> dict:
    """
    Build the reflection_data dict directly using the same logic as tools.reflect_prep,
    without shelling out. This ensures we always have fresh data for reflection.
    Includes all fields from reflect_prep.main(), especially filtered_pf.
    """
    now = datetime.now(timezone.utc).isoformat()
    trades_summary = reflect_prep.summarize_recent_trades(max_trades=50)
    council_summary = reflect_prep.summarize_council_perf(max_events=200)
    exit_quality = reflect_prep.summarize_exit_quality(max_trades=200)
    confidence_summary = reflect_prep.summarize_confidence(max_trades=200)
    risk_behavior = reflect_prep.summarize_risk_behavior(max_trades=200)
    loop_health = reflect_prep.load_loop_health()
    activity_block = reflect_prep.build_activity_block()
    
    # Compute filtered PF (meaningful trades only) - CRITICAL for GPT to see real performance
    from engine_alpha.core.paths import REPORTS
    filtered_pf = reflect_prep.summarize_filtered_pf(
        trades_path=REPORTS / "trades.jsonl",
        threshold=0.0002,  # 0.02% cutoff, more generous than pf_doctor_filtered default
        exit_reasons=("tp", "sl"),  # only meaningful exits
        max_trades=None,  # read all trades to ensure we capture all meaningful closes
    )

    reflection_input = {
        "timestamp": now,
        "recent_trades": trades_summary,
        "council_summary": council_summary,
        "exit_quality": exit_quality,
        "confidence_summary": confidence_summary,
        "risk_behavior": risk_behavior,
        "loop_health": loop_health,
        "activity": activity_block,
        "filtered_pf": filtered_pf,  # CRITICAL: GPT needs this to see meaningful trades
    }
    return reflection_input


def append_reflection_log(record: dict) -> None:
    """
    Append a reflection record (input + prompts + GPT response) to reflections.jsonl.
    """
    try:
        REFLECTIONS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REFLECTIONS_LOG_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"[run_reflection_gpt] WARNING: failed to append reflections log: {e}")


def call_gpt_api(system_prompt: str, user_prompt: str, model: str = "gpt-4o") -> str:
    """
    Call the OpenAI Chat Completions API with the given SYSTEM and USER prompts.
    Returns the assistant content as a string.

    NOTE: This assumes OPENAI_API_KEY is set in the environment.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment.")

    # New 1.x client
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


def main():
    # 1) Build reflection input (recent trades, council summary, loop health)
    reflection_data = build_reflection_input()

    # Optionally also save it to reflection_input.json for inspection/debugging
    try:
        REFLECTION_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REFLECTION_INPUT_PATH.write_text(json.dumps(reflection_data, indent=2))
    except Exception as e:
        print(f"[run_reflection_gpt] WARNING: failed to write reflection_input.json: {e}")

    # 2) Build SYSTEM + USER prompt bundle
    bundle = build_example_prompt_bundle(reflection_data)
    system_prompt = bundle["system"]
    user_prompt = bundle["user"]

    print("[run_reflection_gpt] Prepared reflection input and prompts.")
    print("[run_reflection_gpt] Calling GPT...")

    try:
        gpt_response = call_gpt_api(system_prompt, user_prompt)
    except Exception as e:
        print(f"[run_reflection_gpt] ERROR: GPT call failed: {e}")
        return

    # 3) Append to reflections log
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "reflection_input": reflection_data,
        "prompts": {
            "system": system_prompt,
            "user": user_prompt,
        },
        "gpt_response": gpt_response,
    }
    append_reflection_log(record)

    print("[run_reflection_gpt] Reflection recorded to", REFLECTIONS_LOG_PATH)
    print("\n=== GPT RESPONSE (START) ===\n")
    print(gpt_response)
    print("\n=== GPT RESPONSE (END) ===")


if __name__ == "__main__":
    main()
