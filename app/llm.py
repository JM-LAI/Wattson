import requests

from app.config import CHAT_API_URL, FALLBACK_MODELS
from app.settings import get_api_key, log
from app.prompts import get_system_prompt


def _friendly_error(err: Exception) -> str:
    """Turn raw API errors into something a human can act on."""
    msg = str(err)
    if isinstance(err, requests.exceptions.Timeout):
        return "API timed out — Lightning AI may be slow. Try again in a moment."
    if isinstance(err, requests.exceptions.ConnectionError):
        return "Can't reach Lightning AI — check your internet connection."
    if isinstance(err, requests.exceptions.HTTPError):
        code = getattr(err.response, 'status_code', None)
        if code == 401:
            return "Invalid API key — update it in Settings → API Key."
        if code == 403:
            return "API key doesn't have access — check your Lightning AI account."
        if code == 429:
            return "Rate limited — too many requests. Wait a few seconds and try again."
        if code and code >= 500:
            return f"Lightning AI server error ({code}) — try again in a moment."
        return f"API error ({code}) — {msg[:100]}"
    if "API key not set" in msg:
        return msg
    return f"Rewrite failed: {msg[:150]}"


def _model_display_name(model_id: str) -> str:
    """Get the human-friendly name for a model ID."""
    from app.config import MODELS
    for name, mid in MODELS.items():
        if mid == model_id:
            return name
    return model_id.split("/")[-1]


def _single_attempt(api_key: str, model: str, system_prompt: str, message: str, timeout: int = 30) -> str:
    """Single API call — returns content or raises."""
    resp = requests.post(
        CHAT_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError(f"Unexpected API response: {data}")
    return content.strip().lstrip("\n")


# tracks which model was used (set after successful fallback)
last_fallback_model = None


def call_model(message: str, model: str, system_prompt: str) -> str:
    """Call the Lightning AI API. On timeout, auto-falls back through other models."""
    global last_fallback_model
    last_fallback_model = None

    api_key = get_api_key()
    if not api_key:
        raise ValueError("API key not set — add it in Settings")

    # first try: the user's chosen model (shorter timeout since we have fallbacks)
    try:
        return _single_attempt(api_key, model, system_prompt, message, timeout=20)
    except requests.exceptions.Timeout:
        log(f"{_model_display_name(model)} timed out — trying fallbacks...")
    except Exception as e:
        raise ValueError(_friendly_error(e)) from e

    # fallback: try other models in order, skip the one that just failed
    fallbacks = [m for m in FALLBACK_MODELS if m != model]
    for fallback in fallbacks:
        try:
            log(f"Trying fallback: {_model_display_name(fallback)}...")
            result = _single_attempt(api_key, fallback, system_prompt, message, timeout=15)
            last_fallback_model = fallback
            log(f"Fallback succeeded: {_model_display_name(fallback)}")
            return result
        except requests.exceptions.Timeout:
            log(f"{_model_display_name(fallback)} also timed out")
            continue
        except Exception:
            continue

    raise ValueError(
        f"All models are down — {_model_display_name(model)} and {len(fallbacks)} fallbacks timed out. "
        "Lightning AI may be having an outage."
    )


def rewrite(message: str, mode: str, model: str) -> str:
    """Rewrite a message using the chat completions API with editable local rules."""
    system_prompt = get_system_prompt(mode)
    log(f"Rewriting via {model} (mode: {mode})")
    return call_model(message, model, system_prompt)
