"""Fetch Confluence/Rootly incident pages via the Atlassian Cloud REST API.

Uses a stored API token (Basic auth with email:token). This is optional —
if no token is configured or the fetch fails, the UI falls back to manual paste.
"""
import base64
import re

import requests

from app.settings import get_confluence_creds, log


class ConfluenceError(Exception):
    """Raised when we can't fetch a page — caller should fall back to paste."""
    pass


def parse_page_id(url: str) -> str:
    """Pull the page ID out of a Confluence URL.

    Handles the common formats:
      .../wiki/spaces/IM/pages/448299016/Some+Title  -> 448299016
      .../wiki/x/Fc1bBw                               -> Fc1bBw (tiny link)
    """
    url = url.strip()
    # standard /pages/<id>/ form
    m = re.search(r"/pages/(\d+)", url)
    if m:
        return m.group(1)
    # tiny link /x/<id>
    m = re.search(r"/wiki/x/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    # bare numeric id pasted on its own
    if url.isdigit():
        return url
    raise ConfluenceError(
        "Couldn't find a page ID in that URL. Paste the full Confluence page URL "
        "(the one with /pages/<number>/ in it)."
    )


def _auth_header(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def fetch_page(url: str) -> str:
    """Fetch a Confluence page and return its body as readable text.

    Raises ConfluenceError on any problem so the caller can fall back to paste.
    """
    creds = get_confluence_creds()
    if not creds:
        raise ConfluenceError(
            "No Confluence token set. Add one in Settings → Set Confluence Token, "
            "or just paste the page content below."
        )
    base_url, email, token = creds
    page_id = parse_page_id(url)

    api = f"{base_url}/wiki/api/v2/pages/{page_id}"
    try:
        resp = requests.get(
            api,
            headers={
                "Authorization": _auth_header(email, token),
                "Accept": "application/json",
            },
            params={"body-format": "storage"},
            timeout=30,
        )
    except requests.exceptions.ConnectionError as e:
        raise ConfluenceError(f"Can't reach {base_url} — check your connection.") from e
    except requests.exceptions.Timeout as e:
        raise ConfluenceError("Confluence request timed out — try again.") from e

    if resp.status_code == 401:
        raise ConfluenceError("Confluence auth failed (401) — check your email and token.")
    if resp.status_code == 403:
        raise ConfluenceError("Confluence access denied (403) — token lacks read access to this page.")
    if resp.status_code == 404:
        raise ConfluenceError("Page not found (404) — double-check the URL.")
    if resp.status_code >= 400:
        raise ConfluenceError(f"Confluence error ({resp.status_code}).")

    try:
        data = resp.json()
        title = data.get("title", "")
        body = data.get("body", {}).get("storage", {}).get("value", "")
    except (ValueError, KeyError, AttributeError) as e:
        raise ConfluenceError("Unexpected Confluence response format.") from e

    text = _storage_to_text(body)
    log(f"Fetched Confluence page {page_id} ({len(text)} chars)")
    return f"# {title}\n\n{text}" if title else text


def fetch_page_full(url: str) -> dict:
    """Like fetch_page but returns structured bits for autofill.

    Returns {"title": ..., "author": ..., "text": ...}. 'text' is the same
    body string fetch_page would return (with the title heading prepended).
    """
    creds = get_confluence_creds()
    if not creds:
        raise ConfluenceError(
            "No Confluence token set. Add one in Settings → Set Confluence Token, "
            "or just paste the page content below."
        )
    base_url, email, token = creds
    page_id = parse_page_id(url)

    api = f"{base_url}/wiki/api/v2/pages/{page_id}"
    try:
        resp = requests.get(
            api,
            headers={
                "Authorization": _auth_header(email, token),
                "Accept": "application/json",
            },
            params={"body-format": "storage"},
            timeout=30,
        )
    except requests.exceptions.ConnectionError as e:
        raise ConfluenceError(f"Can't reach {base_url} — check your connection.") from e
    except requests.exceptions.Timeout as e:
        raise ConfluenceError("Confluence request timed out — try again.") from e

    if resp.status_code == 401:
        raise ConfluenceError("Confluence auth failed (401) — check your email and token.")
    if resp.status_code == 403:
        raise ConfluenceError("Confluence access denied (403) — token lacks read access to this page.")
    if resp.status_code == 404:
        raise ConfluenceError("Page not found (404) — double-check the URL.")
    if resp.status_code >= 400:
        raise ConfluenceError(f"Confluence error ({resp.status_code}).")

    try:
        data = resp.json()
        title = data.get("title", "")
        body = data.get("body", {}).get("storage", {}).get("value", "")
    except (ValueError, KeyError, AttributeError) as e:
        raise ConfluenceError("Unexpected Confluence response format.") from e

    text = _storage_to_text(body)
    full = f"# {title}\n\n{text}" if title else text
    log(f"Fetched Confluence page {page_id} ({len(text)} chars)")
    return {"title": title, "author": _extract_author(text), "text": full}


def _extract_author(text: str) -> str:
    """Best-effort pull of the reporter/author name from the page body."""
    for pat in (r"Author:\s*(.+)", r"Reported by:\s*(.+)", r"Reporter:\s*(.+)"):
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            name = m.group(1).strip().splitlines()[0].strip()
            # drop trailing junk like a following field on the same line
            name = re.split(r"\s{2,}|\s*\|\s*", name)[0].strip()
            if name:
                return name
    return ""


def _storage_to_text(storage_html: str) -> str:
    """Strip Confluence storage-format XHTML down to readable text.

    Keeps table rows as pipe-delimited lines so the timeline survives.
    """
    if not storage_html:
        return ""
    s = storage_html
    # turn table cells/rows into pipe-delimited text before stripping tags
    s = re.sub(r"</t[dh]>\s*<t[dh][^>]*>", " | ", s, flags=re.IGNORECASE)
    s = re.sub(r"<tr[^>]*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</p>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</h[1-6]>", "\n", s, flags=re.IGNORECASE)
    # drop all remaining tags
    s = re.sub(r"<[^>]+>", "", s)
    # kill Confluence status-macro noise (renders as e.g. "trueGreyLekan" → "Lekan")
    s = re.sub(r"\btrue(Grey|Gray|Red|Blue|Green|Yellow|Purple|Teal|Pink)", "", s)
    # decode the handful of entities Confluence emits
    for ent, ch in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        s = s.replace(ent, ch)
    # collapse excess blank lines
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
