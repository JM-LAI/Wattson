#!/usr/bin/env python3
"""
Wattson — macOS menu bar tool for CX message rewriting.

Usage:
    python -m app.main              Launch the menu bar app
    python -m app.main --text "..." CLI mode: rewrite a single message and print
    python -m app.main --help       Show options
"""
import argparse
import sys

from app.config import MODES, MODELS, DEFAULT_STATE


def main():
    parser = argparse.ArgumentParser(
        description="Wattson — CX rewrite assistant — rewrite support messages",
    )
    parser.add_argument(
        "--text", type=str, default=None,
        help="Rewrite this text and print the result (CLI mode, no GUI)",
    )
    parser.add_argument(
        "--mode", type=str, default="Brand Voice",
        choices=MODES,
        help="Rewrite mode (default: Brand Voice)",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help=f"Model ID (default: {DEFAULT_STATE['model']})",
    )
    args = parser.parse_args()

    # accept API key from env (safer than argv which shows in ps)
    import os
    env_key = os.environ.get("LIGHTNING_API_KEY")
    if env_key:
        from app.settings import set_api_key
        set_api_key(env_key)

    # CLI mode: single rewrite
    if args.text:
        from app.prompts import ensure_rules_dir
        ensure_rules_dir()

        model = args.model or DEFAULT_STATE["model"]
        from app.llm import rewrite
        try:
            result = rewrite(args.text, args.mode, model)
            print(result)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # GUI mode: launch menu bar app
    from app.prompts import ensure_rules_dir
    ensure_rules_dir()

    from app.tray import WattsonApp
    WattsonApp().run()


if __name__ == "__main__":
    main()
