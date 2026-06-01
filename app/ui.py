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
# RCA Generator Window
# ---------------------------------------------------------------------------

class _RCAHandler(_NSObject):
    """Button handlers for the RCA generator window. Module-level to avoid ObjC redefinition."""

    def _set_status(self, msg):
        from app.tray import _run_on_main_thread
        _run_on_main_thread(self._status.setStringValue_, msg)

    def doFetch_(self, sender):
        try:
            url = self._url_field.stringValue().strip()
        except Exception as e:
            log(f"RCA fetch click error: {e}")
            return
        if not url:
            self._set_status("Enter a Rootly/Confluence URL first, or just paste below.")
            return
        log("RCA: fetch clicked")
        self._set_status("Fetching page…")

        def work():
            from app.confluence import fetch_page_full, ConfluenceError
            from app.tray import _run_on_main_thread
            try:
                info = fetch_page_full(url)
                _run_on_main_thread(self._rootly_tv.setString_, info["text"])
                # autofill title/reporter from the page if the user left them blank
                if info.get("title") and not self._title_field.stringValue().strip():
                    _run_on_main_thread(self._title_field.setStringValue_, info["title"])
                if info.get("author") and not self._reporter_field.stringValue().strip():
                    _run_on_main_thread(self._reporter_field.setStringValue_, info["author"])
                self._set_status(f"Fetched page ({len(info['text'])} chars). Autofilled what we could.")
            except ConfluenceError as e:
                self._set_status(str(e))
            except Exception as e:
                log(f"RCA fetch failed: {e}")
                self._set_status(f"Fetch failed: {str(e)[:120]}")

        threading.Thread(target=work, daemon=True).start()

    def doGenerate_(self, sender):
        log("RCA: generate clicked")
        try:
            slack = self._slack_tv.string()
            rootly = self._rootly_tv.string()
            title = self._title_field.stringValue()
            reported_by = self._reporter_field.stringValue()
            also_html = self._html_checkbox.state() == 1
        except Exception as e:
            log(f"RCA generate click error: {e}")
            self._set_status(f"Couldn't read the inputs: {str(e)[:120]}")
            return
        if not slack.strip() and not rootly.strip():
            self._set_status("Paste a Slack dump and/or fetch a Rootly page first.")
            return
        self._set_status("Generating RCA… this can take up to a couple of minutes.")

        def work():
            from app.rca import generate_rca, save_rca
            try:
                md = generate_rca(slack, rootly, title, reported_by, fmt="md")
                md_path = save_rca(md, title, ext="md")
                _copy_to_clipboard(md)
                msg = f"Done. Markdown saved + copied to clipboard.\n{md_path}"
                if also_html:
                    html = generate_rca(slack, rootly, title, reported_by, fmt="html")
                    html_path = save_rca(html, title, ext="html")
                    subprocess.Popen(["open", html_path])
                    msg += f"\nHTML also saved + opened: {html_path}"
                else:
                    subprocess.Popen(["open", "-t", md_path])
                self._set_status(msg)
            except Exception as e:
                log(f"RCA generate failed: {e}")
                self._set_status(f"Failed: {str(e)[:160]}")

        threading.Thread(target=work, daemon=True).start()

    def doClose_(self, sender):
        # hide, don't destroy — keeps whatever's typed for next time
        self._panel.orderOut_(None)


# keep references so the window/handler aren't garbage collected while open
_rca_window_ref = None
_rca_handler_ref = None
_edit_menu_installed = False
_key_monitor_ref = None


def _install_paste_monitor():
    """Make Cmd+C/V/X/A/Z work in our text boxes.

    The Edit menu route is flaky for LSUIElement apps, so we also drop in a
    local key-event monitor that fires the standard editing selectors straight
    at the responder chain. Belt and braces.
    """
    global _key_monitor_ref
    if _key_monitor_ref is not None:
        return
    from AppKit import (
        NSEvent, NSEventMaskKeyDown, NSEventModifierFlagCommand, NSApplication,
    )

    sel_map = {"x": "cut:", "c": "copy:", "v": "paste:", "a": "selectAll:", "z": "undo:"}

    def handler(event):
        try:
            if event.modifierFlags() & NSEventModifierFlagCommand:
                ch = (event.charactersIgnoringModifiers() or "").lower()
                sel = sel_map.get(ch)
                if sel:
                    app = NSApplication.sharedApplication()
                    if app.sendAction_to_from_(sel, None, app.keyWindow()):
                        return None  # handled — swallow the event
        except Exception:
            pass
        return event

    _key_monitor_ref = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
        NSEventMaskKeyDown, handler
    )


