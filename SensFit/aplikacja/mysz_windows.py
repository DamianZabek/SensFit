"""Reading raw mouse movement on Windows (Raw Input), the same API that CS2 uses.

The program does NOT touch the game process. It creates its own invisible window that receives a
copy of the mouse events from the system (the RIDEV_INPUTSINK flag also delivers them while the
window is in the background). The values are counts, the raw units of the mouse sensor, without
Windows acceleration.
"""
import ctypes
import threading
import time
from ctypes import wintypes

from konfiguracja import KUBELEK_S  # movement is summed in 4 ms "buckets" (250 samples per second are enough)

# constants from the Windows documentation (winuser.h)
WM_INPUT = 0x00FF
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002
MOUSE_MOVE_ABSOLUTE = 0x0001
LRESULT = ctypes.c_ssize_t


# structures from winuser.h rewritten with ctypes
class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", wintypes.USHORT),
                ("_wyrownanie", wintypes.USHORT),  # in C a union follows here, aligned to 4 bytes
                ("usButtonFlags", wintypes.USHORT), ("usButtonData", wintypes.USHORT),
                ("ulRawButtons", wintypes.ULONG),
                ("lLastX", wintypes.LONG), ("lLastY", wintypes.LONG),
                ("ulExtraInformation", wintypes.ULONG)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


class NagrywaczMyszy:
    """Collects movement (in 4 ms buckets) and left button clicks.

    czy_aktywny is a function returning True when recording is allowed (for example alive and playing).
    """

    def __init__(self, czy_aktywny):
        self.czy_aktywny = czy_aktywny
        self.blad = None
        self.wlaczony = False  # True only while recording (set by the program window)
        # The mouse thread writes and the window reads, so a lock keeps them from doing it at the same time
        self._blokada = threading.Lock()
        self.reset()

    def reset(self):
        """Clears the data before a new session."""
        with self._blokada:
            self.kubelki = []      # list of (time_s, dx, dy) in counts
            self.klikniecia = []   # times when the left button was pressed
            self.puszczenia = []   # release times; together with the presses they show when a spray lasted
            self._idx = None       # number of the current bucket
            self._dx = 0
            self._dy = 0

    def pobierz(self):
        """Closes the current bucket and returns a copy of the data: (kubelki, klikniecia, puszczenia)."""
        with self._blokada:
            self._zrzuc()
            return list(self.kubelki), list(self.klikniecia), list(self.puszczenia)

    def kopia(self, od=0):
        """Closed buckets from number `od` and all clicks (used by the live flick counter)."""
        with self._blokada:
            return self.kubelki[od:], list(self.klikniecia), list(self.puszczenia)

    def zdarzenie(self, dx, dy, lewy_wcisniety, t=None, lewy_puszczony=False):
        """Called for every mouse event."""
        with self._blokada:
            if lewy_puszczony:  # always stored, because a spray may have started before the pause
                self.puszczenia.append(t if t is not None else time.perf_counter())
            if not self.czy_aktywny():
                self._zrzuc()
                return
            if t is None:
                t = time.perf_counter()
            if lewy_wcisniety:
                self.klikniecia.append(t)
            if dx or dy:
                idx = int(t / KUBELEK_S)
                if idx != self._idx:      # a new bucket started, so the previous one is stored
                    self._zrzuc()
                    self._idx = idx
                self._dx += dx
                self._dy += dy

    def zrzuc(self):
        with self._blokada:
            self._zrzuc()

    def _zrzuc(self):
        """Stores the current bucket in the list (call with the lock held)."""
        if self._idx is not None and (self._dx or self._dy):
            self.kubelki.append((self._idx * KUBELEK_S, self._dx, self._dy))
        self._idx = None
        self._dx = self._dy = 0

    def start(self):
        """Starts reading in a separate thread. Returns False if that failed."""
        gotowe = threading.Event()
        watek = threading.Thread(target=_petla_raw_input,
                                 args=(self, gotowe), daemon=True)
        watek.start()
        gotowe.wait(3)
        return self.blad is None


def _petla_raw_input(nagrywacz, gotowe):
    """Creates the invisible window, registers the mouse and handles Windows messages."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        # Argument types: without them ctypes passes 64-bit values incorrectly
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                           ctypes.POINTER(wintypes.UINT), wintypes.UINT]
        user32.GetRawInputData.restype = wintypes.UINT
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                           wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                           wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
        user32.RegisterRawInputDevices.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        rozmiar_naglowka = ctypes.sizeof(RAWINPUTHEADER)

        # One buffer for the whole run and one GetRawInputData call per event
        # (a 1000 to 8000 Hz mouse means that many calls per second, so every allocation counts).
        rozmiar_bufora = ctypes.sizeof(RAWINPUT) + 16  # margin: RAWINPUT on Windows can be padded
        bufor_surowy = ctypes.create_string_buffer(rozmiar_bufora)
        raw = RAWINPUT.from_buffer(bufor_surowy)
        rozmiar = wintypes.UINT()

        def obsluga_okna(hwnd, msg, wparam, lparam):
            if msg == WM_INPUT and nagrywacz.wlaczony:  # nothing is read outside recording
                rozmiar.value = rozmiar_bufora
                if user32.GetRawInputData(lparam, RID_INPUT, bufor_surowy, ctypes.byref(rozmiar),
                                          rozmiar_naglowka) not in (0, 0xFFFFFFFF) \
                        and raw.header.dwType == RIM_TYPEMOUSE:
                    m = raw.mouse
                    lewy = bool(m.usButtonFlags & RI_MOUSE_LEFT_BUTTON_DOWN)
                    puszczony = bool(m.usButtonFlags & RI_MOUSE_LEFT_BUTTON_UP)
                    if m.usFlags & MOUSE_MOVE_ABSOLUTE:   # tablets and remote desktop: movement is ignored
                        nagrywacz.zdarzenie(0, 0, lewy, lewy_puszczony=puszczony)
                    else:
                        nagrywacz.zdarzenie(m.lLastX, m.lLastY, lewy, lewy_puszczony=puszczony)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc = WNDPROC(obsluga_okna)  # keep a reference so the garbage collector does not remove it
        hinst = kernel32.GetModuleHandleW(None)
        klasa = WNDCLASSW()
        klasa.lpfnWndProc = wndproc
        klasa.hInstance = hinst
        klasa.lpszClassName = "SensFitRawInput"
        if not user32.RegisterClassW(ctypes.byref(klasa)):
            raise OSError(f"RegisterClassW, kod {ctypes.get_last_error()}")
        hwnd = user32.CreateWindowExW(0, klasa.lpszClassName, "SensFit", 0, 0, 0, 0, 0,
                                      None, None, hinst, None)
        if not hwnd:
            raise OSError(f"CreateWindowExW, kod {ctypes.get_last_error()}")

        mysz = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd)  # 0x01/0x02 = "mouse" in the HID standard
        if not user32.RegisterRawInputDevices(ctypes.byref(mysz), 1, ctypes.sizeof(mysz)):
            raise OSError(f"RegisterRawInputDevices, kod {ctypes.get_last_error()}")
    except Exception as e:  # for example when run outside Windows
        nagrywacz.blad = str(e)
        gotowe.set()
        return

    gotowe.set()
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
