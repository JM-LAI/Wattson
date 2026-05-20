"""
Rich UI components: hotkey recorder, preview window, notifications, onboarding.
Uses pyobjc for native macOS panels beyond what rumps provides.
"""
import subprocess
import threading
import time

import pyperclip
import rumps

from app.config import APP_NAME
from app.settings import log


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def notify_success(mode: str, original_words: int, new_words: int):
    rumps.notification(
        title=APP_NAME,
        subtitle=mode,
        message=f"{original_words} → {new_words} words",
    )


def notify_error(message: str):
    rumps.notification(
        title=APP_NAME,
        subtitle="Rewrite failed",
        message=str(message)[:200],
    )


# ---------------------------------------------------------------------------
# Sound
# ---------------------------------------------------------------------------

def play_sound(path: str):
    """Play a system sound in the background."""
    try:
        subprocess.Popen(
            ["afplay", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Hotkey Recorder
# ---------------------------------------------------------------------------

def record_hotkey(title: str, current: str) -> str | None:
    """
    Show a dialog asking the user to press a hotkey combo.

    Uses a polling approach with rumps.Window since we can't do true
    NSEvent monitoring from a rumps context without blocking. Falls back
    to a text-entry dialog where the user types the combo.

    Returns pynput-format string like '<cmd>+<ctrl>+g' or None if cancelled.
    """
    win = rumps.Window(
        message=(
            f"Current: {_pretty(current)}\n\n"
            "Type your new hotkey combo using this format:\n"
            "cmd+ctrl+g  or  cmd+alt+shift+r\n\n"
            "Available modifiers: cmd, ctrl, alt, shift\n"
            "Then any single letter key."
        ),
        title=title,
        default_text=current.replace("<", "").replace(">", ""),
        ok="Save",
        cancel="Cancel",
        dimensions=(300, 24),
    )
    response = win.run()
    if response.clicked == 0:
        return None

    raw = response.text.strip().lower()
    if not raw:
        return None

    # normalise to pynput format
    parts = [p.strip() for p in raw.split("+")]
    normalised = []
    has_modifier = False
    has_key = False
    for p in parts:
        if p in ("cmd", "ctrl", "alt", "shift"):
            normalised.append(f"<{p}>")
            has_modifier = True
        elif len(p) == 1 and p.isalpha():
            normalised.append(p)
            has_key = True

    if not has_modifier or not has_key:
        rumps.alert(
            title="Invalid Hotkey",
            message="Need at least one modifier (cmd/ctrl/alt/shift) and one letter key.",
        )
        return None

    result = "+".join(normalised)
    log(f"Hotkey recorded: {result}")
    return result


def _pretty(expr: str) -> str:
    """<cmd>+<ctrl>+g → Cmd+Ctrl+G"""
    parts = expr.split("+")
    out = []
    for p in parts:
        token = p.strip("<>").lower()
        if token in ("cmd", "ctrl", "alt", "shift"):
            out.append(token.capitalize())
        else:
            out.append(token.upper())
    return "+".join(out)


# ---------------------------------------------------------------------------
# Preview Window with Inline Diff
# ---------------------------------------------------------------------------

import objc
from AppKit import NSObject as _NSObject, NSApplication as _NSApp


class _PreviewHandler(_NSObject):
    """Button handler for the preview panel. Defined once at module level to avoid ObjC class redefinition."""

    def doAccept_(self, sender):
        self._result_holder[0] = self._edit_tv.string()
        _NSApp.sharedApplication().stopModal()
        self._panel.close()

    def doCancel_(self, sender):
        self._result_holder[0] = None
        _NSApp.sharedApplication().stopModal()
        self._panel.close()

def _is_dark_mode() -> bool:
    """Check if macOS is using dark appearance."""
    try:
        from AppKit import NSApplication
        app = NSApplication.sharedApplication()
        appearance = app.effectiveAppearance()
        name = appearance.name() if appearance else ""
        return "Dark" in str(name)
    except Exception:
        return False


def _build_diff_attributed_string(original: str, rewritten: str):
    """Build an NSAttributedString with inline diff: red strikethrough for removed, green for added."""
    import difflib
    from AppKit import (
        NSMutableAttributedString, NSAttributedString, NSFont, NSColor,
        NSForegroundColorAttributeName, NSStrikethroughStyleAttributeName,
        NSUnderlineStyleSingle, NSFontAttributeName,
        NSBackgroundColorAttributeName,
    )

    dark = _is_dark_mode()
    font = NSFont.fontWithName_size_("Menlo", 13.0) or NSFont.systemFontOfSize_(13.0)

    if dark:
        base_color = NSColor.colorWithRed_green_blue_alpha_(0.9, 0.9, 0.9, 1.0)
        removed_fg = NSColor.colorWithRed_green_blue_alpha_(1.0, 0.55, 0.55, 1.0)
        removed_bg = NSColor.colorWithRed_green_blue_alpha_(0.4, 0.1, 0.1, 1.0)
        added_fg = NSColor.colorWithRed_green_blue_alpha_(0.55, 1.0, 0.55, 1.0)
        added_bg = NSColor.colorWithRed_green_blue_alpha_(0.1, 0.35, 0.1, 1.0)
    else:
        base_color = NSColor.colorWithRed_green_blue_alpha_(0.1, 0.1, 0.1, 1.0)
        removed_fg = NSColor.colorWithRed_green_blue_alpha_(0.8, 0.2, 0.2, 1.0)
        removed_bg = NSColor.colorWithRed_green_blue_alpha_(1.0, 0.9, 0.9, 1.0)
        added_fg = NSColor.colorWithRed_green_blue_alpha_(0.1, 0.5, 0.1, 1.0)
        added_bg = NSColor.colorWithRed_green_blue_alpha_(0.9, 1.0, 0.9, 1.0)

    base_attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: base_color}

    removed_attrs = {
        NSFontAttributeName: font,
        NSForegroundColorAttributeName: removed_fg,
        NSStrikethroughStyleAttributeName: NSUnderlineStyleSingle,
        NSBackgroundColorAttributeName: removed_bg,
    }
    added_attrs = {
        NSFontAttributeName: font,
        NSForegroundColorAttributeName: added_fg,
        NSBackgroundColorAttributeName: added_bg,
    }

    result = NSMutableAttributedString.alloc().init()
    sm = difflib.SequenceMatcher(None, original.split(), rewritten.split())

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            text = " ".join(original.split()[i1:i2]) + " "
            chunk = NSAttributedString.alloc().initWithString_attributes_(text, base_attrs)
            result.appendAttributedString_(chunk)
        elif tag == "replace":
            old_text = " ".join(original.split()[i1:i2]) + " "
            new_text = " ".join(rewritten.split()[j1:j2]) + " "
            old_chunk = NSAttributedString.alloc().initWithString_attributes_(old_text, removed_attrs)
            new_chunk = NSAttributedString.alloc().initWithString_attributes_(new_text, added_attrs)
            result.appendAttributedString_(old_chunk)
            result.appendAttributedString_(new_chunk)
        elif tag == "delete":
            old_text = " ".join(original.split()[i1:i2]) + " "
            old_chunk = NSAttributedString.alloc().initWithString_attributes_(old_text, removed_attrs)
            result.appendAttributedString_(old_chunk)
        elif tag == "insert":
            new_text = " ".join(rewritten.split()[j1:j2]) + " "
            new_chunk = NSAttributedString.alloc().initWithString_attributes_(new_text, added_attrs)
            result.appendAttributedString_(new_chunk)

    return result


def show_preview(original: str, rewritten: str) -> str | None:
    """
    Show a native preview panel with inline diff (red strikethrough / green highlight)
    and an editable field for the rewritten text.

    Returns the (possibly edited) rewritten text if accepted, None if cancelled.
    """
    from AppKit import (
        NSPanel, NSTextField, NSTextView, NSScrollView, NSButton,
        NSFont, NSApplication, NSFloatingWindowLevel,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSBackingStoreBuffered, NSBezelStyleRounded,
        NSMakeRect,
    )

    orig_words = len(original.split())
    new_words = len(rewritten.split())

    panel_w, panel_h = 620, 520
    padding = 16

    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(200, 200, panel_w, panel_h),
        NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
        NSBackingStoreBuffered,
        False,
    )
    panel.setTitle_(f"Preview Rewrite — {orig_words} → {new_words} words")
    panel.setLevel_(NSFloatingWindowLevel)
    content = panel.contentView()

    y = panel_h - 40

    # diff label
    diff_label = NSTextField.labelWithString_("Diff (red = removed, green = added):")
    diff_label.setFrame_(NSMakeRect(padding, y, panel_w - padding * 2, 20))
    diff_label.setFont_(NSFont.boldSystemFontOfSize_(12.0))
    content.addSubview_(diff_label)
    y -= 180

    # diff scroll view with attributed string
    from AppKit import NSColor
    dark = _is_dark_mode()
    diff_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(padding, y, panel_w - padding * 2, 170))
    diff_scroll.setHasVerticalScroller_(True)
    diff_scroll.setBorderType_(1)
    diff_tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, panel_w - padding * 2 - 20, 170))
    diff_tv.setEditable_(False)
    diff_tv.setRichText_(True)
    if dark:
        diff_tv.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(0.15, 0.15, 0.15, 1.0))
    attr_str = _build_diff_attributed_string(original, rewritten)
    diff_tv.textStorage().setAttributedString_(attr_str)
    diff_scroll.setDocumentView_(diff_tv)
    content.addSubview_(diff_scroll)
    y -= 30

    # editable label
    edit_label = NSTextField.labelWithString_("Edit the rewrite if needed:")
    edit_label.setFrame_(NSMakeRect(padding, y, panel_w - padding * 2, 20))
    edit_label.setFont_(NSFont.boldSystemFontOfSize_(12.0))
    content.addSubview_(edit_label)
    y -= 180

    # editable text view
    edit_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(padding, y, panel_w - padding * 2, 170))
    edit_scroll.setHasVerticalScroller_(True)
    edit_scroll.setBorderType_(1)
    edit_tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, panel_w - padding * 2 - 20, 170))
    edit_tv.setEditable_(True)
    edit_tv.setFont_(NSFont.fontWithName_size_("Menlo", 13.0) or NSFont.systemFontOfSize_(13.0))
    if dark:
        edit_tv.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(0.18, 0.18, 0.18, 1.0))
        edit_tv.setTextColor_(NSColor.colorWithRed_green_blue_alpha_(0.92, 0.92, 0.92, 1.0))
    edit_tv.setString_(rewritten)
    edit_scroll.setDocumentView_(edit_tv)
    content.addSubview_(edit_scroll)
    y -= 40

    # buttons
    _result_holder = [None]
    handler = _PreviewHandler.alloc().init()
    handler._result_holder = _result_holder
    handler._edit_tv = edit_tv
    handler._panel = panel

    accept_btn = NSButton.alloc().initWithFrame_(NSMakeRect(panel_w - padding - 100, padding, 90, 32))
    accept_btn.setTitle_("Accept")
    accept_btn.setBezelStyle_(NSBezelStyleRounded)
    accept_btn.setTarget_(handler)
    accept_btn.setAction_(objc.selector(handler.doAccept_, signature=b"v@:@"))
    accept_btn.setKeyEquivalent_("\r")
    content.addSubview_(accept_btn)

    cancel_btn = NSButton.alloc().initWithFrame_(NSMakeRect(panel_w - padding - 200, padding, 90, 32))
    cancel_btn.setTitle_("Cancel")
    cancel_btn.setBezelStyle_(NSBezelStyleRounded)
    cancel_btn.setTarget_(handler)
    cancel_btn.setAction_(objc.selector(handler.doCancel_, signature=b"v@:@"))
    cancel_btn.setKeyEquivalent_("\x1b")
    content.addSubview_(cancel_btn)

    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    panel.makeKeyAndOrderFront_(None)
    NSApplication.sharedApplication().runModalForWindow_(panel)

    if _result_holder[0] is not None:
        return _result_holder[0].strip()
    return None


