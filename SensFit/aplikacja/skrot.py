"""Global start and stop hotkey for recording. It also works while the game is active.

Windows RegisterHotKey: the system sends WM_HOTKEY to the thread that registered the key, and the
key does not reach the game. The player picks a key in Settings that is not used in CS2 (F10 by default).
"""
import ctypes
import threading

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000  # holding the key does not toggle recording repeatedly
DOMYSLNY = {"nazwa": "F10", "vk": 0x79}  # vk is the Windows virtual-key code
# Keys that cannot be used: Escape (cancels the choice), F12 (reserved for the debugger), modifiers
ZAKAZANE = {0x1B, 0x7B, 0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x01, 0x02}


class Skrot:
    def __init__(self, po_wcisnieciu):
        self.po_wcisnieciu = po_wcisnieciu  # called from a separate thread, so pass the event on, for example through a queue
        self.blad = None
        self._watek = None
        self._id_watku = None

    def ustaw(self, vk):
        """Registers the key with code vk (None disables it). Returns True when the hotkey works."""
        self.zatrzymaj()
        self.blad = None
        if not vk or vk in ZAKAZANE:
            return False
        gotowe = threading.Event()
        self._watek = threading.Thread(target=self._petla, args=(vk, gotowe), daemon=True)
        self._watek.start()
        gotowe.wait(2)
        return self.blad is None and self._id_watku is not None

    def zatrzymaj(self):
        if self._watek and self._id_watku:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._id_watku, WM_QUIT, 0, 0)
            except (AttributeError, OSError):
                pass
            self._watek.join(1)
        self._watek = self._id_watku = None

    def _petla(self, vk, gotowe):
        try:
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            if not user32.RegisterHotKey(None, 1, MOD_NOREPEAT, vk):
                raise OSError(f"klawisz zajęty przez inny program (kod {ctypes.get_last_error()})")
            self._id_watku = kernel32.GetCurrentThreadId()
        except (AttributeError, OSError) as e:  # for example outside Windows
            self.blad = str(e)
            gotowe.set()
            return
        gotowe.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self.po_wcisnieciu()
        finally:
            user32.UnregisterHotKey(None, 1)
