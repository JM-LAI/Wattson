import threading

from pynput import keyboard as pynput_keyboard

from app.settings import log


def _normalize_hotkey(expr: str) -> str:
    """Normalise a hotkey string to pynput format: <cmd>+<ctrl>+g"""
    parts = [p.strip() for p in expr.split("+")]
    out = []
    for p in parts:
        token = p.strip("<>").lower()
        if token in ("cmd", "ctrl", "alt", "shift"):
            out.append(f"<{token}>")
        else:
            out.append(token)
    return "+".join(out)


class HotkeyListener:
    """Global hotkey listener running in a daemon thread."""

    def __init__(self, hotkey_rewrite: str, hotkey_cycle: str, hotkey_undo: str,
                 on_rewrite=None, on_cycle=None, on_undo=None):
        self._hotkey_rewrite = _normalize_hotkey(hotkey_rewrite)
        self._hotkey_cycle = _normalize_hotkey(hotkey_cycle)
        self._hotkey_undo = _normalize_hotkey(hotkey_undo)
        self.on_rewrite = on_rewrite or (lambda: None)
        self.on_cycle = on_cycle or (lambda: None)
        self.on_undo = on_undo or (lambda: None)
        self._listener = None
        self._thread = None

    def start(self):
        """Start listening for hotkeys in a daemon thread."""
        if self._thread and self._thread.is_alive():
            return

        hotkeys_map = {
            self._hotkey_rewrite: self.on_rewrite,
            self._hotkey_cycle: self.on_cycle,
            self._hotkey_undo: self.on_undo,
        }

        log(f"Hotkeys: rewrite={self._hotkey_rewrite} "
            f"cycle={self._hotkey_cycle} undo={self._hotkey_undo}")

        def _run():
            try:
                self._listener = pynput_keyboard.GlobalHotKeys(hotkeys_map)
                self._listener.start()
                self._listener.join()
            except Exception as e:
                log(f"Hotkey listener error: {e}")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the hotkey listener."""
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def update_hotkeys(self, hotkey_rewrite: str, hotkey_cycle: str, hotkey_undo: str):
        """Restart with new hotkey bindings."""
        self._hotkey_rewrite = _normalize_hotkey(hotkey_rewrite)
        self._hotkey_cycle = _normalize_hotkey(hotkey_cycle)
        self._hotkey_undo = _normalize_hotkey(hotkey_undo)
        self.stop()
        self.start()