# ---------------------------------------------------------------------------
# First-Run Onboarding
# ---------------------------------------------------------------------------


def _bring_to_front():
    """Bring our app to the front so dialogs are visible."""
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass


def _copy_to_clipboard(text: str):
    """Copy text to clipboard with fallback to pbcopy if pyperclip fails."""
    try:
        pyperclip.copy(text)
        if pyperclip.paste() == text:
            return
    except Exception:
        pass
    # fallback: use pbcopy directly
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"))
    except Exception:
        pass


def run_onboarding() -> bool:
    """
    Walk the user through initial setup.
    Returns True if completed, False if cancelled at any step.
    """
    from app.settings import set_api_key, get_api_key
    from app.llm import call_model
    from app.prompts import ensure_rules_dir

    _bring_to_front()

    # step 1: welcome
    result = rumps.alert(
        title="Welcome to Wattson",
        message=(
            "This tool rewrites your support messages to match the team's brand voice.\n\n"
            "Select text anywhere → press Cmd+Ctrl+G → text gets rewritten.\n\n"
            "Let's get you set up. You'll need your Lightning AI API key."
        ),
        ok="Let's go",
        cancel="Skip Setup",
    )
    if result == 0:
        return False

    # step 2: API key
    win = rumps.Window(
        message="Paste your Lightning AI API key (starts with sk-lit-...):",
        title="API Key",
        default_text="",
        ok="Save",
        cancel="Skip",
        dimensions=(400, 24),
    )
    resp = win.run()
    if resp.clicked == 1 and resp.text.strip():
        set_api_key(resp.text.strip())
    elif resp.clicked == 0:
        return False

    # step 3: test rewrite (if they entered a key)
    api_key = get_api_key()
    if api_key:
        result = rumps.alert(
            title="Test Connection",
            message="Want to test a quick rewrite to make sure everything works?",
            ok="Test Now",
            cancel="Skip",
        )
        if result == 1:
            try:
                test_input = "hi we see ur issue and are looking into it will get back to u"
                from app.config import DEFAULT_MODEL
                from app.prompts import get_system_prompt
                test_output = call_model(test_input, DEFAULT_MODEL, get_system_prompt("Brand Voice"))
                rumps.alert(
                    title="It works!",
                    message=f"Input: {test_input}\n\nOutput: {test_output}",
                )
            except Exception as e:
                rumps.alert(
                    title="Connection Failed",
                    message=f"Error: {e}\n\nCheck your API key and try again from Settings.",
                )

    # step 4: auto-start
    import subprocess

    result = rumps.alert(
        title="Run at Login?",
        message=(
            "Want Wattson to start automatically when you log in?\n\n"
            "It'll always be in your menu bar — no need to launch manually."
        ),
        ok="Yes, auto-start",
        cancel="No, I'll launch it manually",
    )
    if result == 1:
        from app.settings import read_state, write_state
        state = read_state()
        state["auto_start"] = True
        write_state(state)

    # step 5: permissions — trigger native macOS prompt
    _bring_to_front()
    rumps.alert(
        title="Permissions",
        message=(
            "Wattson needs Accessibility and Input Monitoring permissions "
            "so it can read and replace selected text.\n\n"
            "macOS will open System Settings next.\n"
            "Find 'Wattson' in the list and toggle it ON.\n\n"
            "You'll need to do this for both Accessibility and Input Monitoring."
        ),
        ok="Open Settings",
    )

    # trigger the native TCC prompt + open the settings pane
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        from Foundation import NSDictionary
        opts = NSDictionary.dictionaryWithObject_forKey_(True, "AXTrustedCheckOptionPrompt")
        AXIsProcessTrustedWithOptions(opts)
    except ImportError:
        pass

    subprocess.Popen([
        "open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    ])
    time.sleep(1.0)
    _bring_to_front()
    rumps.alert(
        title="Accessibility",
        message=(
            "Toggle Wattson ON in the Accessibility list.\n\n"
            "If you don't see it, click + and find Wattson.app "
            "in your Applications folder.\n\n"
            "Click OK when done."
        ),
    )

    subprocess.Popen([
        "open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
    ])
    time.sleep(1.0)
    _bring_to_front()
    rumps.alert(
        title="Input Monitoring",
        message=(
            "Now do the same for Input Monitoring.\n\n"
            "Toggle Wattson ON.\n\n"
            "Click OK when done."
        ),
    )

    # done
    _bring_to_front()
    rumps.alert(
        title="You're All Set!",
        message=(
            "Select text anywhere and press Cmd+Ctrl+G to rewrite.\n\n"
            "Cmd+Ctrl+M cycles between modes.\n"
            "Cmd+Ctrl+Z undoes the last rewrite.\n\n"
            "Edit rules and change settings from the menu bar icon."
        ),
    )

    ensure_rules_dir()
    log("Onboarding completed")
    return True
