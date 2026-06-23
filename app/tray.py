import os
import subprocess
import threading
import time

import objc
import pyperclip
import rumps

from app.config import (
    MODES, MODELS, DEFAULT_STATE, SOUND_PATH, LAUNCHAGENT_LABEL,
    LAUNCHAGENT_PATH, MODE_TO_FILENAME,
)
from app.settings import (
    read_state, write_state, log,
    get_api_key, set_api_key,
    is_first_run, add_history_entry,
)
from app.prompts import ensure_rules_dir, get_rules_path, get_rca_path, reset_rules
from app.clipboard import copy_selection, replace_selection
from app.llm import rewrite, _model_display_name
from app.hotkeys import HotkeyListener
from app.ui import (
    notify_success, notify_error, play_sound,
    show_preview, record_hotkey, run_onboarding,
    show_rca_window, set_confluence_token_dialog,
)

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _find_app_bundle() -> str:
    """Find the Wattson.app bundle path.
    Works whether running from ~/Applications, /Applications, or dev dist/."""
    import sys
    exe = sys.executable
    # pyinstaller: exe is inside Wattson.app/Contents/MacOS/Wattson
    parts = exe.split("/")
    for i, p in enumerate(parts):
        if p.endswith(".app"):
            candidate = "/".join(parts[: i + 1])
            if os.path.isdir(candidate):
                return candidate
    # fallback checks
    candidates = [
        os.path.expanduser("~/Applications/Wattson.app"),
        "/Applications/Wattson.app",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dist", "Wattson.app"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[0]


def _request_accessibility(prompt: bool = True) -> bool:
    """Check (and optionally trigger) the native macOS Accessibility prompt.
    Returns True if already trusted."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        from Foundation import NSDictionary
        opts = NSDictionary.dictionaryWithObject_forKey_(prompt, "AXTrustedCheckOptionPrompt")
        return AXIsProcessTrustedWithOptions(opts)
    except ImportError:
        from ApplicationServices import AXIsProcessTrusted
        trusted = AXIsProcessTrusted()
        if not trusted and prompt:
            subprocess.Popen([
                "open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
            ])
        return trusted

from Foundation import NSObject

class _Trampoline(NSObject):
    """One-shot callback trampoline for dispatching to the main thread."""
    def initWithFunc_(self, fn):
        self = objc.super(_Trampoline, self).init()
        if self is None:
            return None
        self._fn = fn
        return self

    def invoke(self):
        self._fn()


def _run_on_main_thread(func, *args):
    """Dispatch a function to the main thread. Used for UI calls from background threads."""
    trampoline = _Trampoline.alloc().initWithFunc_(lambda: func(*args))
    trampoline.performSelectorOnMainThread_withObject_waitUntilDone_(
        "invoke", None, True
    )


MODE_SHORT = {
    "Brand Voice": "W",
    "Grammar Only": "Gram",
    "Shorten": "Short",
    "Formal": "Form",
    "Casual": "Chill",
    "Custom Voice": "You",
}


class WattsonApp(rumps.App):
    def __init__(self):
        super().__init__("BV", quit_button=None)
        self.state = read_state()
        self.title = self._mode_title()
        self._undo_buffer = None  # {original, rewritten}
        self._spinning = False
        self._spinner_idx = 0
        self._preview_result = None  # shared slot for preview return value

        ensure_rules_dir()

        self.menu = self._build_menu()
        self._sync_menu_state()

        # hotkey listener in a daemon thread
        self.hotkey_listener = HotkeyListener(
            hotkey_rewrite=self.state.get("hotkey_rewrite", DEFAULT_STATE["hotkey_rewrite"]),
            hotkey_cycle=self.state.get("hotkey_cycle", DEFAULT_STATE["hotkey_cycle"]),
            hotkey_undo=self.state.get("hotkey_undo", DEFAULT_STATE["hotkey_undo"]),
            on_rewrite=self._on_rewrite,
            on_cycle=self._on_cycle,
            on_undo=self._on_undo,
        )
        self.hotkey_listener.start()

        # onboarding for first-time users — use rumps.Timer so it fires on the main thread
        if is_first_run():
            self._onboarding_timer = rumps.Timer(self._deferred_onboarding, 1.5)
            self._onboarding_timer.start()
        else:
            # check permissions with retries (TCC can be slow right after login)
            self._perms_retries = 0
            self._perms_timer = rumps.Timer(self._check_permissions, 5.0)
            self._perms_timer.start()

        log("Wattson started")

    def _check_permissions(self, _):
        """Check TCC with retries. Triggers native macOS prompt on first try.
        After Accessibility is granted, starts an Input Monitoring check."""
        try:
            should_prompt = (self._perms_retries == 0)
            trusted = _request_accessibility(prompt=should_prompt)
            if trusted:
                self._perms_timer.stop()
                log("Accessibility granted")
                self._start_input_monitoring_check()
                return
            self._perms_retries += 1
            if self._perms_retries < 4:
                log(f"Accessibility not ready yet, retry {self._perms_retries}/4...")
                return
            self._perms_timer.stop()
            log("Accessibility not granted — showing manual instructions")
            self._show_permission_instructions()
        except Exception as e:
            self._perms_timer.stop()
            log(f"Permission check failed: {e}")

    def _start_input_monitoring_check(self):
        """After Accessibility is confirmed, wait then check if hotkeys actually fire.
        If they haven't, Input Monitoring is probably missing.
        Only prompts once — tracks in state so we don't nag."""
        if self.state.get("input_monitoring_prompted"):
            return
        self._hotkey_ever_fired = getattr(self, '_hotkey_ever_fired', False)
        if self._hotkey_ever_fired:
            return
        self._im_timer = rumps.Timer(self._check_input_monitoring, 15.0)
        self._im_timer.start()

    def _check_input_monitoring(self, _):
        """If no hotkey has fired yet, prompt user about Input Monitoring."""
        self._im_timer.stop()
        if getattr(self, '_hotkey_ever_fired', False):
            return
        log("No hotkey activity detected — prompting for Input Monitoring")
        # mark so we don't nag again on next launch
        self.state["input_monitoring_prompted"] = True
        write_state(self.state)

        app_bundle = _find_app_bundle()
        subprocess.Popen(["open", "-R", app_bundle])
        subprocess.Popen([
            "open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
        ])
        from app.ui import _bring_to_front
        time.sleep(0.5)
        _bring_to_front()
        rumps.alert(
            title="Wattson — Input Monitoring",
            message=(
                "Almost there! Hotkeys need Input Monitoring permission.\n\n"
                "I've opened the settings and highlighted Wattson.app in Finder.\n\n"
                "1. Click the + button in Input Monitoring\n"
                "2. Drag Wattson.app from Finder into the list\n"
                "3. Toggle it ON\n\n"
                "Hotkeys will work immediately after — no restart needed."
            ),
        )

    def _show_permission_instructions(self):
        """Fallback: manual instructions if native prompt doesn't work."""
        import sys
        app_path = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
        if not app_path.endswith(".app"):
            app_path = _find_app_bundle()
        subprocess.Popen(["open", "-R", app_path])
        subprocess.Popen([
            "open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        ])
        from app.ui import _bring_to_front
        time.sleep(0.5)
        _bring_to_front()
        rumps.alert(
            title="Wattson — Permissions Needed",
            message=(
                "Hotkeys won't work until you enable permissions.\n\n"
                "I've opened Accessibility settings AND highlighted "
                "Wattson.app in Finder.\n\n"
                "Drag Wattson.app into the Accessibility list, then toggle ON.\n\n"
                "Click OK when done — I'll open Input Monitoring next."
            ),
        )
        subprocess.Popen([
            "open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
        ])
        time.sleep(0.5)
        _bring_to_front()
        rumps.alert(
            title="Input Monitoring",
            message=(
                "Now drag Wattson.app into Input Monitoring too.\n"
                "Toggle it ON.\n\n"
                "After both are ON, the app will work immediately — no restart needed."
            ),
        )

    def _deferred_onboarding(self, _):
        """Fires once on the main thread, then stops itself."""
        self._onboarding_timer.stop()
        self._run_onboarding()

    def _mode_title(self, mode=None):
        m = mode or self.state.get("mode", "Brand Voice")
        return MODE_SHORT.get(m, "BV")

    # -----------------------------------------------------------------------
    # Menu construction
    # -----------------------------------------------------------------------

    def _build_menu(self):
        mode_label = rumps.MenuItem(f"Mode: {self.state.get('mode', 'Brand Voice')}")
        mode_label.set_callback(None)

        return [
            mode_label,
            None,  # separator
            rumps.MenuItem("Enabled", callback=self._toggle_enabled),
            None,
            self._mode_submenu(),
            self._model_submenu(),
            None,
            self._edit_rules_submenu(),
            None,
            rumps.MenuItem("Undo Last Rewrite", callback=self._menu_undo),
            self._history_submenu(),
            None,
            rumps.MenuItem("Preview Before Paste", callback=self._toggle_preview),
            rumps.MenuItem("Sound on Complete", callback=self._toggle_sound),
            None,
            rumps.MenuItem("Generate RCA…", callback=self._on_generate_rca),
            None,
            self._settings_submenu(),
            None,
            rumps.MenuItem("Restart", callback=self._restart),
            rumps.MenuItem("Quit", callback=self._quit),
        ]

    def _mode_submenu(self):
        items = []
        current = self.state.get("mode", "Brand Voice")
        for mode in MODES:
            item = rumps.MenuItem(mode, callback=self._set_mode)
            item.state = 1 if mode == current else 0
            items.append(item)
        return {"Mode": items}

    def _model_submenu(self):
        items = []
        current = self.state.get("model", "")
        for display_name, model_id in MODELS.items():
            item = rumps.MenuItem(display_name, callback=self._set_model)
            item.state = 1 if model_id == current else 0
            items.append(item)
        return {"Model": items}

    def _edit_rules_submenu(self):
        items = []
        for mode in MODES:
            item = rumps.MenuItem(f"{mode}...", callback=self._edit_rules)
            items.append(item)
        items.append(None)  # separator
        items.append(rumps.MenuItem("RCA...", callback=self._edit_rca_rules))
        items.append(rumps.MenuItem("Reset All to Defaults", callback=self._reset_all_rules))
        return {"Edit Rules": items}

    def _history_submenu(self):
        items = []
        history = self.state.get("history", [])
        if history:
            for i, entry in enumerate(history[:20]):
                label = entry["original"][:30]
                if len(entry["original"]) > 30:
                    label += "..."
                item = rumps.MenuItem(label, callback=self._copy_from_history)
                item._bv_index = i
                items.append(item)
            items.append(None)
        items.append(rumps.MenuItem("Clear History", callback=self._clear_history))
        return {"History": items}

    def _settings_submenu(self):
        return {"Settings": [
            rumps.MenuItem("API Key...", callback=self._set_api_key),
            rumps.MenuItem("Set Confluence Token...", callback=self._set_confluence_token),
            None,
            rumps.MenuItem("Set Rewrite Hotkey...", callback=self._set_rewrite_hotkey),
            rumps.MenuItem("Set Cycle Mode Hotkey...", callback=self._set_cycle_hotkey),
            rumps.MenuItem("Set Undo Hotkey...", callback=self._set_undo_hotkey),
            None,
            rumps.MenuItem("Auto-start at Login", callback=self._toggle_autostart),
            rumps.MenuItem("Fix Permissions...", callback=self._fix_permissions),
            rumps.MenuItem("Test Connection", callback=self._test_connection),
            rumps.MenuItem("Open Logs", callback=self._open_logs),
        ]}

    # -----------------------------------------------------------------------
    # Menu state sync
    # -----------------------------------------------------------------------

    def _sync_menu_state(self):
        """Reflect current state in menu checkmarks and labels."""
        try:
            self.menu["Enabled"].state = 1 if self.state.get("enabled", True) else 0
            self.menu["Preview Before Paste"].state = 1 if self.state.get("preview") else 0
            self.menu["Sound on Complete"].state = 1 if self.state.get("sound", True) else 0

            mode_label = f"Mode: {self.state.get('mode', 'Brand Voice')}"
            # update the first menu item text
            for key in list(self.menu.keys()):
                if str(key).startswith("Mode:"):
                    self.menu[key].title = mode_label
                    break

            settings = self.menu.get("Settings")
            if settings:
                for item in settings.values():
                    if hasattr(item, 'title'):
                        if item.title == "Auto-start at Login":
                            item.state = 1 if self.state.get("auto_start") else 0
        except Exception:
            pass

    def _save_and_sync(self):
        write_state(self.state)
        self._sync_menu_state()

    # -----------------------------------------------------------------------
    # Core rewrite flow
    # -----------------------------------------------------------------------

    def _on_rewrite(self):
        """Hotkey pressed — run rewrite in a background thread."""
        self._hotkey_ever_fired = True
        if not self.state.get("enabled", True):
            return
        if getattr(self, '_rewrite_active', False):
            return
        self._rewrite_active = True
        threading.Thread(target=self._do_rewrite, daemon=True).start()

    def _looks_like_password(self, text: str) -> bool:
        """Heuristic: password fields on macOS copy as bullet chars or short no-space strings."""
        stripped = text.strip()
        if not stripped:
            return False
        # macOS secure fields copy as bullet characters (•)
        if all(c == '•' or c == '●' or c == '*' for c in stripped):
            return True
        # very short, no spaces, no newlines — likely a password or token
        if len(stripped) < 40 and ' ' not in stripped and '\n' not in stripped:
            # but allow short normal words/phrases
            if not stripped.isalpha() and any(c.isdigit() or c in '!@#$%^&*' for c in stripped):
                return True
        return False

    def _looks_suspicious(self, text: str) -> bool:
        """Heuristic: text that probably wasn't meant to be rewritten."""
        words = len(text.split())
        # extremely long (>2000 words) — probably grabbed a whole doc by accident
        if words > 2000:
            return True
        return False

    def _do_rewrite(self):
        saved_clipboard = pyperclip.paste() or ""
        self._start_spinner()
        try:
            text = copy_selection()
            if not text.strip():
                log("Nothing selected to rewrite")
                _run_on_main_thread(notify_error, "Nothing selected — highlight text first")
                self._stop_spinner()
                return

            # password field check
            if self._looks_like_password(text):
                log("Looks like a password field — skipping")
                _run_on_main_thread(notify_error, "Looks like a password field — rewrite skipped")
                self._stop_spinner()
                return

            mode = self.state.get("mode", "Brand Voice")
            model = self.state.get("model", "")
            word_count = len(text.split())
            self._spinner_word_count = word_count

            # suspicious content check — require double-press within 3s
            if self._looks_suspicious(text):
                now = time.time()
                last = getattr(self, '_confirm_timestamp', 0)
                if now - last > 3.0:
                    self._confirm_timestamp = now
                    log(f"Suspicious content ({word_count} words) — waiting for confirmation")
                    _run_on_main_thread(
                        rumps.notification, "Wattson",
                        f"Rewrite {word_count} words?",
                        "Press the hotkey again within 3s to confirm"
                    )
                    self._stop_spinner()
                    return
                # second press within window — proceed
                self._confirm_timestamp = 0

            log(f"Rewriting {word_count} words in {mode} mode")

            # fired the instant the chosen model times out — so the user knows
            # we're cycling rather than wondering if Wattson froze.
            current_name = _model_display_name(model)

            def _on_fallback():
                _run_on_main_thread(
                    rumps.notification, "Wattson",
                    f"{current_name} is slow to respond",
                    "Lightning's API is having a moment — cycling models until one answers..."
                )

            max_attempts = 3
            result = None
            for attempt in range(1, max_attempts + 1):
                try:
                    result = rewrite(text, mode, model, on_fallback=_on_fallback)
                    if result and result.strip():
                        break
                    log(f"Empty response (attempt {attempt}/{max_attempts})")
                except Exception as retry_err:
                    log(f"Rewrite attempt {attempt}/{max_attempts} failed: {retry_err}")
                    if attempt == max_attempts:
                        raise

            if not result or not result.strip():
                _run_on_main_thread(notify_error, "AI returned nothing — try again or switch models in the menu bar.")
                self._stop_spinner()
                return

            # preview if enabled
            if self.state.get("preview"):
                self._preview_result = None
                _run_on_main_thread(self._show_preview_main, text, result)
                final = self._preview_result
                if final is None:
                    log("Preview cancelled")
                    self._stop_spinner()
                    return
                result = final

            # store undo before replacing
            self._undo_buffer = {"original": text, "rewritten": result}

            replace_selection(result, original_text=text)

            add_history_entry(self.state, text, result)
            self.state = read_state()

            orig_words = len(text.split())
            new_words = len(result.split())

            # check if a fallback model was used and notify the user
            from app.llm import last_fallback_model
            if last_fallback_model:
                fallback_name = _model_display_name(last_fallback_model)
                original_name = _model_display_name(model)
                _run_on_main_thread(
                    rumps.notification, "Wattson",
                    f"⚠️ {original_name} is down",
                    f"Used {fallback_name} instead. Rewrite completed ({orig_words} → {new_words} words)."
                )
                log(f"Rewrite done via fallback {fallback_name}: {orig_words} → {new_words} words")
            else:
                _run_on_main_thread(notify_success, mode, orig_words, new_words)
                log(f"Rewrite done: {orig_words} → {new_words} words")

            if self.state.get("sound", True):
                play_sound(SOUND_PATH)

        except Exception as e:
            log(f"Rewrite error: {e}")
            msg = str(e)
            # already friendly if it came from _friendly_error in llm.py
            if not any(hint in msg for hint in ["API key", "Lightning AI", "timed out", "internet", "Rate limited", "Rewrite failed", "All models"]):
                msg = f"Something went wrong — check Settings → Open Logs for details."
            _run_on_main_thread(notify_error, msg)
            self.title = self._mode_title() + "!"

        finally:
            self._rewrite_active = False
            self._stop_spinner()
            try:
                pyperclip.copy(saved_clipboard)
            except Exception:
                pass

    def _show_preview_main(self, original, rewritten):
        """Wrapper for show_preview that stores result — called on main thread."""
        self._preview_result = show_preview(original, rewritten)

    def _on_cycle(self):
        """Cycle to the next mode."""
        self._hotkey_ever_fired = True
        current = self.state.get("mode", "Brand Voice")
        try:
            idx = MODES.index(current)
        except ValueError:
            idx = 0
        next_mode = MODES[(idx + 1) % len(MODES)]
        self.state["mode"] = next_mode
        write_state(self.state)
        self.title = self._mode_title()

        def _update_ui():
            self._sync_menu_state()
            try:
                mode_menu = self.menu.get("Mode")
                if mode_menu:
                    for item in mode_menu.values():
                        if hasattr(item, 'title'):
                            item.state = 1 if item.title == next_mode else 0
            except Exception:
                pass
            for key in list(self.menu.keys()):
                if str(key).startswith("Mode:"):
                    self.menu[key].title = f"Mode: {next_mode}"
                    break
            rumps.notification(title="Wattson", subtitle="Mode", message=next_mode)

        _run_on_main_thread(_update_ui)
        log(f"Mode cycled to: {next_mode}")

    def _on_undo(self):
        """Undo the last rewrite."""
        self._hotkey_ever_fired = True
        if not self._undo_buffer:
            _run_on_main_thread(rumps.notification, "Wattson", "Nothing to undo", "No recent rewrite to undo")
            return
        replace_selection(self._undo_buffer["original"])
        _run_on_main_thread(rumps.notification, "Wattson", "Undo", "Original text restored")
        log("Undo: restored original text")
        self._undo_buffer = None

    # -----------------------------------------------------------------------
    # Spinner
    # -----------------------------------------------------------------------

    def _start_spinner(self, word_count: int = 0):
        self._spinning = True
        self._spinner_idx = 0
        self._spinner_start = time.time()
        self._spinner_word_count = word_count
        self._spinner_notified_15 = False
        self._spinner_notified_45 = False

        if getattr(self, '_spinner_thread_alive', False):
            return

        def _spin():
            self._spinner_thread_alive = True
            while self._spinning:
                elapsed = int(time.time() - self._spinner_start)
                frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
                if elapsed >= 5:
                    self.title = f"{frame} {elapsed}s"
                else:
                    self.title = frame
                self._spinner_idx += 1

                if elapsed >= 15 and not self._spinner_notified_15:
                    self._spinner_notified_15 = True
                    wc = self._spinner_word_count
                    msg = f"Still working on it ({wc} words)..." if wc else "Still working..."
                    _run_on_main_thread(rumps.notification, "Wattson", "Hang tight", msg)

                if elapsed >= 45 and not self._spinner_notified_45:
                    self._spinner_notified_45 = True
                    _run_on_main_thread(
                        rumps.notification, "Wattson", "Taking a while",
                        "Still trying — the API may be slow"
                    )

                time.sleep(0.1)
            self._spinner_thread_alive = False

        threading.Thread(target=_spin, daemon=True).start()

    def _stop_spinner(self):
        self._spinning = False
        self.title = self._mode_title()

    # -----------------------------------------------------------------------
    # Menu callbacks
    # -----------------------------------------------------------------------

    def _toggle_enabled(self, sender):
        self.state["enabled"] = not self.state.get("enabled", True)
        self._save_and_sync()

    def _set_mode(self, sender):
        self.state["mode"] = sender.title
        self._save_and_sync()
        self.title = self._mode_title()

        mode_menu = self.menu.get("Mode")
        if mode_menu:
            for item in mode_menu.values():
                if hasattr(item, 'title'):
                    item.state = 1 if item.title == sender.title else 0

        for key in list(self.menu.keys()):
            if str(key).startswith("Mode:"):
                self.menu[key].title = f"Mode: {sender.title}"
                break

    def _set_model(self, sender):
        model_id = MODELS.get(sender.title, sender.title)
        self.state["model"] = model_id
        self._save_and_sync()

        model_menu = self.menu.get("Model")
        if model_menu:
            for item in model_menu.values():
                if hasattr(item, 'title'):
                    item.state = 1 if item.title == sender.title else 0

    def _toggle_preview(self, sender):
        self.state["preview"] = not self.state.get("preview", False)
        self._save_and_sync()

    def _toggle_sound(self, sender):
        self.state["sound"] = not self.state.get("sound", True)
        self._save_and_sync()

    def _edit_rules(self, sender):
        # sender.title is like "Brand Voice..." — strip the ellipsis
        mode_name = sender.title.rstrip(".")
        path = get_rules_path(mode_name)
        if path.exists():
            subprocess.Popen(["open", "-t", str(path)])
        else:
            ensure_rules_dir()
            subprocess.Popen(["open", "-t", str(path)])

    def _edit_rca_rules(self, _):
        path = get_rca_path()
        if not path.exists():
            ensure_rules_dir()
        subprocess.Popen(["open", "-t", str(path)])

    def _on_generate_rca(self, _):
        try:
            show_rca_window()
        except Exception as e:
            log(f"Failed to open RCA window: {e}")
            rumps.notification(title="Wattson", subtitle="RCA", message=f"Couldn't open RCA window: {e}")

    def _set_confluence_token(self, _):
        try:
            set_confluence_token_dialog()
        except Exception as e:
            log(f"Confluence token dialog failed: {e}")

    def _reset_all_rules(self, _):
        result = rumps.alert(
            title="Reset Rules",
            message="Reset all rules files to their defaults?\n\nThis will overwrite any edits you've made.",
            ok="Reset",
            cancel="Cancel",
        )
        if result == 1:
            reset_rules()
            rumps.notification(title="Wattson", subtitle="Rules Reset", message="All rules restored to defaults")

    def _menu_undo(self, _):
        self._on_undo()

    def _copy_from_history(self, sender):
        idx = getattr(sender, '_bv_index', 0)
        history = self.state.get("history", [])
        if idx < len(history):
            pyperclip.copy(history[idx]["rewritten"])
            rumps.notification(title="Wattson", subtitle="Copied", message="Rewritten text copied to clipboard")

    def _clear_history(self, _):
        self.state["history"] = []
        self._save_and_sync()

    # settings callbacks

    def _set_api_key(self, _):
        existing = get_api_key() or ""
        masked = f"{'•' * 12}{existing[-4:]}" if len(existing) > 4 else ""
        win = rumps.Window(
            message=f"Current: {masked}\n\nPaste your Lightning AI API key (starts with sk-lit-...):",
            title="API Key",
            default_text="",
            ok="Save",
            cancel="Cancel",
            dimensions=(400, 24),
        )
        resp = win.run()
        if resp.clicked == 1 and resp.text.strip():
            set_api_key(resp.text.strip())

    def _set_rewrite_hotkey(self, _):
        current = self.state.get("hotkey_rewrite", DEFAULT_STATE["hotkey_rewrite"])
        new = record_hotkey("Set Rewrite Hotkey", current)
        if new:
            self.state["hotkey_rewrite"] = new
            self._save_and_sync()
            self.hotkey_listener.update_hotkeys(
                new,
                self.state.get("hotkey_cycle", DEFAULT_STATE["hotkey_cycle"]),
                self.state.get("hotkey_undo", DEFAULT_STATE["hotkey_undo"]),
            )

    def _set_cycle_hotkey(self, _):
        current = self.state.get("hotkey_cycle", DEFAULT_STATE["hotkey_cycle"])
        new = record_hotkey("Set Cycle Mode Hotkey", current)
        if new:
            self.state["hotkey_cycle"] = new
            self._save_and_sync()
            self.hotkey_listener.update_hotkeys(
                self.state.get("hotkey_rewrite", DEFAULT_STATE["hotkey_rewrite"]),
                new,
                self.state.get("hotkey_undo", DEFAULT_STATE["hotkey_undo"]),
            )

    def _set_undo_hotkey(self, _):
        current = self.state.get("hotkey_undo", DEFAULT_STATE["hotkey_undo"])
        new = record_hotkey("Set Undo Hotkey", current)
        if new:
            self.state["hotkey_undo"] = new
            self._save_and_sync()
            self.hotkey_listener.update_hotkeys(
                self.state.get("hotkey_rewrite", DEFAULT_STATE["hotkey_rewrite"]),
                self.state.get("hotkey_cycle", DEFAULT_STATE["hotkey_cycle"]),
                new,
            )

    def _toggle_autostart(self, sender):
        self.state["auto_start"] = not self.state.get("auto_start", False)
        self._save_and_sync()

        if self.state["auto_start"]:
            self._install_launchagent()
        else:
            self._remove_launchagent()

    def _install_launchagent(self):
        """Write a LaunchAgent plist for auto-start at login."""
        app_path = _find_app_bundle()

        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHAGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-a</string>
        <string>{app_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{os.path.expanduser("~/Library/Logs/wattson.stdout.log")}</string>
    <key>StandardErrorPath</key>
    <string>{os.path.expanduser("~/Library/Logs/wattson.stderr.log")}</string>
</dict>
</plist>"""
        os.makedirs(os.path.dirname(LAUNCHAGENT_PATH), exist_ok=True)
        with open(LAUNCHAGENT_PATH, "w") as f:
            f.write(plist)
        subprocess.run(["launchctl", "load", "-w", LAUNCHAGENT_PATH],
                       capture_output=True)
        log("LaunchAgent installed for auto-start")

    def _remove_launchagent(self):
        try:
            subprocess.run(["launchctl", "unload", "-w", LAUNCHAGENT_PATH],
                           capture_output=True)
            if os.path.exists(LAUNCHAGENT_PATH):
                os.remove(LAUNCHAGENT_PATH)
            log("LaunchAgent removed")
        except Exception:
            pass

    def _test_connection(self, _):
        """Quick API test — send a one-word message, show result."""
        def _test():
            try:
                from app.llm import call_model
                from app.prompts import get_system_prompt
                from app.config import DEFAULT_MODEL
                start = time.time()
                call_model("Hello", self.state.get("model", DEFAULT_MODEL),
                           get_system_prompt("Grammar Only"))
                elapsed = time.time() - start
                _run_on_main_thread(
                    rumps.notification, "Wattson", "Connection OK",
                    f"Response in {elapsed:.1f}s",
                )
            except Exception as e:
                msg = str(e)
                if "API key not set" in msg:
                    msg = "No API key found — add one in Settings → API Key."
                elif "timed out" in msg.lower() or "timeout" in msg.lower():
                    msg = "Connection timed out — Lightning AI may be down. Try again later."
                elif "connection" in msg.lower():
                    msg = "Can't connect — check your internet and try again."
                elif "401" in msg or "Unauthorized" in msg:
                    msg = "API key is invalid — update it in Settings → API Key."
                else:
                    msg = f"Connection test failed — check Settings → Open Logs."
                _run_on_main_thread(notify_error, msg)

        threading.Thread(target=_test, daemon=True).start()

    def _fix_permissions(self, _):
        """Walk user through enabling permissions with Finder reveal."""
        from app.ui import _bring_to_front
        log("Fix Permissions triggered")
        app_bundle = _find_app_bundle()
        subprocess.Popen(["open", "-R", app_bundle])
        subprocess.Popen([
            "open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        ])
        time.sleep(0.5)
        _bring_to_front()
        rumps.alert(
            title="Step 1 — Accessibility",
            message=(
                "I've highlighted Wattson.app in Finder.\n\n"
                "Drag it into the Accessibility list and toggle it ON.\n\n"
                "Click OK when done."
            ),
        )
        subprocess.Popen([
            "open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
        ])
        time.sleep(0.5)
        _bring_to_front()
        rumps.alert(
            title="Step 2 — Input Monitoring",
            message=(
                "Now drag Wattson.app into Input Monitoring too.\n"
                "Toggle it ON."
            ),
        )
        log("Fix Permissions completed")

    def _open_logs(self, _):
        from app.config import LOG_PATH
        if os.path.exists(LOG_PATH):
            subprocess.Popen(["open", "-a", "Console", LOG_PATH])
        else:
            rumps.alert("No log file found yet.")

    def _restart(self, _):
        """Restart the app — uses open -a for .app bundle, falls back to execv."""
        import sys
        self.hotkey_listener.stop()
        log("App restarting")
        app_bundle = _find_app_bundle()
        if os.path.isdir(app_bundle):
            subprocess.Popen(["open", "-a", app_bundle])
            rumps.quit_application()
        else:
            python = sys.executable
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            os.chdir(app_dir)
            os.execv(python, [python, "-m", "app.main"])

    def _quit(self, _):
        self.hotkey_listener.stop()
        log("App quit")
        rumps.quit_application()

    def _run_onboarding(self):
        run_onboarding()
        self.state = read_state()
        self._sync_menu_state()
