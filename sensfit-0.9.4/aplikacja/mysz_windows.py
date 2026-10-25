import ctypes
import threading
import time
from ctypes import wintypes

KUBELEK_S = 0.004  # ruch sumujemy w "kubełkach" po 4 ms (250 próbek/s wystarcza)

# --- stałe z dokumentacji Windows (winuser.h) ---
WM_INPUT = 0x00FF
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002
MOUSE_MOVE_ABSOLUTE = 0x0001
LRESULT = ctypes.c_ssize_t


# --- struktury z winuser.h przepisane na ctypes ---
class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", wintypes.USHORT),
                ("_wyrownanie", wintypes.USHORT),  # w C dalej jest unia wyrównana do 4 bajtów
                ("usButtonFlags", wintypes.USHORT), ("usButtonData", wintypes.USHORT),
                ("ulRawButtons", wintypes.ULONG),
                ("lLastX", wintypes.LONG), ("lLastY", wintypes.LONG),
                ("ulExtraInformation", wintypes.ULONG)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


class NagrywaczMyszy:
    """Zbiera ruch (w kubełkach 4 ms) i kliknięcia lewym przyciskiem.

    czy_aktywny - funkcja zwracająca True, gdy wolno nagrywać (np. żyjesz i grasz).
    """

    def __init__(self, czy_aktywny):
        self.czy_aktywny = czy_aktywny
        self.blad = None
        # Mysz zapisuje z osobnego wątku, a okno czyta - blokada pilnuje, żeby nie robiły tego naraz
        self._blokada = threading.Lock()
        self.reset()

    def reset(self):
        """Czyści dane przed nową sesją."""
        with self._blokada:
            self.kubelki = []      # lista (czas_s, dx, dy) w counts
            self.klikniecia = []   # czasy wciśnięcia lewego przycisku
            self.puszczenia = []   # czasy puszczenia - razem z wciśnięciami wiadomo, kiedy trwała seria
            self._idx = None       # numer bieżącego kubełka
            self._dx = 0
            self._dy = 0

    def pobierz(self):
        """Kończy bieżący kubełek i zwraca kopię danych: (kubelki, klikniecia, puszczenia)."""
        with self._blokada:
            self._zrzuc()
            return list(self.kubelki), list(self.klikniecia), list(self.puszczenia)

    def zdarzenie(self, dx, dy, lewy_wcisniety, t=None, lewy_puszczony=False):
        """Wywoływane przy każdym zdarzeniu myszy."""
        with self._blokada:
            if lewy_puszczony:  # zapisujemy zawsze - seria mogła się zacząć przed pauzą
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
                if idx != self._idx:      # zaczął się nowy kubełek - zapisz poprzedni
                    self._zrzuc()
                    self._idx = idx
                self._dx += dx
                self._dy += dy

    def zrzuc(self):
        with self._blokada:
            self._zrzuc()

    def _zrzuc(self):
        """Zapisuje bieżący kubełek do listy (wywoływać z założoną blokadą)."""
        if self._idx is not None and (self._dx or self._dy):
            self.kubelki.append((self._idx * KUBELEK_S, self._dx, self._dy))
        self._idx = None
        self._dx = self._dy = 0

    def start(self):
        """Uruchamia odczyt w osobnym wątku. Zwraca False, jeśli się nie udało."""
        gotowe = threading.Event()
        watek = threading.Thread(target=_petla_raw_input,
                                 args=(self, gotowe), daemon=True)
        watek.start()
        gotowe.wait(3)
        return self.blad is None


def _petla_raw_input(nagrywacz, gotowe):
    """Tworzy niewidoczne okno, rejestruje mysz i obsługuje komunikaty Windows."""
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

        # Typy argumentów - bez nich ctypes źle przekazuje 64-bitowe wartości
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

        def obsluga_okna(hwnd, msg, wparam, lparam):
            if msg == WM_INPUT:
                rozmiar = wintypes.UINT(0)
                user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(rozmiar), rozmiar_naglowka)
                bufor = ctypes.create_string_buffer(max(rozmiar.value, ctypes.sizeof(RAWINPUT)))
                if user32.GetRawInputData(lparam, RID_INPUT, bufor, ctypes.byref(rozmiar),
                                          rozmiar_naglowka) == rozmiar.value:
                    raw = ctypes.cast(bufor, ctypes.POINTER(RAWINPUT)).contents
                    if raw.header.dwType == RIM_TYPEMOUSE:
                        m = raw.mouse
                        lewy = bool(m.usButtonFlags & RI_MOUSE_LEFT_BUTTON_DOWN)
                        puszczony = bool(m.usButtonFlags & RI_MOUSE_LEFT_BUTTON_UP)
                        if m.usFlags & MOUSE_MOVE_ABSOLUTE:   # tablety / pulpit zdalny - pomijamy ruch
                            nagrywacz.zdarzenie(0, 0, lewy, lewy_puszczony=puszczony)
                        else:
                            nagrywacz.zdarzenie(m.lLastX, m.lLastY, lewy, lewy_puszczony=puszczony)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc = WNDPROC(obsluga_okna)  # trzymamy referencję, żeby GC jej nie usunął
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

        mysz = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd)  # 0x01/0x02 = "mysz" w standardzie HID
        if not user32.RegisterRawInputDevices(ctypes.byref(mysz), 1, ctypes.sizeof(mysz)):
            raise OSError(f"RegisterRawInputDevices, kod {ctypes.get_last_error()}")
    except Exception as e:  # np. uruchomione poza Windows
        nagrywacz.blad = str(e)
        gotowe.set()
        return

    gotowe.set()
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