def _install_edit_menu():
    """Give the app an Edit menu so Cmd+C/V/X/A work in text fields.

    Menu-bar (LSUIElement) apps have no main menu by default, so the standard
    editing key-equivalents never route to the focused text view. Adding an Edit
    menu with nil-target selectors fixes paste/copy/cut/select-all everywhere.
    """
    global _edit_menu_installed
    if _edit_menu_installed:
        return
    from AppKit import NSMenu, NSMenuItem, NSApplication

    main_menu = NSMenu.alloc().init()
    edit_item = NSMenuItem.alloc().init()
    main_menu.addItem_(edit_item)

    edit_menu = NSMenu.alloc().initWithTitle_("Edit")
    for title, sel, key in (
        ("Cut", "cut:", "x"),
        ("Copy", "copy:", "c"),
        ("Paste", "paste:", "v"),
        ("Select All", "selectAll:", "a"),
    ):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key)
        edit_menu.addItem_(item)
    edit_item.setSubmenu_(edit_menu)

    NSApplication.sharedApplication().setMainMenu_(main_menu)
    _edit_menu_installed = True


def show_rca_window():
    """Open the RCA generator window: inputs for Slack dump + Rootly page, generate to HTML."""
    global _rca_window_ref, _rca_handler_ref
    from AppKit import (
        NSPanel, NSTextField, NSTextView, NSScrollView, NSButton,
        NSFont, NSApplication, NSColor,
        NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
        NSBackingStoreBuffered, NSBezelStyleRounded, NSMakeRect,
    )

    # if a window already exists (maybe just hidden behind something), reuse it
    # so we don't pop a fresh empty one and lose what was already filled in.
    if _rca_window_ref is not None:
        try:
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            _rca_window_ref.makeKeyAndOrderFront_(None)
            return
        except Exception:
            _rca_window_ref = None  # stale ref, fall through and rebuild

    dark = _is_dark_mode()
    w, h = 640, 720
    pad = 16
    field_w = w - pad * 2

    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(180, 140, w, h),
        NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable,
        NSBackingStoreBuffered,
        False,
    )
    panel.setTitle_("Generate RCA")
    panel.setHidesOnDeactivate_(False)  # stay open when user clicks away to grab the URL
    panel.setBecomesKeyOnlyIfNeeded_(False)
    panel.setReleasedWhenClosed_(False)  # keep the object + its filled fields alive when closed
    content = panel.contentView()
    handler = _RCAHandler.alloc().init()
    handler._panel = panel

    def label(text, yy, bold=True):
        lbl = NSTextField.labelWithString_(text)
        lbl.setFrame_(NSMakeRect(pad, yy, field_w, 18))
        lbl.setFont_(NSFont.boldSystemFontOfSize_(12.0) if bold else NSFont.systemFontOfSize_(11.0))
        content.addSubview_(lbl)
        return lbl

    def text_view(yy, height):
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(pad, yy, field_w, height))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(1)
        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, field_w - 20, height))
        tv.setEditable_(True)
        tv.setRichText_(False)
        tv.setFont_(NSFont.fontWithName_size_("Menlo", 12.0) or NSFont.systemFontOfSize_(12.0))
        if dark:
            tv.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(0.18, 0.18, 0.18, 1.0))
            tv.setTextColor_(NSColor.colorWithRed_green_blue_alpha_(0.92, 0.92, 0.92, 1.0))
        scroll.setDocumentView_(tv)
        content.addSubview_(scroll)
        return tv

    def single_line_field(yy, width):
        f = NSTextField.alloc().initWithFrame_(NSMakeRect(pad, yy, width, 24))
        # keep these one-liners — no newlines pasted/typed in
        f.setUsesSingleLineMode_(True)
        f.cell().setWraps_(False)
        f.cell().setScrollable_(True)
        return f

    y = h - 36

    # rootly URL + fetch FIRST — fetch autofills the title/reporter below
    label("1. Rootly / Confluence URL (paste, then Fetch — needs a token):", y)
    y -= 28
    handler._url_field = single_line_field(y, field_w - 100)
    content.addSubview_(handler._url_field)
    fetch_btn = NSButton.alloc().initWithFrame_(NSMakeRect(w - pad - 90, y - 2, 90, 28))
    fetch_btn.setTitle_("Fetch")
    fetch_btn.setBezelStyle_(NSBezelStyleRounded)
    fetch_btn.setTarget_(handler)
    fetch_btn.setAction_(objc.selector(handler.doFetch_, signature=b"v@:@"))
    content.addSubview_(fetch_btn)
    y -= 34

    # incident title + reported by (auto-filled by Fetch, editable)
    label("2. Incident title (auto-filled by Fetch, editable):", y)
    y -= 26
    handler._title_field = single_line_field(y, field_w)
    content.addSubview_(handler._title_field)
    y -= 34

    label("3. Reported by (auto-filled by Fetch, editable):", y)
    y -= 26
    handler._reporter_field = single_line_field(y, field_w)
    content.addSubview_(handler._reporter_field)
    y -= 34

    # rootly content
    label("Rootly / Confluence page content (auto-filled by Fetch, or paste):", y)
    y -= 150
    handler._rootly_tv = text_view(y, 142)
    y -= 28

    # slack dump
    label("Slack channel dump (paste the full incident thread):", y)
    y -= 150
    handler._slack_tv = text_view(y, 142)
    y -= 40

    # buttons
    gen_btn = NSButton.alloc().initWithFrame_(NSMakeRect(w - pad - 140, y, 140, 32))
    gen_btn.setTitle_("Generate RCA")
    gen_btn.setBezelStyle_(NSBezelStyleRounded)
    gen_btn.setTarget_(handler)
    gen_btn.setAction_(objc.selector(handler.doGenerate_, signature=b"v@:@"))
    gen_btn.setKeyEquivalent_("\r")
    content.addSubview_(gen_btn)

    # "also save HTML" checkbox (Markdown is the default output)
    from AppKit import NSSwitchButton
    handler._html_checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(pad + 100, y + 4, 200, 24))
    handler._html_checkbox.setButtonType_(NSSwitchButton)
    handler._html_checkbox.setTitle_("Also save HTML")
    handler._html_checkbox.setState_(0)
    content.addSubview_(handler._html_checkbox)

    close_btn = NSButton.alloc().initWithFrame_(NSMakeRect(pad, y, 90, 32))
    close_btn.setTitle_("Close")
    close_btn.setBezelStyle_(NSBezelStyleRounded)
    close_btn.setTarget_(handler)
    close_btn.setAction_(objc.selector(handler.doClose_, signature=b"v@:@"))
    content.addSubview_(close_btn)
    y -= 56

    # status line
    handler._status = NSTextField.labelWithString_("Paste a Slack dump and/or fetch a Rootly page, then Generate.")
    handler._status.setFrame_(NSMakeRect(pad, pad, field_w, 44))
    handler._status.setFont_(NSFont.systemFontOfSize_(11.0))
    handler._status.setSelectable_(True)
    content.addSubview_(handler._status)

    _install_edit_menu()       # Edit menu route for Cmd+C/V/X/A
    _install_paste_monitor()   # belt-and-braces key monitor (the reliable one)
    _rca_handler_ref = handler  # retain handler so callbacks survive
    _rca_window_ref = panel
    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    panel.makeKeyAndOrderFront_(None)


