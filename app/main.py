#!/usr/bin/env python3
"""
Wattson — macOS menu bar tool for CX message rewriting.

Usage:
    python -m app.main              Launch the menu bar app
    python -m app.main --text "..." CLI mode: rewrite a single message and print
    python -m app.main --rca ...    CLI mode: generate an RCA from incident data
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
    parser.add_argument(
        "--rca", action="store_true",
        help="Generate an RCA HTML document (CLI mode, no GUI)",
    )
    parser.add_argument("--slack-file", type=str, default=None,
                        help="Path to a Slack channel dump for --rca")
    parser.add_argument("--rootly-url", type=str, default=None,
                        help="Rootly/Confluence page URL for --rca (needs a stored token)")
    parser.add_argument("--rootly-file", type=str, default=None,
                        help="Path to a pasted Rootly/Confluence page for --rca")
    parser.add_argument("--title", type=str, default="",
                        help="Incident title for --rca")
    parser.add_argument("--reported-by", type=str, default="",
                        help="Reporter name for --rca")
    parser.add_argument("--format", type=str, default="md", choices=["md", "html"],
                        help="RCA output format (default: md)")
    parser.add_argument("--out", type=str, default=None,
                        help="Write RCA to this path (default: prints to stdout)")
    args = parser.parse_args()

    # accept API key from env (safer than argv which shows in ps)
    import os
    env_key = os.environ.get("LIGHTNING_API_KEY")
    if env_key:
        from app.settings import set_api_key
        set_api_key(env_key)

    # CLI mode: RCA generation
    if args.rca:
        from app.prompts import ensure_rules_dir
        ensure_rules_dir()
        _run_rca_cli(args)
        return

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


def _run_rca_cli(args):
    """Generate an RCA from CLI args and print/save the HTML."""
    slack = ""
    rootly = ""

    if args.slack_file:
        try:
            with open(args.slack_file, "r", encoding="utf-8") as f:
                slack = f.read()
        except OSError as e:
            print(f"Error reading slack file: {e}", file=sys.stderr)
            sys.exit(1)

    if args.rootly_file:
        try:
            with open(args.rootly_file, "r", encoding="utf-8") as f:
                rootly = f.read()
        except OSError as e:
            print(f"Error reading rootly file: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.rootly_url:
        from app.confluence import fetch_page, ConfluenceError
        try:
            rootly = fetch_page(args.rootly_url)
        except ConfluenceError as e:
            print(f"Error fetching Rootly page: {e}", file=sys.stderr)
            sys.exit(1)

    from app.rca import generate_rca
    try:
        out = generate_rca(slack, rootly, args.title, args.reported_by, fmt=args.format)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"RCA written to {args.out}")
        except OSError as e:
            print(f"Error writing output: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(out)


if __name__ == "__main__":
    main()
