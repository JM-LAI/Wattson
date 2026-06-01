import json
import os
import subprocess
import time

from app.config import (
    APP_SUPPORT, STATE_PATH, LOG_PATH, DEFAULT_STATE,
    KEYCHAIN_ACCOUNT, KEYCHAIN_API_KEY_SERVICE,
    KEYCHAIN_CONFLUENCE_TOKEN_SERVICE,
)


def log(message: str):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        pass


def read_state() -> dict:
    os.makedirs(APP_SUPPORT, exist_ok=True)
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # only accept known keys to prevent injection of rogue settings
            valid_keys = set(DEFAULT_STATE.keys())
            filtered = {k: v for k, v in saved.items() if k in valid_keys}
            merged = {**DEFAULT_STATE, **filtered}
            # cap and validate history entries
            from app.config import MAX_HISTORY
            history = merged.get("history", [])
            if not isinstance(history, list):
                history = []
            history = [
                e for e in history[:MAX_HISTORY]
                if isinstance(e, dict) and "original" in e and "rewritten" in e
            ]
            merged["history"] = history
            return merged
        except Exception:
            pass
    return dict(DEFAULT_STATE)


def write_state(data: dict):
    os.makedirs(APP_SUPPORT, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.chmod(STATE_PATH, 0o600)


def _keychain_get(service: str) -> str | None:
    """Read a password from macOS Keychain."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password",
             "-a", KEYCHAIN_ACCOUNT, "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _keychain_set(service: str, secret: str):
    """Write a password to macOS Keychain. Overwrites if exists."""
    # delete existing entry first (ignore errors if it doesn't exist)
    subprocess.run(
        ["security", "delete-generic-password",
         "-a", KEYCHAIN_ACCOUNT, "-s", service],
        capture_output=True, timeout=5,
    )
    subprocess.run(
        ["security", "add-generic-password",
         "-a", KEYCHAIN_ACCOUNT, "-s", service, "-w", secret],
        capture_output=True, timeout=5,
    )


def get_api_key() -> str | None:
    return _keychain_get(KEYCHAIN_API_KEY_SERVICE)


def set_api_key(key: str):
    _keychain_set(KEYCHAIN_API_KEY_SERVICE, key)
    log("API key updated in Keychain")


def is_first_run() -> bool:
    return get_api_key() is None


def get_confluence_token() -> str | None:
    return _keychain_get(KEYCHAIN_CONFLUENCE_TOKEN_SERVICE)


def set_confluence_token(token: str):
    _keychain_set(KEYCHAIN_CONFLUENCE_TOKEN_SERVICE, token)
    log("Confluence token updated in Keychain")


def get_confluence_creds() -> tuple[str, str, str] | None:
    """Return (base_url, email, token) if all are set, else None."""
    state = read_state()
    base_url = (state.get("confluence_base_url") or "").strip().rstrip("/")
    email = (state.get("confluence_email") or "").strip()
    token = get_confluence_token()
    if base_url and email and token:
        return base_url, email, token
    return None


def set_confluence_config(base_url: str, email: str, token: str):
    """Save Confluence base URL + email to state, token to Keychain."""
    state = read_state()
    state["confluence_base_url"] = base_url.strip().rstrip("/")
    state["confluence_email"] = email.strip()
    write_state(state)
    set_confluence_token(token.strip())


def add_history_entry(state: dict, original: str, rewritten: str):
    """Append a rewrite to history, cap at MAX_HISTORY. Truncates long entries."""
    from app.config import MAX_HISTORY
    # limit stored text to 500 chars to reduce data-at-rest exposure
    max_len = 500
    entry = {
        "original": original[:max_len],
        "rewritten": rewritten[:max_len],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    history = state.get("history", [])
    history.insert(0, entry)
    state["history"] = history[:MAX_HISTORY]
    write_state(state)
