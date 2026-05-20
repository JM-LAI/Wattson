#!/usr/bin/env bash
# wattson — launch the Wattson menu bar app
# Usage:
#   ./wattson.sh                  (launch GUI, detaches from terminal)
#   ./wattson.sh --text "msg"     (CLI mode, runs in foreground)
#   ./wattson.sh --help           (show options)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "No virtual environment found at ${SCRIPT_DIR}/.venv"
    echo "Run install.sh first:  ./install.sh"
    exit 1
fi

# CLI mode runs in foreground so you can see output
if [[ "${1:-}" == "--text" || "${1:-}" == "--help" || "${1:-}" == "--version" ]]; then
    exec "$VENV_PYTHON" -m app.main "$@"
fi

# check for existing instance
EXISTING_PID=$(pgrep -f "python.*-m app.main" 2>/dev/null | head -1 || true)
if [[ -n "$EXISTING_PID" && "$EXISTING_PID" != "$$" ]]; then
    if [[ -t 0 ]]; then
        # interactive terminal — ask the user
        echo "Wattson is already running (PID ${EXISTING_PID})."
        printf "Kill it and restart? (y/n): "
        read -r yn
        if [[ "$yn" =~ ^[Yy] ]]; then
            kill "$EXISTING_PID" 2>/dev/null || true
            sleep 0.5
        else
            echo "Leaving existing instance running."
            exit 0
        fi
    else
        # non-interactive (LaunchAgent) — kill silently and restart
        kill "$EXISTING_PID" 2>/dev/null || true
        sleep 0.5
    fi
fi

# non-interactive (LaunchAgent): run in foreground so launchd manages the process
if [[ ! -t 0 ]]; then
    exec "$VENV_PYTHON" -m app.main "$@"
fi

# interactive terminal: detach so closing the terminal doesn't kill the app
nohup "$VENV_PYTHON" -m app.main "$@" &>/dev/null &
disown
echo "Wattson running in background (PID $!). Check your menu bar."