def set_confluence_token_dialog():
    """Prompt the user for Confluence base URL, email, and API token, then store them."""
    from app.settings import set_confluence_config, read_state

    _bring_to_front()
    rumps.alert(
        title="Confluence API Setup",
        message=(
            "To let Wattson fetch Rootly/Confluence pages by URL, create an API token:\n\n"
            "1. Go to id.atlassian.com/manage-profile/security/api-tokens\n"
            "2. Click 'Create API token', name it (e.g. Wattson RCA), copy it\n"
            "3. Enter your site URL, email, and the token on the next screens\n\n"
            "This is optional — you can always paste page content manually instead."
        ),
        ok="Continue",
    )

    state = read_state()
    url_win = rumps.Window(
        message="Confluence site / base URL (e.g. https://your-org.atlassian.net):",
        title="Confluence URL",
        default_text=state.get("confluence_base_url", ""),
        ok="Next", cancel="Cancel", dimensions=(400, 24),
    )
    r = url_win.run()
    if r.clicked == 0 or not r.text.strip():
        return
    base_url = r.text.strip()

    email_win = rumps.Window(
        message="Your Atlassian account email (e.g. you@example.com):",
        title="Confluence Email",
        default_text=state.get("confluence_email", ""),
        ok="Next", cancel="Cancel", dimensions=(400, 24),
    )
    r = email_win.run()
    if r.clicked == 0 or not r.text.strip():
        return
    email = r.text.strip()

    token_win = rumps.Window(
        message="Paste your Confluence API token:",
        title="Confluence Token",
        default_text="",
        ok="Save", cancel="Cancel", dimensions=(400, 24),
    )
    r = token_win.run()
    if r.clicked == 0 or not r.text.strip():
        return
    token = r.text.strip()

    set_confluence_config(base_url, email, token)
    rumps.alert(title="Saved", message="Confluence credentials stored. You can now fetch pages by URL in the RCA window.")


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
