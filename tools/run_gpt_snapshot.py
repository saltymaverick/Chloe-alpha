"""
Helper CLI to run a quick GPT snapshot for the dashboard.
"""

from __future__ import annotations

def main() -> None:
    try:
        from engine_alpha.reflect.gpt_reflection import run_once as run_reflection  # type: ignore
    except ImportError:
        from engine_alpha.reflect.gpt_reflection import run_gpt_reflection as run_reflection  # type: ignore

    from engine_alpha.core.governor import run_once as run_governor

    try:
        run_reflection()
    except Exception as exc:  # pragma: no cover - diagnostic script
        print("reflection error:", exc)

    try:
        run_governor()
    except Exception as exc:  # pragma: no cover - diagnostic script
        print("governance error:", exc)

    print("GPT snapshot complete")


if __name__ == "__main__":
    main()

