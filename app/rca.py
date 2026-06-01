"""Generate a Root Cause Analysis (RCA) HTML document from incident data.

Takes a Slack channel dump and/or a Rootly/Confluence incident page, feeds them
to the LLM with the RCA prompt, and returns a self-contained HTML document.
"""
import os
import re
import time

import requests

from app.config import RCA_MODEL, RCA_TIMEOUT, FALLBACK_MODELS
from app.settings import get_api_key, log
from app.prompts import get_rca_prompt, RCA_HTML_OVERRIDE
from app.llm import _single_attempt, _model_display_name

RCA_DIR = os.path.expanduser("~/Reports/RCAs")


# patterns that look like shell/remediation commands. Lightning's WAF rejects
# these as possible injection attacks, and they don't belong in a customer-facing
# RCA anyway — so we swap them for a neutral marker before sending.
_COMMAND_PATTERNS = [
    r"`[^`]*`",                                   # inline code/backticks
    r"(?m)^\s*(sudo\s+)?(perl|pdsh|sed|awk|ssh|scp|rsync|curl|wget|bash|sh|kubectl|systemctl|journalctl|docker|rm|chmod|chown|mount|umount|dd|mkfs|iptables)\b.*$",
    r"for\s+\w+\s+in\b.*?done",                   # for-loops
    r"s/[^/]*/[^/]*/[a-z]*",                      # sed/perl substitutions
    r"-pi\s+-e\b.*",                              # perl in-place edits
]


def _sanitize_for_waf(text: str) -> str:
    """Replace shell-command-like content so it (a) passes Lightning's WAF and
    (b) stays out of the customer-facing output. Narrative around it is kept."""
    if not text:
        return text
    out = text
    for pat in _COMMAND_PATTERNS:
        out = re.sub(pat, "[internal remediation command omitted]", out, flags=re.IGNORECASE | re.DOTALL)
    return out


def _build_user_message(slack_dump: str, rootly_text: str,
                        incident_title: str = "", reported_by: str = "") -> str:
    """Assemble the raw incident data into a single user message for the LLM."""
    slack_dump = _sanitize_for_waf(slack_dump)
    rootly_text = _sanitize_for_waf(rootly_text)
    parts = []
    if incident_title.strip():
        parts.append(f"INCIDENT TITLE (use this): {incident_title.strip()}")
    if reported_by.strip():
        parts.append(f"REPORTED BY (use this): {reported_by.strip()}")
    if rootly_text.strip():
        parts.append("=== ROOTLY / CONFLUENCE INCIDENT PAGE ===\n" + rootly_text.strip())
    if slack_dump.strip():
        parts.append("=== SLACK CHANNEL DUMP ===\n" + slack_dump.strip())
    parts.append(
        "Build the RCA HTML document from the data above. "
        "Remember: times in PST, never invent facts, output only HTML."
    )
    return "\n\n".join(parts)


def generate_rca(slack_dump: str = "", rootly_text: str = "",
                 incident_title: str = "", reported_by: str = "", fmt: str = "md") -> str:
    """Generate the RCA (Markdown by default, HTML if fmt='html').

    Raises ValueError with a friendly message on failure.
    """
    if not slack_dump.strip() and not rootly_text.strip():
        raise ValueError("Need at least a Slack dump or a Rootly/Confluence page to work from.")

    api_key = get_api_key()
    if not api_key:
        raise ValueError("API key not set — add it in Settings → API Key.")

    system_prompt = get_rca_prompt()
    if fmt == "html":
        system_prompt = system_prompt + RCA_HTML_OVERRIDE
    message = _build_user_message(slack_dump, rootly_text, incident_title, reported_by)

    # try the capable RCA model first, then fall back through the rest
    models = [RCA_MODEL] + [m for m in FALLBACK_MODELS if m != RCA_MODEL]
    last_err = None
    for model in models:
        try:
            log(f"Generating RCA ({fmt}) via {_model_display_name(model)}...")
            out = _single_attempt(api_key, model, system_prompt, message, timeout=RCA_TIMEOUT)
            out = _clean_output(out)
            log(f"RCA generated via {_model_display_name(model)} ({len(out)} chars)")
            return out
        except requests.exceptions.Timeout:
            log(f"{_model_display_name(model)} timed out generating RCA — trying next...")
            last_err = "timeout"
            continue
        except requests.exceptions.HTTPError as e:
            code = getattr(e.response, "status_code", None)
            body = getattr(e.response, "text", "") or ""
            if code == 403 and ("<html" in body.lower() or "<!doctype" in body.lower()):
                # gateway/WAF block — same for every model, no point retrying
                raise ValueError(
                    "Lightning's firewall blocked the request — the incident text likely "
                    "contains content flagged as unsafe (e.g. raw commands). Try removing "
                    "command blocks from the input and generate again."
                ) from e
            log(f"{_model_display_name(model)} failed generating RCA: {e}")
            last_err = e
            continue
        except Exception as e:
            log(f"{_model_display_name(model)} failed generating RCA: {e}")
            last_err = e
            continue

    if last_err == "timeout":
        raise ValueError("All models timed out generating the RCA — Lightning AI may be slow. Try again.")
    raise ValueError(f"Couldn't generate RCA: {str(last_err)[:150]}")


def _clean_output(text: str) -> str:
    """Strip any stray markdown/html code fences the model might wrap the doc in."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t.strip()


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
    return slug[:60] or "rca"


def save_rca(content: str, incident_id: str = "", ext: str = "md") -> str:
    """Write the RCA to ~/Reports/RCAs/ and return the path."""
    os.makedirs(RCA_DIR, exist_ok=True)
    os.chmod(RCA_DIR, 0o700)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = _slugify(incident_id) if incident_id else "rca"
    name = f"{base}-{stamp}.{ext}"
    path = os.path.join(RCA_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(path, 0o600)
    log(f"RCA saved to {path}")
    return path
