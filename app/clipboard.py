import time
import uuid

import pyperclip
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGHIDEventTap,
)

# macOS virtual keycodes (US layout)
KEY_C = 8
KEY_V = 9
KEY_A = 0
KEY_DELETE = 51

# CGEvent flag masks
_FLAG_CMD = 1 << 20
_FLAG_CTRL = 1 << 18
_FLAG_ALT = 1 << 19
_FLAG_SHIFT = 1 << 17


def press_keys(keycode: int, cmd=False, ctrl=False, alt=False, shift=False):
    """Simulate a keyboard shortcut via Quartz CGEvent."""
    flags = 0
    if cmd:
        flags |= _FLAG_CMD
    if ctrl:
        flags |= _FLAG_CTRL
    if alt:
        flags |= _FLAG_ALT
    if shift:
        flags |= _FLAG_SHIFT

    down = CGEventCreateKeyboardEvent(None, keycode, True)
    up = CGEventCreateKeyboardEvent(None, keycode, False)
    CGEventSetFlags(down, flags)
    CGEventSetFlags(up, flags)
    CGEventPost(kCGHIDEventTap, down)
    CGEventPost(kCGHIDEventTap, up)


def copy_selection() -> str:
    """Smart copy: grab existing selection first, fall back to select-all if nothing highlighted."""
    original_clipboard = pyperclip.paste() or ""
    sentinel = f"__bv_{uuid.uuid4().hex[:8]}__"

    # try copying the current selection (no Cmd+A)
    pyperclip.copy(sentinel)
    time.sleep(0.1)
    press_keys(KEY_C, cmd=True)

    text = sentinel
    for _ in range(30):
        time.sleep(0.08)
        text = pyperclip.paste() or ""
        if text != sentinel:
            break

    # if nothing was selected, fall back to select-all
    if text == sentinel:
        press_keys(KEY_A, cmd=True)
        time.sleep(0.2)
        press_keys(KEY_C, cmd=True)

        for _ in range(40):
            time.sleep(0.08)
            text = pyperclip.paste() or ""
            if text != sentinel:
                break

    pyperclip.copy(original_clipboard)

    if text and text != sentinel:
        return text
    return ""


def _text_has_urls(text: str) -> bool:
    """Quick check if text contains URLs that could cause hyperlink bleeding."""
    return "http://" in text or "https://" in text or "www." in text


def replace_selection(new_text: str, original_text: str = ""):
    """Replace currently selected text by pasting new_text, restore clipboard after.
    If the original contained URLs, deletes selection first to prevent hyperlink bleeding."""
    original_clipboard = pyperclip.paste() or ""

    if original_text and _text_has_urls(original_text):
        # delete selection first to clear link formatting context
        press_keys(KEY_DELETE)
        time.sleep(0.05)

    pyperclip.copy(new_text)
    time.sleep(0.05)
    press_keys(KEY_V, cmd=True)
    time.sleep(0.15)
    pyperclip.copy(original_clipboard)
