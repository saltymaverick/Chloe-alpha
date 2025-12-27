#!/usr/bin/env python3
"""
Setup script for GPT Reflection.

Installs dependencies and verifies OpenAI API key configuration.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def check_openai_installed() -> bool:
    """Check if openai package is installed."""
    try:
        import openai
        return True
    except ImportError:
        return False


def install_openai() -> bool:
    """Install openai package."""
    print("Installing openai package...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "openai"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return True
        else:
            print(f"   pip install failed: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print("   Installation timed out")
        return False
    except Exception as e:
        print(f"   Installation error: {e}")
        return False


def check_api_key() -> tuple[bool, str]:
    """
    Check if OPENAI_API_KEY is set.
    
    Returns:
        Tuple of (is_set, key_preview)
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return False, ""
    
    # Show first 8 chars + last 4 chars for verification
    if len(key) > 12:
        preview = f"{key[:8]}...{key[-4:]}"
    else:
        preview = "***" * 4
    
    return True, preview


def check_gpt_client() -> tuple[bool, str]:
    """
    Check if GPT client can initialize.
    
    Returns:
        Tuple of (can_init, error_message)
    """
    try:
        from engine_alpha.core.gpt_client import _get_client
        client = _get_client()
        if client is None:
            return False, "Client initialization returned None"
        return True, ""
    except Exception as e:
        return False, str(e)


def main():
    """Main setup function."""
    import sys
    
    # Check for --auto-install flag
    auto_install = "--auto-install" in sys.argv or "--yes" in sys.argv or "-y" in sys.argv
    
    print("=" * 60)
    print("GPT Reflection Setup")
    print("=" * 60)
    print()
    
    # Check OpenAI package
    print("1. Checking openai package...")
    if check_openai_installed():
        print("   ✅ openai package is installed")
    else:
        print("   ❌ openai package not found")
        if auto_install:
            print("   Installing automatically (--auto-install)...")
            if install_openai():
                print("   ✅ openai package installed successfully")
            else:
                print("   ❌ Failed to install openai package")
                return 1
        else:
            try:
                response = input("   Install openai package? (y/n): ").strip().lower()
                if response == 'y':
                    if install_openai():
                        print("   ✅ openai package installed successfully")
                    else:
                        print("   ❌ Failed to install openai package")
                        return 1
                else:
                    print("   ⚠️  Skipping installation")
                    return 1
            except EOFError:
                print("   ⚠️  Non-interactive mode - use --auto-install to install automatically")
                return 1
    
    print()
    
    # Check API key
    print("2. Checking OPENAI_API_KEY...")
    is_set, preview = check_api_key()
    if is_set:
        print(f"   ✅ OPENAI_API_KEY is set ({preview})")
    else:
        print("   ❌ OPENAI_API_KEY is not set")
        print()
        print("   To set it, run:")
        print("   export OPENAI_API_KEY='your-key-here'")
        print()
        print("   Or add it to your shell profile (~/.bashrc, ~/.zshrc, etc.)")
        print("   Or set it in your systemd service EnvironmentFile")
        return 1
    
    print()
    
    # Check GPT client initialization
    print("3. Checking GPT client initialization...")
    can_init, error = check_gpt_client()
    if can_init:
        print("   ✅ GPT client can initialize")
    else:
        print(f"   ❌ GPT client initialization failed: {error}")
        if "OPENAI_API_KEY" in error or "api_key" in error.lower():
            print("   This might be an API key issue")
        return 1
    
    print()
    print("=" * 60)
    print("✅ GPT Reflection setup complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Ensure enable_gpt_reflection is true in config/engine_config.json")
    print("2. Wait for a close event (samples_processed >= 1)")
    print("3. Check engine_alpha/reflect/gpt_reflection.jsonl for results")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

