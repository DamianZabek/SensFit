"""SensFit main window (tkinter).

Rule: tkinter may only be touched from the main thread. The worker threads (mouse reading, GSI
server, analysis, update check) only put data into a queue, and the window reads it every 0.5 s
in the `odswiez` method.

Language and theme changes rebuild the window from scratch while recording and results stay.
"""
import base64
import io
import os
import platform
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk


def zapisz_blad(tekst):
    """Writes the error to %APPDATA%\\SensFit\\blad.txt and shows a dialog.

    The .exe has no console, so without this a startup error would be invisible.
    """
    folder = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "SensFit")
    plik = os.path.join(folder, "blad.txt")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(plik, "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S} ---\n{tekst}\n")
    except OSError:
        pass
    try:
        messagebox.showerror("SensFit", "SensFit napotkał błąd / SensFit hit an error:\n\n"
                             + tekst[-1500:] + f"\n\n{plik}")
    except Exception:
        pass


def _blad_globalny(typ, wartosc, slad):
    import traceback
    zapisz_blad("".join(traceback.format_exception(typ, wartosc, slad)))


sys.excepthook = _blad_globalny

import aktualizacja
import analiza
import dostep
import dziennik
import eksport
import gsi
import jezyk
import ksztalty
import konfiguracja as kfg
import mapy
import raport
import rozdzielczosc as rozdz
import sesje
import skrot
import wersja
from jezyk import t
from mysz_windows import NagrywaczMyszy

WERSJA = wersja.OPIS
MIN_MINUT = 3  # shorter recordings are not useful
CEL_FLICKOW = 150  # counter "flicks: 65/150" shown while recording
CO_ILE_FLICKI_S = 10
DISCORD = "https://discord.gg/g56qwVZAsh"
CO_ILE_SPRAWDZAC_CS2_S = 20  # how often to look for a sensitivity change in the CS2 files

# Two themes. Dark: graphite like a game HUD with amber as the accent. Light: same proportions.
MOTYWY = {
    "ciemny": {
        "tlo": "#14161a", "panel": "#1b1f26", "panel2": "#222630", "linia": "#2a2f38",
        "tekst": "#e8eaed", "mocny": "#ffffff", "szary": "#9aa1ac", "akcent": "#ffb020",
        "akcent_tekst": "#ffb020", "akcent_hover": "#ffc457", "na_akcencie": "#1a1204",
        "ok": "#4ade80", "uwaga": "#fbbf24", "zle": "#f97373", "pasek": "#0e1013",
        "pole": "#0e1013", "hover": "#343a46", "stara": "#7d8590",
    },
    "jasny": {
        "tlo": "#eef1f5", "panel": "#ffffff", "panel2": "#f5f7fa", "linia": "#d6dde6",
        "tekst": "#18212d", "mocny": "#0d141d", "szary": "#556171", "akcent": "#ffb020",
        "akcent_tekst": "#8f5200", "akcent_hover": "#ffc457", "na_akcencie": "#1a1204",
        "ok": "#17803d", "uwaga": "#9a6400", "zle": "#c23b32", "pasek": "#e7ebf0",
        "pole": "#ffffff", "hover": "#dfe5ec", "stara": "#7a8594",
    },
}
KOLOR = dict(MOTYWY["ciemny"])
MOTYW = "ciemny"
CZCIONKA = "Segoe UI"
MONO = "Consolas"


def ustaw_motyw(nazwa):
    global MOTYW
    MOTYW = nazwa if nazwa in MOTYWY else "ciemny"
    KOLOR.clear()
    KOLOR.update(MOTYWY[MOTYW])


def sciezka_zasobu(nazwa):
    """Path to a file bundled into the .exe (for example icons)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), nazwa)


def wczytaj_logo(nazwa):
    """Icon image (PNG), or None when the file is missing."""
    try:
        return tk.PhotoImage(file=sciezka_zasobu(nazwa))
    except tk.TclError:
        return None


def opis_windows():
    if sys.platform == "win32":
        try:
            v = sys.getwindowsversion()
            nazwa = "Windows 11" if v.major == 10 and v.build >= 22000 else f"Windows {platform.release()}"
            return f"{nazwa} (build {v.build})"
        except AttributeError:
            pass
    return platform.platform()


# Small window elements
def etykieta(rodzic, tekst="", bg="panel", fg="tekst", rozmiar=10, gruba=False, czcionka=None, **opcje):
    opcje.setdefault("anchor", "w")
    opcje.setdefault("justify", "left")
    return tk.Label(rodzic, text=tekst, bg=KOLOR[bg], fg=KOLOR[fg],
                    font=(czcionka or CZCIONKA, rozmiar, "bold" if gruba else "normal"), **opcje)


def zawin(lbl, margines=0):
    """Wraps the label text to the width of the frame it sits in."""
    lbl.config(wraplength=560)
    lbl.master.bind("<Configure>", lambda e: lbl.winfo_exists() and lbl.config(wraplength=max(120, e.width - margines)), add="+")
    return lbl


def nadtytul(rodzic, tekst, bg="panel", akcent=False):
    """Small uppercase caption above a card (for example ZALECENIE)."""
    return etykieta(rodzic, tekst.upper(), bg=bg, fg="akcent_tekst" if akcent else "szary", rozmiar=9, gruba=True)


PROMIEN_KARTY = 12
PROMIEN_PRZYCISKU = 9
_STYLE = {"pokolenie": 0}  # ttk elements with images (created anew on every theme change)


def _tlo_rodzica(w):
    try:
        return w.cget("bg")
    except (tk.TclError, AttributeError):  # a ttk parent has no bg option
        return None


def karta(rodzic, padx=20, pady=16, bg="panel"):
    """Card with a border and rounded corners. Returns (outer frame, inner frame).

    The corners are four small images placed (place) on the card corners, so they do not change the card layout.
    """
    zewnatrz = _tlo_rodzica(rodzic)
    if ksztalty.dostepne() and zewnatrz:
        zew = tk.Frame(rodzic, bg=KOLOR["linia"])
        srodek = tk.Frame(zew, bg=KOLOR[bg])
        srodek.pack(fill="both", expand=True, padx=1, pady=1)
        wew = tk.Frame(srodek, bg=KOLOR[bg])
        wew.pack(fill="both", expand=True, padx=padx - 1, pady=pady - 1)
        for obraz, miejsce in zip(ksztalty.rogi(PROMIEN_KARTY, KOLOR[bg], KOLOR["linia"], zewnatrz),
                                  ({}, {"relx": 1, "anchor": "ne"}, {"rely": 1, "anchor": "sw"},
                                   {"relx": 1, "rely": 1, "anchor": "se"})):
            tk.Label(zew, image=obraz, bd=0, highlightthickness=0, padx=0, pady=0).place(**miejsce)
        return zew, wew
    zew = tk.Frame(rodzic, bg=KOLOR[bg], highlightbackground=KOLOR["linia"], highlightthickness=1)
    wew = tk.Frame(zew, bg=KOLOR[bg])
    wew.pack(fill="both", expand=True, padx=padx, pady=pady)
    return zew, wew


def link(rodzic, tekst, polecenie, bg="panel"):
    lbl = etykieta(rodzic, tekst, bg=bg, fg="akcent_tekst", rozmiar=9, gruba=True, cursor="hand2", takefocus=1)
    lbl.bind("<Button-1>", lambda _e: polecenie())
    lbl.bind("<Key-Return>", lambda _e: polecenie())
    lbl.bind("<Key-space>", lambda _e: polecenie())
    return lbl


def plakietka(rodzic, tekst, dobra=False, bg="panel"):
    return tk.Label(rodzic, text=tekst, bg=KOLOR["panel2"], fg=KOLOR["ok" if dobra else "szary"],
                    font=(CZCIONKA, 9, "bold" if dobra else "normal"), padx=8, pady=2,
                    highlightbackground=KOLOR["linia"], highlightthickness=1)


class Przelacznik(tk.Frame):
    """Buttons side by side where one is selected (as in the preview: PL | EN)."""

    def __init__(self, rodzic, opcje, wybrana, po_wyborze=None):
        super().__init__(rodzic, bg=KOLOR["linia"], padx=1, pady=1)
        self.po_wyborze = po_wyborze
        self.przyciski = {}
        for i, (klucz, tekst) in enumerate(opcje):
            lbl = tk.Label(self, text=tekst, font=(CZCIONKA, 9, "bold"), padx=12, pady=5,
                           cursor="hand2", takefocus=1)
            lbl.pack(side="left", padx=(1 if i else 0, 0))
            for zdarzenie in ("<Button-1>", "<Key-space>", "<Key-Return>"):
                lbl.bind(zdarzenie, lambda _e, k=klucz: self.wybierz(k, True))
            self.przyciski[klucz] = lbl
        self.wybierz(wybrana)

    def wybierz(self, klucz, wywolaj=False):
        self.wybrana = klucz
        for k, lbl in self.przyciski.items():
            aktywny = k == klucz
            lbl.config(bg=KOLOR["akcent"] if aktywny else KOLOR["panel"],
                       fg=KOLOR["na_akcencie"] if aktywny else KOLOR["szary"])
        if wywolaj and self.po_wyborze:
            self.po_wyborze(klucz)


class Przewijana(tk.Frame):
    """Frame with a scrollbar, for tab content that can be taller than the window."""

    def __init__(self, rodzic):
        super().__init__(rodzic, bg=KOLOR["tlo"])
        self.canvas = tk.Canvas(self, bg=KOLOR["tlo"], highlightthickness=0, bd=0)
        self.pasek = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Vertical.TScrollbar")
        self.wnetrze = tk.Frame(self.canvas, bg=KOLOR["tlo"])
        self.okno = self.canvas.create_window(0, 0, window=self.wnetrze, anchor="nw")
        self.canvas.configure(yscrollcommand=self.pasek.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.pasek_widoczny = False
        self.wnetrze.bind("<Configure>", lambda _e: self._uklad())
        self.canvas.bind("<Configure>", self._szerokosc)

    def _szerokosc(self, e):
        self.canvas.itemconfigure(self.okno, width=e.width)
        self._uklad()

    def _uklad(self):
        self.canvas.configure(scrollregion=(0, 0, self.wnetrze.winfo_reqwidth(), self.wnetrze.winfo_reqheight()))
        potrzebny = self.wnetrze.winfo_reqheight() > self.canvas.winfo_height() + 2
        if potrzebny != self.pasek_widoczny:
            self.pasek_widoczny = potrzebny
            if potrzebny:
                self.pasek.pack(side="right", fill="y", before=self.canvas)
            else:
                self.pasek.pack_forget()
                self.canvas.yview_moveto(0)

    def przewin(self, ile):
        if self.pasek_widoczny:
            self.canvas.yview_scroll(ile, "units")

    def na_gore(self):
        self.canvas.yview_moveto(0)


class Zakladki:
    """Side menu: buttons on the left, content on the right. Pages have keys (rec, res and so on)."""

    def __init__(self, menu, po_zmianie=None):
        self.menu = menu
        self.po_zmianie = po_zmianie
        self.pozycje = {}  # key -> (page, row, stripe, label, name)
        self.aktywna = None

    def add(self, klucz, strona, nazwa):
        k = KOLOR
        c = tk.Canvas(self.menu, height=40, bg=k["pasek"], highlightthickness=1, highlightbackground=k["pasek"],
                      highlightcolor=k["akcent"], bd=0, cursor="hand2", takefocus=1)
        c.pack(fill="x", pady=1)
        tlo = c.create_image(0, 0, anchor="nw")
        ikona = c.create_image(14, 20, anchor="w")
        tekst = c.create_text(42, 20, anchor="w", text=nazwa, fill=k["szary"], font=(CZCIONKA, 11))
        c.bind("<Button-1>", lambda _e, kl=klucz: self.select(kl))
        c.bind("<Key-Return>", lambda _e, kl=klucz: self.select(kl))
        c.bind("<Enter>", lambda _e, kl=klucz: self._rysuj(kl, True))
        c.bind("<Leave>", lambda _e, kl=klucz: self._rysuj(kl, False))
        c.bind("<Configure>", lambda _e, kl=klucz: self._rysuj(kl))
        self.pozycje[klucz] = (strona, c, (tlo, ikona, tekst), klucz, nazwa)

    def _rysuj(self, klucz, nad=False):
        """Item background: active is a lighter rounded bar with an accent, hovered is a soft background."""
        k = KOLOR
        _s, c, (tlo, ikona, tekst), _k, _n = self.pozycje[klucz]
        aktywna = klucz == self.aktywna
        szer = max(40, c.winfo_width() - 2)
        kolor = k["panel2"] if aktywna else (k["panel"] if nad else None)
        if ksztalty.dostepne():
            c.itemconfigure(tlo, image=ksztalty.prostokat(szer, 38, 8, kolor, pasek=k["akcent"] if aktywna else None)
                            if kolor else "")
            c.itemconfigure(ikona, image=ksztalty.ikona(klucz, k["akcent"] if aktywna else k["szary"]))
        else:
            c.configure(bg=kolor or k["pasek"])
        c.itemconfigure(tekst, fill=k["mocny"] if aktywna else k["szary"],
                        font=(CZCIONKA, 11, "bold" if aktywna else "normal"))

    def select(self, klucz):
        self.aktywna = klucz
        for kl, (strona, *_r) in self.pozycje.items():
            self._rysuj(kl)
            if kl == klucz:
                strona.pack(fill="both", expand=True)
            else:
                strona.pack_forget()
        if self.po_zmianie:
            self.po_zmianie(klucz, self.pozycje[klucz][4])

    def strona(self):
        return self.pozycje[self.aktywna][0] if self.aktywna else None


def konfiguruj_style(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    k = KOLOR
    s.configure(".", background=k["tlo"], foreground=k["tekst"], font=(CZCIONKA, 10),
                bordercolor=k["linia"], focuscolor=k["akcent"])
    ramki = dict(bordercolor=k["tlo"], lightcolor=k["tlo"], darkcolor=k["tlo"])
    s.configure("Vertical.TScrollbar", background=k["linia"], troughcolor=k["tlo"],
                arrowcolor=k["szary"], borderwidth=0, **ramki)
    s.map("Vertical.TScrollbar", background=[("active", k["hover"])])
    s.configure("TButton", background=k["panel2"], foreground=k["tekst"], padding=(12, 6), borderwidth=1,
                bordercolor=k["linia"], lightcolor=k["panel2"], darkcolor=k["panel2"])
    s.map("TButton", background=[("active", k["hover"]), ("disabled", k["panel"])],
          foreground=[("disabled", k["szary"])])
    s.configure("Akcent.TButton", background=k["akcent"], foreground=k["na_akcencie"],
                font=(CZCIONKA, 12, "bold"), padding=(20, 12), bordercolor=k["akcent"],
                lightcolor=k["akcent"], darkcolor=k["akcent"])
    s.map("Akcent.TButton", background=[("active", k["akcent_hover"]), ("disabled", k["linia"])])
    s.configure("AkcentMaly.TButton", background=k["akcent"], foreground=k["na_akcencie"],
                font=(CZCIONKA, 10, "bold"), padding=(16, 6), bordercolor=k["akcent"],
                lightcolor=k["akcent"], darkcolor=k["akcent"])
    s.map("AkcentMaly.TButton", background=[("active", k["akcent_hover"]), ("disabled", k["linia"])],
          foreground=[("disabled", k["szary"])])
    s.configure("TCheckbutton", background=k["panel"], foreground=k["tekst"],
                indicatorbackground=k["pole"], indicatorforeground=k["akcent"])
    s.map("TCheckbutton", background=[("active", k["panel"])], indicatorbackground=[("disabled", k["panel"])])
    s.configure("TEntry", fieldbackground=k["pole"], foreground=k["tekst"], insertcolor=k["tekst"],
                padding=5, bordercolor=k["linia"], lightcolor=k["linia"], darkcolor=k["linia"])
    s.map("TEntry", bordercolor=[("focus", k["akcent"])], lightcolor=[("focus", k["akcent"])])
    s.configure("TCombobox", fieldbackground=k["pole"], background=k["panel2"], foreground=k["tekst"],
                arrowcolor=k["tekst"], padding=4, bordercolor=k["linia"], lightcolor=k["linia"],
                darkcolor=k["linia"], selectbackground=k["pole"], selectforeground=k["tekst"])
    s.map("TCombobox", fieldbackground=[("readonly", k["pole"])], foreground=[("readonly", k["tekst"])],
          bordercolor=[("focus", k["akcent"])])
    s.configure("Horizontal.TProgressbar", background=k["akcent"], troughcolor=k["panel2"],
                bordercolor=k["linia"], lightcolor=k["akcent"], darkcolor=k["akcent"])
    if ksztalty.dostepne():
        _zaokraglone_przyciski(s, root)
    root.option_add("*TCombobox*Listbox.background", k["pole"])
    root.option_add("*TCombobox*Listbox.foreground", k["tekst"])
    root.option_add("*TCombobox*Listbox.selectBackground", k["akcent"])
    root.option_add("*TCombobox*Listbox.selectForeground", k["na_akcencie"])


def _zaokraglone_przyciski(s, root):
    """Buttons with a rounded background (ttk image) instead of the rectangle of the ttk clam theme."""
    k = KOLOR
    _STYLE["pokolenie"] += 1
    r = PROMIEN_PRZYCISKU
    _STYLE["tla"] = set()

    # Big image: Tk tiles the middle of the image across the full button width. With a small
    # image that means hundreds of copies on every redraw and the window slows down; at 320x72 one is usually enough.
    def obraz(kolor, obrys=None):
        return ksztalty.prostokat(320, 72, r, kolor, obrys)

    for styl, zwykly, nad, wylaczony in (
            ("TButton", obraz(k["panel2"], k["linia"]), obraz(k["hover"], k["linia"]), obraz(k["panel"], k["linia"])),
            ("Akcent.TButton", obraz(k["akcent"]), obraz(k["akcent_hover"]), obraz(k["linia"])),
            ("AkcentMaly.TButton", obraz(k["akcent"]), obraz(k["akcent_hover"]), obraz(k["linia"]))):
        element = f"przycisk{_STYLE['pokolenie']}{styl}.border"
        s.element_create(element, "image", zwykly, ("disabled", wylaczony), ("pressed", nad), ("active", nad),
                         border=r + 1, sticky="nsew", width=2 * r + 4, height=2 * r + 4)  # without this the button takes the size of the image
        s.layout(styl, [(element, {"sticky": "nsew", "children": [
            ("Button.focus", {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]})]})]})])

    if not _STYLE.get("dowiazane"):
        root.bind_class("TButton", "<Map>", lambda e: ustaw_styl_przycisku(e.widget), add="+")
        _STYLE["dowiazane"] = True


def ustaw_styl_przycisku(w, baza=None):
    """Button style with corners in the parent colour (the transparent image corners show the style background)."""
    if not hasattr(w, "cget"):
        return
    baza = baza or str(w.cget("style")) or "TButton"
    baza = baza.split(".", 1)[1] if baza.startswith("Tlo") else baza
    tlo = _tlo_rodzica(getattr(w, "master", None)) if ksztalty.dostepne() else None
    nazwa = f"Tlo{tlo.lstrip('#')}.{baza}" if tlo else baza
    if tlo and nazwa not in _STYLE.setdefault("tla", set()):
        # Every style change recalculates all ttk widgets, so every style is set only once
        ttk.Style(w).configure(nazwa, background=tlo)
        _STYLE["tla"].add(nazwa)
    if str(w.cget("style")) != nazwa:
        w.configure(style=nazwa)


def dzwiek(czestotliwosc, ile=1):
    """Short beep for the hotkey (in a separate thread, because Beep blocks). None gives the Windows error sound."""
    if sys.platform != "win32":
        return
    import winsound

    def graj():
        try:
            if czestotliwosc is None:
                winsound.MessageBeep(winsound.MB_ICONHAND)
            for _ in range(ile if czestotliwosc else 0):
                winsound.Beep(czestotliwosc, 110)
        except RuntimeError:
            pass
    threading.Thread(target=graj, daemon=True).start()


def ustaw_okno(root):
    root.title("SensFit")
    root.geometry("1000x780")
    root.minsize(900, 700)
    root.configure(bg=KOLOR["tlo"])
    try:
        root.iconbitmap(default=sciezka_zasobu("ikona.ico"))
    except tk.TclError:
        pass


# Login screen
class EkranDostepu:
    """First screen: checks the access ticket and, when there is none, starts the Discord login.

    The network runs in a separate thread and the window picks up the result every 0.2 s (same as in Aplikacja).
    """

    def __init__(self, root, gdy_wpuszczony):
        self.root = root
        self.gdy_wpuszczony = gdy_wpuszczony
        self.kolejka = queue.Queue()
        self.anuluj = False
        ustaw_okno(root)

        k = KOLOR
        self.ramka = tk.Frame(root, bg=k["tlo"])
        self.ramka.place(relx=0.5, rely=0.45, anchor="center")
        self.logo = wczytaj_logo("ikona_128.png")
        if self.logo:
            tk.Label(self.ramka, image=self.logo, bg=k["tlo"]).pack(pady=(0, 14))
        tk.Label(self.ramka, text="SensFit", bg=k["tlo"], fg=k["mocny"], font=(CZCIONKA, 28, "bold")).pack()
        tk.Label(self.ramka, text=t("wersja testowa - dostęp dla testerów z serwera Discord",
                                    "test version - access for testers from the Discord server"),
                 bg=k["tlo"], fg=k["szary"], font=(CZCIONKA, 10)).pack(pady=(2, 28))
        self.napis = tk.Label(self.ramka, bg=k["tlo"], fg=k["tekst"], font=(CZCIONKA, 11),
                              wraplength=480, justify="center")
        self.napis.pack()
        self.przycisk = tk.Button(self.ramka, text=t("Zaloguj przez Discord", "Log in with Discord"),
                                  command=self.zaloguj, bg="#5865F2", fg="white", activebackground="#4752c4",
                                  activeforeground="white", relief="flat", bd=0, cursor="hand2",
                                  font=(CZCIONKA, 12, "bold"), padx=24, pady=10)
        self.przycisk_anuluj = tk.Button(self.ramka, text=t("Anuluj", "Cancel"), command=self.przerwij,
                                         bg=k["linia"], fg=k["tekst"], activebackground=k["hover"],
                                         activeforeground=k["tekst"], relief="flat", bd=0,
                                         font=(CZCIONKA, 10), padx=16, pady=6)
        self.blad = tk.Label(self.ramka, bg=k["tlo"], fg=k["zle"], font=(CZCIONKA, 10),
                             wraplength=480, justify="center")
        self.blad.pack(pady=(16, 0))
        tk.Label(self.ramka, text=t("Nie masz dostępu? Dołącz do serwera Discord SensFit i poproś o rolę testera.",
                                    "No access? Join the SensFit Discord server and ask for the tester role."),
                 bg=k["tlo"], fg=k["szary"], font=(CZCIONKA, 9), wraplength=480).pack(pady=(28, 0))
        dolacz = tk.Label(self.ramka, text=DISCORD.replace("https://", ""), bg=k["tlo"], fg=k["akcent_tekst"],
                          font=(CZCIONKA, 9, "bold"), cursor="hand2")
        dolacz.pack(pady=(4, 0))
        dolacz.bind("<Button-1>", lambda _e: webbrowser.open(DISCORD))

        if not dostep.skonfigurowany():
            self.pokaz_logowanie(t("Ta kopia SensFit nie ma ustawionego serwera dostępu. "
                                   "Pobierz aktualną wersję od autora.",
                                   "This copy of SensFit has no access server set. "
                                   "Get the current version from the author."))
            self.przycisk.config(state="disabled")
            return
        self.napis.config(text=t("Sprawdzam dostęp…", "Checking access…"))
        self.w_tle(dostep.sprawdz_przy_starcie)
        self.odbierz()

    def w_tle(self, praca):
        def watek():
            try:
                self.kolejka.put(("wynik", praca()))
            except dostep.BladDostepu as e:
                self.kolejka.put(("blad", str(e)))
            except dostep.BrakPolaczenia as e:
                self.kolejka.put(("blad", f"{e} " + t("Sprawdź internet i spróbuj ponownie.",
                                                      "Check your internet connection and try again.")))
            except Exception as e:  # do not leave the window in a waiting state
                self.kolejka.put(("blad", t("Nieoczekiwany błąd: ", "Unexpected error: ") + str(e)))
        threading.Thread(target=watek, daemon=True).start()

    def odbierz(self):
        while not self.kolejka.empty():
            rodzaj, tresc = self.kolejka.get()
            if rodzaj == "blad":
                self.pokaz_logowanie("", tresc)
            elif isinstance(tresc, tuple):  # result of sprawdz_przy_starcie
                stan, dane = tresc
                if stan == "ok":
                    return self.wpusc(dane)
                self.pokaz_logowanie("", dane)
            else:  # ticket after logging in
                return self.wpusc(dostep.odczytaj_bilet(tresc))
        self.root.after(200, self.odbierz)

    def pokaz_logowanie(self, napis="", blad=""):
        self.napis.config(text=napis or t("Zaloguj się kontem Discord, na którym masz rolę testera SensFit.",
                                          "Log in with the Discord account that has the SensFit tester role."))
        self.blad.config(text=blad)
        self.przycisk_anuluj.pack_forget()
        self.przycisk.config(state="normal")
        self.przycisk.pack(before=self.blad, pady=(18, 0))

    def zaloguj(self):
        self.anuluj = False
        self.blad.config(text="")
        self.napis.config(text=t("Dokończ logowanie w przeglądarce, która się otworzyła…",
                                 "Finish logging in in the browser window that opened…"))
        self.przycisk.pack_forget()
        self.przycisk_anuluj.pack(before=self.blad, pady=(18, 0))
        self.w_tle(lambda: dostep.zaloguj(lambda: self.anuluj))

    def przerwij(self):
        self.anuluj = True

    def wpusc(self, dane):
        self.ramka.destroy()
        self.gdy_wpuszczony(dane or {})


# Program window
class Aplikacja:
    def __init__(self, root, uzytkownik=None):
        self.root = root
        self.uzytkownik = uzytkownik or {}
        self.ust = kfg.wczytaj_ustawienia()
        sens_cs2 = kfg.odczytaj_sens_z_cs2()
        if sens_cs2:
            self.ust["sens"] = sens_cs2
        self.wczytaj_obraz()
        dziennik.zanotuj(self.ust["sens"], self.ust["dpi"], "cs2")

        # GSI server: receives from CS2 whether the player is playing
        self.stan = gsi.StanGry()
        try:
            gsi.uruchom_serwer(self.stan)
            self.blad_gsi = None
        except OSError:
            self.blad_gsi = t(f"Port {gsi.PORT} jest zajęty. Czy SensFit nie jest już uruchomiony? "
                              "Jeśli nie, zamknij program, który używa tego portu.",
                              f"Port {gsi.PORT} is busy. Is SensFit already running? "
                              "If not, close the program that uses this port.")

        # Mouse reading runs all the time but stores movement only when czy_nagrywac() is True
        self.nagrywanie = False
        self.bez_gsi = False
        self.czas_gry_s = 0.0
        self.liczba_flickow, self._flicki_od, self._flicki_t = 0, 0, 0.0
        self.ostatnie_flicki = time.monotonic()
        self.cs2_dziala = None
        root.protocol("WM_DELETE_WINDOW", self.zamknij_program)
        self.ostatni_tik = time.monotonic()
        self.ostatnie_sprawdzenie_cs2 = time.monotonic()
        self.nagrywacz = NagrywaczMyszy(self.czy_nagrywac)
        self.mysz_ok = self.nagrywacz.start()

        self.kolejka = queue.Queue()  # results from the threads (analysis, log, update)
        # Start and stop hotkey, also works in game (no key in the settings means the default F10)
        self.ust.setdefault("skrot", dict(skrot.DOMYSLNY))
        self.skrot = skrot.Skrot(lambda: self.kolejka.put(("skrot",)))
        self.skrot.ustaw((self.ust["skrot"] or {}).get("vk"))
        self.wybieram_skrot = False
        self.ostatni = None           # (result, info, sens, dpi), used for export and for rebuilding the window
        self.porady_klucze = []       # [(key, title, what, how)] from the latest result
        self.akt_stan, self.akt_info, self.akt_recznie = "sprawdzam", None, False
        self.baner_ukryty = False
        self.pobrany_instalator = None
        self.komenda = None

        self.zbuduj_okno()
        self.root.bind_all("<MouseWheel>", self.kolko)
        self.root.bind_all("<Button-4>", lambda e: self.kolko(e, -1))
        self.root.bind_all("<Button-5>", lambda e: self.kolko(e, 1))
        self.odswiez()
        self.sprawdz_aktualizacje()

        if not self.ust["dpi"]:
            self.pokaz_ustawienia_cs2()
            self.pole_dpi.focus_set()
            self.pokaz_info_ustawien(t("Na start wpisz DPI swojej myszki i kliknij „Zapisz”.",
                                       "To start, enter your mouse DPI and click “Save”."), "uwaga")
        else:
            self.uruchom_analize()

    # Picture (resolution)
    def wczytaj_obraz(self):
        """The monitor always comes from Windows (there is no Monitor field anymore), the game resolution from the CS2 files or the settings."""
        self.ust.setdefault("skalowanie", "rozciagniete")
        mon = rozdz.rozdzielczosc_monitora()
        if mon:
            self.ust["monitor"] = f"{mon[0]}x{mon[1]}"
        elif not rozdz.parsuj(self.ust.get("monitor")):
            self.ust["monitor"] = "1920x1080"
        gra = rozdz.odczytaj_z_cs2(kfg.folder_steam())
        if gra:
            self.ust["rozdzielczosc"] = f"{gra[0]}x{gra[1]}"
        elif not rozdz.parsuj(self.ust.get("rozdzielczosc")):
            self.ust["rozdzielczosc"] = self.ust["monitor"]
        if self.ust.get("proporcje") not in rozdz.PROPORCJE or gra:
            g = rozdz.parsuj(self.ust["rozdzielczosc"])
            nazwa = rozdz.proporcje_nazwa(*g) if g else "16:9"
            self.ust["proporcje"] = nazwa if nazwa in rozdz.PROPORCJE else self.ust.get("proporcje") or "16:9"

    def obraz(self):
        """(game resolution, monitor resolution, scaling)"""
        return (rozdz.parsuj(self.ust.get("rozdzielczosc")), rozdz.parsuj(self.ust.get("monitor")),
                self.ust.get("skalowanie", "rozciagniete"))

    def klucz_obrazu(self):
        return rozdz.klucz_sesji(*self.obraz())

    def ocena_obrazu(self, sens=None):
        return rozdz.ocen(sens or self.ust["sens"], self.ust["dpi"], *self.obraz())

    def proporcje_monitora(self):
        mon = rozdz.parsuj(self.ust.get("monitor"))
        return rozdz.proporcje_nazwa(*mon) if mon else "16:9"

    # Logic
    def czy_nagrywac(self):
        """Called from the mouse thread, only reads simple fields."""
        return self.nagrywanie and (self.bez_gsi or self.stan.czy_nagrywac())

    def cs2_polaczone(self):
        return time.monotonic() - self.stan.ostatnia_wiadomosc < 30

    def zmien_sens(self, sens, zrodlo):
        """New sensitivity (detected in CS2): saves it, adds a log entry and runs a new analysis."""
        self.ust["sens"] = sens
        try:
            kfg.zapisz_ustawienia(self.ust)
        except OSError:
            pass
        dziennik.zanotuj(sens, self.ust["dpi"], zrodlo)
        if hasattr(self, "pole_sens"):
            self.pole_sens.delete(0, "end")
            self.pole_sens.insert(0, str(sens))
        self.odswiez_naglowek()
        self.odswiez_ocene_obrazu()
        self.uruchom_analize()

    def start_stop(self):
        if self.nagrywanie:
            self.nagrywanie = False
            self.nagrywacz.wlaczony = False
            self.przycisk_start.config(text=t("Analizuję…", "Analysing…"), state="disabled")
            self.root.after(150, self.zakoncz_nagrywanie)  # a moment for the mouse thread to finish
            return

        if not self.ust["dpi"] or not self.ust["sens"]:
            messagebox.showwarning("SensFit", t("Najpierw uzupełnij DPI i czułość w zakładce Ustawienia.",
                                                "First fill in DPI and sensitivity in the Settings tab."))
            self.pokaz_ustawienia_cs2()
            return
        if not self.mysz_ok:
            messagebox.showerror("SensFit", t("Nie można odczytać myszy: ", "Cannot read the mouse: ")
                                 + str(self.nagrywacz.blad))
            return
        sens_cs2 = kfg.odczytaj_sens_z_cs2()  # the player may have changed the sensitivity since the program started
        if sens_cs2 and sens_cs2 != self.ust["sens"]:
            self.zmien_sens(sens_cs2, "cs2")
        gra = rozdz.odczytaj_z_cs2(kfg.folder_steam())  # and the resolution
        if gra and f"{gra[0]}x{gra[1]}" != self.ust.get("rozdzielczosc"):
            self.ust["rozdzielczosc"] = f"{gra[0]}x{gra[1]}"
            nazwa = rozdz.proporcje_nazwa(*gra)
            if nazwa in rozdz.PROPORCJE:
                self.ust["proporcje"] = nazwa
            self.wypelnij_obraz()
            self.odswiez_naglowek()
            self.odswiez_ocene_obrazu()

        self.bez_gsi = self.var_bez_gsi.get()
        self.nagrywacz.reset()
        self.stan.zabojstwa = []  # only kills from this session are counted
        self.czas_gry_s = 0.0
        self.liczba_flickow, self._flicki_od, self._flicki_t = 0, 0, 0.0
        self.sens_nagrania = self.ust["sens"]
        self.nagrywacz.wlaczony = True
        self.nagrywanie = True
        self.przycisk_start.config(text=t("Zakończ i analizuj", "Stop and analyse"))
        self.check_bez_gsi.config(state="disabled")

    def pozwol_zamknac(self, rodzic=None):
        """Before closing the program: if recording is running, asks whether to save. False means the user cancelled."""
        if not self.nagrywanie:
            return True
        odp = messagebox.askyesnocancel("SensFit", t(
            "Trwa nagrywanie. Zapisać sesję przed zamknięciem programu?",
            "Recording is in progress. Save the session before closing the app?"), parent=rodzic or self.root)
        if odp is None:
            return False
        self.nagrywanie = False
        self.nagrywacz.wlaczony = False
        if odp:
            self.zakoncz_nagrywanie(analizuj=False)
        return True

    def zamknij_program(self):
        if self.pozwol_zamknac():
            self.root.destroy()

    def zakoncz_nagrywanie(self, analizuj=True):
        kubelki, klikniecia, puszczenia = self.nagrywacz.pobierz()
        zabojstwa = list(self.stan.zabojstwa)
        minuty = self.czas_gry_s / 60
        self.check_bez_gsi.config(state="normal")
        self.przycisk_start.config(text=t("Rozpocznij nagrywanie", "Start recording"), state="normal")

        if minuty < MIN_MINUT or not kubelki:
            messagebox.showinfo("SensFit", t(f"Nagrano tylko {minuty:.1f} min gry. Sesja nie została zapisana - "
                                             f"potrzeba co najmniej {MIN_MINUT} min (zalecane 20–30).",
                                             f"Only {minuty:.1f} min of play was recorded. The session was not "
                                             f"saved - at least {MIN_MINUT} min is needed (20–30 recommended)."))
            return
        sens_teraz = kfg.odczytaj_sens_z_cs2()  # a sensitivity change during recording gives a session with two settings
        if sens_teraz and sens_teraz != self.sens_nagrania:
            messagebox.showwarning("SensFit", t(
                f"Czułość w CS2 zmieniła się w trakcie nagrywania ({self.sens_nagrania:g} → {sens_teraz:g}). "
                "Sesja nie została zapisana, bo mieszałaby dwa ustawienia. Nagraj ją ponownie na jednej czułości.",
                f"Your CS2 sensitivity changed during recording ({self.sens_nagrania:g} → {sens_teraz:g}). "
                "The session was not saved because it would mix two settings. Record it again on one sensitivity."))
            self.zmien_sens(sens_teraz, "cs2")
            return
        sesje.zapisz(self.sens_nagrania, self.ust["dpi"], minuty, kubelki, klikniecia, self.klucz_obrazu(),
                     puszczenia, zabojstwa, kfg.cs2["m_yaw"], kfg.cs2["m_pitch"])
        if analizuj:
            self.uruchom_analize(przelacz=True)

    def licz_flicki_na_zywo(self):
        """Adds flicks from the new part of the recording, up to the last pause in movement longer than 0.5 s.

        After such a pause the movement and the shot window are closed, so the part is counted exactly as in the analysis.
        shortcut: with movement that never pauses for 0.5 s the counter waits; the final result still uses the whole session.
        """
        kubelki, klikniecia, puszczenia = self.nagrywacz.kopia(self._flicki_od)
        if len(kubelki) < 2:
            return
        koniec = next((i for i in range(len(kubelki) - 1, 0, -1)
                       if kubelki[i][0] - kubelki[i - 1][0] > 0.5 and kubelki[-1][0] - kubelki[i][0] > 0.5), None)
        if not koniec:
            return
        t1 = kubelki[koniec][0]
        klik = [k for k in klikniecia if self._flicki_t <= k < t1]
        if klik:
            try:
                flicki = analiza.znajdz_flicki(kubelki[:koniec], klik, self.sens_nagrania,
                                               [p for p in puszczenia if p >= self._flicki_t], None,
                                               self.ust["dpi"], kfg.cs2["m_yaw"], kfg.cs2["m_pitch"])[0]
                self.liczba_flickow += len(flicki)
            except Exception:  # the counter is only a preview, so an error must not stop the recording
                pass
        self._flicki_od += koniec
        self._flicki_t = t1

    def uruchom_analize(self, przelacz=False):
        sens, dpi = self.ust["sens"], self.ust["dpi"]
        if not sens or not dpi:
            return
        self.etykieta_wynik.config(text=t("Analizuję sesje…", "Analysing sessions…"), fg=KOLOR["szary"])
        obraz, ocena = self.klucz_obrazu(), self.ocena_obrazu()

        def praca():
            try:
                self.kolejka.put(("wynik", sesje.analizuj(sens, dpi, obraz, ocena, kfg.m_yaw()), sens, dpi, przelacz))
            except Exception as e:  # damaged file and similar: show it instead of failing silently
                self.kolejka.put(("blad", str(e)))
        threading.Thread(target=praca, daemon=True).start()

    def odswiez(self):
        """Every 0.5 s: counts play time, updates the statuses and collects results from the threads."""
        teraz = time.monotonic()
        if self.czy_nagrywac():
            self.czas_gry_s += teraz - self.ostatni_tik
        self.ostatni_tik = teraz

        while not self.kolejka.empty():
            wiadomosc = self.kolejka.get()
            rodzaj = wiadomosc[0]
            if rodzaj == "wynik":
                (wynik, info), sens, dpi, przelacz = wiadomosc[1:]
                self.ostatni = (wynik, info, sens, dpi)
                self.pokaz_wynik(wynik, info, sens, dpi)
                if przelacz:
                    self.zakladki.select("res")
            elif rodzaj == "blad":
                self.etykieta_wynik.config(text=t("Błąd analizy: ", "Analysis error: ") + wiadomosc[1],
                                           fg=KOLOR["zle"])
            elif rodzaj == "dziennik":
                self.pokaz_dziennik(wiadomosc[1])
            elif rodzaj == "aktualizacja":
                self.po_sprawdzeniu(wiadomosc[1], wiadomosc[2])
            elif rodzaj == "skrot" and not self.wybieram_skrot:
                self.klik_skrotu()

        if self.nagrywanie and teraz - self.ostatnie_flicki > CO_ILE_FLICKI_S:
            self.ostatnie_flicki = teraz
            self.licz_flicki_na_zywo()

        # Sensitivity changed in CS2 without restarting the program (for example during the day)
        if not self.nagrywanie and teraz - self.ostatnie_sprawdzenie_cs2 > CO_ILE_SPRAWDZAC_CS2_S:
            self.ostatnie_sprawdzenie_cs2 = teraz
            sens_cs2 = kfg.odczytaj_sens_z_cs2()
            if sens_cs2 and sens_cs2 != self.ust["sens"]:
                self.zmien_sens(sens_cs2, "cs2")
            if not self.cs2_polaczone():  # only when there is no data, and then a game restart is suggested
                threading.Thread(target=lambda: setattr(self, "cs2_dziala", kfg.cs2_uruchomione()),
                                 daemon=True).start()
            if hasattr(self, "etykieta_folder"):
                self.odswiez_folder()

        self.odswiez_statusy()
        self.root.after(500, self.odswiez)

    def kolko(self, e, kierunek=None):
        """Mouse wheel scrolling in the active tab."""
        try:
            if e.widget.winfo_toplevel() is not self.root:
                return
        except (AttributeError, KeyError, tk.TclError):
            return
        strona = self.zakladki.strona()
        if isinstance(strona, Przewijana):
            strona.przewin(kierunek if kierunek else (-1 if e.delta > 0 else 1) * max(1, abs(e.delta) // 40))

    # Window layout
    def zbuduj_okno(self, aktywna="rec"):
        r = self.root
        ustaw_okno(r)
        konfiguruj_style(r)
        k = KOLOR

        menu = tk.Frame(r, bg=k["pasek"], width=216, highlightthickness=0)
        menu.pack(side="left", fill="y")
        menu.pack_propagate(False)
        tk.Frame(r, bg=k["linia"], width=1).pack(side="left", fill="y")
        glowna = tk.Frame(r, bg=k["tlo"])
        glowna.pack(side="left", fill="both", expand=True)

        self.logo = wczytaj_logo("ikona_48.png")
        naglowek_menu = tk.Frame(menu, bg=k["pasek"])
        naglowek_menu.pack(fill="x", padx=14, pady=(22, 20))
        if self.logo:
            tk.Label(naglowek_menu, image=self.logo, bg=k["pasek"]).pack(side="left")
        tk.Label(naglowek_menu, text="SensFit", bg=k["pasek"], fg=k["mocny"],
                 font=(CZCIONKA, 17, "bold")).pack(side="left", padx=(10, 0))

        # Menu footer (always visible): Update, CS2 status, version
        stopka = tk.Frame(menu, bg=k["pasek"])
        stopka.pack(side="bottom", fill="x", padx=14, pady=16)
        self.przycisk_akt = ttk.Button(stopka, command=self.klik_aktualizuj)
        self.przycisk_akt.pack(fill="x", pady=(0, 12))
        rzad_cs2 = tk.Frame(stopka, bg=k["pasek"])
        rzad_cs2.pack(anchor="w")
        self.kropka_menu = tk.Label(rzad_cs2, text="●", bg=k["pasek"], fg=k["uwaga"], font=(CZCIONKA, 10))
        self.kropka_menu.pack(side="left")
        self.tekst_menu = tk.Label(rzad_cs2, bg=k["pasek"], fg=k["tekst"], font=(CZCIONKA, 9))
        self.tekst_menu.pack(side="left", padx=(6, 0))
        tk.Label(stopka, text=f"v{WERSJA}", bg=k["pasek"], fg=k["szary"],
                 font=(CZCIONKA, 9)).pack(anchor="w", pady=(6, 0))

        self.menu_pozycje = tk.Frame(menu, bg=k["pasek"])
        self.menu_pozycje.pack(fill="x", padx=8)

        # Top bar: title, badge with the settings, theme switch
        gora = tk.Frame(glowna, bg=k["tlo"])
        gora.pack(fill="x", padx=24, pady=(18, 0))
        self.tytul_strony = tk.Label(gora, bg=k["tlo"], fg=k["mocny"], font=(CZCIONKA, 18, "bold"))
        self.tytul_strony.pack(side="left")
        motyw = tk.Label(gora, text="☀" if MOTYW == "ciemny" else "☾", bg=k["panel"], fg=k["tekst"],
                         font=(CZCIONKA, 12), padx=8, pady=1, cursor="hand2", takefocus=1,
                         highlightbackground=k["linia"], highlightthickness=1)
        motyw.pack(side="right", padx=(10, 0))
        motyw.bind("<Button-1>", lambda _e: self.zmien_motyw("jasny" if MOTYW == "ciemny" else "ciemny"))
        motyw.bind("<Key-Return>", lambda _e: self.zmien_motyw("jasny" if MOTYW == "ciemny" else "ciemny"))
        self.naglowek = tk.Label(gora, bg=k["panel2"], fg=k["szary"], font=(MONO, 9), padx=10, pady=6,
                                 highlightbackground=k["linia"], highlightthickness=1)
        self.naglowek.pack(side="right")
        self.odswiez_naglowek()

        # Banner about a new version (under the bar, above the content)
        self.baner = tk.Frame(glowna, bg=k["panel"], highlightbackground=k["akcent"], highlightthickness=1)
        wnetrze = tk.Frame(self.baner, bg=k["panel"])
        wnetrze.pack(fill="x", padx=14, pady=8)
        self.baner_tekst = etykieta(wnetrze, gruba=True, rozmiar=10)
        self.baner_tekst.pack(side="left")
        ttk.Button(wnetrze, text=t("Później", "Later"), command=self.ukryj_baner).pack(side="right")
        ttk.Button(wnetrze, text=t("Aktualizuj", "Update"), style="AkcentMaly.TButton",
                   command=self.otworz_aktualizacje).pack(side="right", padx=(0, 8))

        self.tresc = tk.Frame(glowna, bg=k["tlo"])
        self.tresc.pack(fill="both", expand=True, padx=(24, 8), pady=(14, 16))
        self.zakladki = Zakladki(self.menu_pozycje, self.po_zmianie_zakladki)
        for klucz, nazwa, budowa in (
                ("rec", t("Nagrywanie", "Recording"), self.zbuduj_nagrywanie),
                ("res", t("Wyniki", "Results"), self.zbuduj_wyniki),
                ("maps", t("Mapy treningowe", "Training maps"), self.zbuduj_mapy),
                ("log", t("Dziennik ustawień", "Settings log"), self.zbuduj_dziennik),
                ("set", t("Ustawienia", "Settings"), self.zbuduj_ustawienia),
                ("help", t("Pomoc", "Help"), self.zbuduj_pomoc)):
            strona = Przewijana(self.tresc)
            budowa(strona.wnetrze)
            self.zakladki.add(klucz, strona, nazwa)
        self.zakladki.select(aktywna)
        self.odswiez_aktualizacje_widok()
        self.odswiez_statusy()

    def przebuduj(self):
        """New language or theme: the window is rebuilt, recording and results stay."""
        aktywna = self.zakladki.aktywna or "rec"
        zakladka_ust = getattr(self, "zakladka_ust", "cs")
        for w in self.root.winfo_children():
            w.destroy()
        self.zbuduj_okno(aktywna)
        if zakladka_ust == "app":
            self.przelacz_ustawienia("app")
        if self.nagrywanie:
            self.przycisk_start.config(text=t("Zakończ i analizuj", "Stop and analyse"))
            self.check_bez_gsi.config(state="disabled")
            self.var_bez_gsi.set(self.bez_gsi)
        if self.ostatni:
            self.pokaz_wynik(*self.ostatni)
        elif self.ust["sens"] and self.ust["dpi"]:
            self.uruchom_analize()

    def po_zmianie_zakladki(self, klucz, nazwa):
        self.tytul_strony.config(text=nazwa)
        if klucz == "log":
            self.odswiez_dziennik()

    # Recording tab
    def zbuduj_nagrywanie(self, rodzic):
        zew, t_ = karta(rodzic, padx=22, pady=20)
        zew.pack(fill="x")
        self.status_mysz = self.wiersz_statusu(t_)
        self.status_gsi = self.wiersz_statusu(t_)
        self.status_cs2 = self.wiersz_statusu(t_)

        tk.Frame(t_, bg=KOLOR["linia"], height=1).pack(fill="x", pady=14)
        self.etykieta_stan = etykieta(t_, rozmiar=20, gruba=True)
        self.etykieta_stan.pack(anchor="w")
        self.etykieta_powod = etykieta(t_, fg="szary")
        self.etykieta_powod.pack(anchor="w", pady=(2, 12))

        liczniki = tk.Frame(t_, bg=KOLOR["panel"])
        liczniki.pack(anchor="w", pady=(0, 16))
        self.licznik_czas = self.licznik(liczniki, t("czas gry", "play time"))
        # Clicks, not bullets: the mouse reports one press for a whole spray
        self.licznik_strzaly = self.licznik(liczniki, t("kliknięcia", "clicks"))
        self.licznik_zabojstw = self.licznik(liczniki, t("zabójstwa (GSI)", "kills (GSI)"))
        self.licznik_flickow = self.licznik(liczniki, t("flicki", "flicks"))

        self.przycisk_start = ttk.Button(t_, text=t("Rozpocznij nagrywanie", "Start recording"),
                                         style="Akcent.TButton", command=self.start_stop)
        self.przycisk_start.pack(anchor="w")
        self.var_bez_gsi = tk.BooleanVar(value=False)
        self.check_bez_gsi = ttk.Checkbutton(
            t_, variable=self.var_bez_gsi,
            text=t("Nagrywaj bez połączenia z CS2 (awaryjnie - nagrywa też menu, mniej dokładne)",
                   "Record without a CS2 connection (fallback - also records menus, less accurate)"))
        self.check_bez_gsi.pack(anchor="w", pady=(12, 0))
        self.etykieta_skrotu = etykieta(t_, fg="szary", rozmiar=9)
        self.etykieta_skrotu.pack(anchor="w", pady=(8, 0))
        self.odswiez_skrot()
        zawin(etykieta(t_, t("Kliknij „Rozpocznij”, przełącz się do CS2 i graj 20–30 min deathmatchu karabinem "
                             "lub pistoletem. Program sam wstrzymuje nagrywanie w menu, po śmierci i przy nożu, "
                             "granatach i AWP. Na koniec wróć tutaj i kliknij „Zakończ i analizuj”.",
                             "Click “Start”, switch to CS2 and play 20–30 min of deathmatch with a rifle or "
                             "pistol. The app pauses recording in menus, after death and with the knife, grenades "
                             "and AWP. When you are done, come back here and click “Stop and analyse”."),
                       fg="szary")).pack(anchor="w", fill="x", pady=(16, 0))

    def wiersz_statusu(self, rodzic):
        ramka = tk.Frame(rodzic, bg=KOLOR["panel"])
        ramka.pack(fill="x", pady=2)
        kropka = etykieta(ramka, "●", rozmiar=11)
        kropka.pack(side="left", padx=(0, 8))
        tekst = etykieta(ramka)
        tekst.pack(side="left")
        return kropka, tekst

    def ustaw_status(self, wiersz, ok, tekst):
        kolor = {True: KOLOR["ok"], False: KOLOR["zle"], None: KOLOR["uwaga"]}[ok]
        wiersz[0].config(fg=kolor)
        wiersz[1].config(text=tekst)

    def licznik(self, rodzic, podpis):
        ramka = tk.Frame(rodzic, bg=KOLOR["panel"])
        ramka.pack(side="left", padx=(0, 40))
        wartosc = etykieta(ramka, "0", rozmiar=18, gruba=True, czcionka=MONO)
        wartosc.pack(anchor="w")
        etykieta(ramka, podpis.upper(), fg="szary", rozmiar=8).pack(anchor="w")
        return wartosc

    # Results tab
    def zbuduj_wyniki(self, rodzic):
        k = KOLOR
        gora = tk.Frame(rodzic, bg=k["tlo"])
        gora.pack(fill="x")

        # Score card (ring) on the right
        zew_oc, oc = karta(gora, padx=18, pady=14)
        zew_oc.pack(side="right", fill="y", padx=(14, 0))
        nadtytul(oc, t("Ocena celowania", "Aim score")).pack(anchor="w")
        self.pierscien = tk.Canvas(oc, width=170, height=170, bg=k["panel"], highlightthickness=0)
        self.pierscien.pack(pady=(4, 0))
        self.ocena_pod = etykieta(oc, fg="szary", rozmiar=9, anchor="center")
        self.ocena_pod.pack()

        # Recommendation card
        zew, h = karta(gora, padx=22, pady=16)
        zew.pack(side="left", fill="both", expand=True)
        nadtytul(h, t("Zalecenie", "Recommendation"), akcent=True).pack(anchor="w")
        self.etykieta_wynik = zawin(etykieta(h, t("Brak wyników - nagraj pierwszą sesję.",
                                                  "No results yet - record your first session."),
                                             rozmiar=17, gruba=True))
        self.etykieta_wynik.pack(anchor="w", fill="x", pady=(4, 0))
        # Big "old to new" numbers, only visible when the program recommends a change
        self.liczby = tk.Frame(h, bg=k["panel"])
        self.liczba_stara = etykieta(self.liczby, rozmiar=28, gruba=True, fg="stara")
        self.liczba_stara.pack(side="left")
        etykieta(self.liczby, "  →  ", fg="akcent_tekst", rozmiar=22, gruba=True).pack(side="left")
        self.liczba_nowa = etykieta(self.liczby, rozmiar=38, gruba=True, fg="mocny")
        self.liczba_nowa.pack(side="left")
        self.liczba_zmiana = etykieta(self.liczby, fg="akcent_tekst", rozmiar=16, gruba=True)
        self.liczba_zmiana.pack(side="left", padx=(14, 0), pady=(10, 0))
        self.etykieta_wynik_pod = zawin(etykieta(h, fg="szary"))
        self.etykieta_wynik_pod.pack(anchor="w", fill="x", pady=(6, 10))
        akcje = tk.Frame(h, bg=k["panel"])
        akcje.pack(anchor="w")
        self.przycisk_kopiuj = ttk.Button(akcje, text=t("Kopiuj komendę do konsoli CS2", "Copy command for the CS2 console"),
                                          style="AkcentMaly.TButton", command=self.kopiuj_komende, state="disabled")
        self.przycisk_kopiuj.pack(side="left")
        self.przycisk_eksport = ttk.Button(akcje, text=t("Eksportuj raport", "Export report"),
                                           command=self.otworz_eksport, state="disabled")
        self.przycisk_eksport.pack(side="left", padx=(8, 0))

        # Card with the "score vs sensitivity" chart
        zew_w, w = karta(rodzic, padx=18, pady=12)
        zew_w.pack(fill="x", pady=(14, 0))
        naglowek = tk.Frame(w, bg=k["panel"])
        naglowek.pack(fill="x")
        nadtytul(naglowek, t("Ocena a czułość", "Score vs sensitivity")).pack(side="left")
        self.wykres_najlepsza = etykieta(naglowek, fg="akcent_tekst", rozmiar=9, gruba=True)
        self.wykres_najlepsza.pack(side="right")
        self.wykres = tk.Canvas(w, height=150, bg=k["panel"], highlightthickness=0)
        self.wykres.pack(fill="x")
        self.wykres.bind("<Configure>", lambda _e: self.rysuj_wykres())
        self.punkty_wykresu = []

        przyciski = tk.Frame(rodzic, bg=k["tlo"])
        przyciski.pack(anchor="w", pady=(12, 0))
        ttk.Button(przyciski, text=t("Analizuj ponownie", "Analyse again"),
                   command=self.uruchom_analize).pack(side="left", padx=(0, 8))
        ttk.Button(przyciski, text=t("Usuń sesje z tej czułości", "Delete sessions for this sensitivity"),
                   command=self.usun_sesje).pack(side="left")

        nadtytul(rodzic, t("Co poprawić", "What to improve"), bg="tlo").pack(anchor="w", pady=(16, 6))
        self.porady_ramka = tk.Frame(rodzic, bg=k["tlo"])
        self.porady_ramka.pack(fill="x")
        self.porady_ramka.columnconfigure(0, weight=1, uniform="porady")
        self.porady_ramka.columnconfigure(1, weight=1, uniform="porady")

        nadtytul(rodzic, t("Szczegóły", "Details"), bg="tlo").pack(anchor="w", pady=(16, 6))
        zew_s, self.szczegoly = karta(rodzic, padx=18, pady=12)
        zew_s.pack(fill="x")
        self.rysuj_pierscien(None)

    def rysuj_pierscien(self, ocena):
        k = KOLOR
        c = self.pierscien
        c.delete("all")
        ramka = (15, 15, 155, 155)
        c.create_arc(*ramka, start=0, extent=359.9, style="arc", outline=k["linia"], width=14)
        if ocena is None:
            c.create_text(85, 85, text="–", fill=k["szary"], font=(CZCIONKA, 36, "bold"))
            return
        wartosc = max(0, min(100, ocena))
        if wartosc > 0:
            c.create_arc(*ramka, start=90, extent=-min(359.9, 3.6 * wartosc), style="arc",
                         outline=k["akcent"], width=14)
        c.create_text(85, 82, text=str(ocena), fill=k["mocny"], font=(CZCIONKA, 38, "bold"))
        c.create_text(85, 116, text=t("z 100", "out of 100"), fill=k["szary"], font=(CZCIONKA, 9))

    def rysuj_wykres(self):
        k = KOLOR
        c = self.wykres
        c.delete("all")
        szer, wys = c.winfo_width(), c.winfo_height()
        if szer < 80:
            return
        punkty = sorted(self.punkty_wykresu)
        if len(punkty) < 2:
            c.create_text(szer / 2, wys / 2, fill=k["szary"], font=(CZCIONKA, 10), justify="center",
                          text=t("Nagraj sesje na kilku czułościach (to samo DPI i rozdzielczość),\n"
                                 "a pojawi się tu krzywa „ocena a czułość”.",
                                 "Record sessions at a few sensitivities (same DPI and resolution)\n"
                                 "and a “score vs sensitivity” curve will appear here."))
            return
        lewo, prawo, gora, dol = 44, 26, 14, 30
        oceny = [p[1] for p in punkty]
        dolna = max(0, int(min(oceny) // 10 * 10) - 10)
        gorna = min(100, int(-(-max(oceny) // 10) * 10) + 10)
        if gorna - dolna < 20:
            gorna = min(100, dolna + 20)
        smin, smax = punkty[0][0], punkty[-1][0]
        zakres = (smax - smin) or 1

        def px(sens):
            return lewo + (sens - smin) / zakres * (szer - lewo - prawo)

        def py(o):
            return gora + (gorna - o) / (gorna - dolna) * (wys - gora - dol)

        for i in range(5):
            o = dolna + (gorna - dolna) * i / 4
            c.create_line(lewo, py(o), szer - prawo, py(o), fill=k["linia"])
            c.create_text(lewo - 8, py(o), text=f"{o:.0f}", fill=k["szary"], anchor="e", font=(CZCIONKA, 8))
        wspolrzedne = [v for p in punkty for v in (px(p[0]), py(p[1]))]
        c.create_line(*wspolrzedne, fill=k["akcent"], width=3, smooth=True)
        najlepsza = max(punkty, key=lambda p: p[1])
        for sens, o, teraz in punkty:
            x, y = px(sens), py(o)
            if (sens, o, teraz) == najlepsza:
                c.create_oval(x - 8, y - 8, x + 8, y + 8, fill=k["akcent"], outline=k["akcent"])
            else:
                c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=k["panel"], outline=k["akcent"], width=3)
            napis = f"{sens:g}" + (t(" (teraz)", " (now)") if teraz else "")
            c.create_text(x, wys - 12, text=napis, fill=k["tekst"] if teraz else k["szary"],
                          font=(CZCIONKA, 8, "bold" if teraz else "normal"))
        self.wykres_najlepsza.config(text=t("najlepsza: ", "best: ") + f"{najlepsza[0]:g}")

    def zeruj_karty(self):
        """Clears the ring, chart, advice and big numbers before a new result is shown."""
        self.liczby.pack_forget()
        self.rysuj_pierscien(None)
        self.ocena_pod.config(text="")
        self.punkty_wykresu = []
        self.wykres_najlepsza.config(text="")
        self.rysuj_wykres()
        for w in self.porady_ramka.winfo_children() + self.szczegoly.winfo_children():
            w.destroy()

    def pokaz_liczby(self, stara, nowa, zmiana):
        self.liczba_stara.config(text=f"{stara:g}")
        self.liczba_nowa.config(text=f"{nowa:g}")
        self.liczba_zmiana.config(text=f"{zmiana:+.0%}".replace("-", "−"))
        self.liczby.pack(anchor="w", before=self.etykieta_wynik_pod)

    def pokaz_porady(self, porady, pusto=None):
        """Advice cards in two columns. porady is a list of (key, title, what, how)."""
        if not porady:
            zew, w = karta(self.porady_ramka, padx=16, pady=12)
            zew.grid(row=0, column=0, columnspan=2, sticky="ew")
            etykieta(w, pusto or t("Nie widać wyraźnych problemów. Tak trzymaj.",
                                   "No clear problems. Keep it up."), fg="tekst" if not pusto else "szary").pack(anchor="w")
            return
        for i, (klucz, tytul, co, jak) in enumerate(porady):
            zew, w = karta(self.porady_ramka, padx=16, pady=12)
            zew.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else 7, 7 if i % 2 == 0 else 0),
                     pady=(0, 14))
            zawin(etykieta(w, f"{i + 1}. {tytul}", gruba=True, rozmiar=10)).pack(anchor="w", fill="x")
            zawin(etykieta(w, co, fg="szary", rozmiar=9)).pack(anchor="w", fill="x", pady=(4, 0))
            zawin(etykieta(w, t("Jak: ", "How: ") + jak, rozmiar=9)).pack(anchor="w", fill="x", pady=(4, 0))
            if mapy.czy_jest_mapa(klucz):
                link(w, t("Zobacz polecane mapy →", "See recommended maps →"),
                     lambda: self.zakladki.select("maps")).pack(anchor="w", pady=(8, 0))

    def szczegol(self, tekst, styl=None):
        """A line in the Details card. styl is h (heading), szary, mono or None."""
        if styl == "h":
            lbl = etykieta(self.szczegoly, tekst, fg="akcent_tekst", rozmiar=10, gruba=True)
            lbl.pack(anchor="w", fill="x", pady=(10 if self.szczegoly.winfo_children()[:-1] else 0, 2))
            return
        lbl = etykieta(self.szczegoly, tekst, fg="szary" if styl == "szary" else "tekst",
                       rozmiar=9, czcionka=MONO if styl == "mono" else None)
        zawin(lbl).pack(anchor="w", fill="x")

    def wstaw_obraz(self, ocena):
        if not ocena:
            return
        self.szczegol(t("Obraz i rozdzielczość", "Picture and resolution"), "h")
        self.szczegol(t("cm/360 nie zależy od rozdzielczości, ale zmienia się pole widzenia i to, "
                        "jak szybko obraz przesuwa się na monitorze",
                        "cm/360 does not depend on resolution, but the field of view changes, and so does "
                        "how fast the picture moves on the monitor"), "szary")
        for linia in rozdz.opis(ocena):
            self.szczegol(linia, "mono")

    def porady_obrazu(self, ocena, sens):
        """Resolution advice with keys, like the advice from the report."""
        wynik = []
        for tytul, co, jak in rozdz.porady(ocena, sens):
            klucz = "piksele" if ocena and ocena["stosunek"] > 1 and not wynik else "rozciagniete"
            wynik.append((klucz, tytul, co, jak))
        return wynik

    def pokaz_wynik(self, w, info, sens, dpi):
        ocena = self.ocena_obrazu(sens)
        self.przycisk_kopiuj.config(state="disabled")
        self.przycisk_eksport.config(state="disabled")
        self.komenda = None
        self.porady_klucze = []
        self.zeruj_karty()

        if w is None:
            self.etykieta_wynik.config(text=t("Brak wyników - nagraj pierwszą sesję.",
                                              "No results yet - record your first session."), fg=KOLOR["tekst"])
            self.etykieta_wynik_pod.config(text=t(
                f"Sesje są liczone osobno dla każdego eDPI i rozdzielczości (teraz: sens {sens}, {dpi} DPI, "
                f"{self.klucz_obrazu() or 'rozdzielczość nieznana'}).",
                f"Sessions are counted separately for each eDPI and resolution (now: sens {sens}, {dpi} DPI, "
                f"{self.klucz_obrazu() or 'unknown resolution'})."))
            self.porady_klucze = self.porady_obrazu(ocena, sens)
            self.pokaz_porady(self.porady_klucze, t("Porady pojawią się po pierwszej analizie.",
                                                    "Tips will appear after the first analysis."))
            self.wstaw_obraz(ocena)
            if not ocena:
                self.szczegol(t("Tu pojawią się szczegóły analizy.", "Analysis details will appear here."), "szary")
            self.odswiez_mapy()
            return

        pod = (dziennik.liczba_sesji_tekst(info["sesje"]) + t(f" · ok. {info['minuty']:.0f} min gry · "
                                                              f"{w['liczba']} flicków zakończonych strzałem",
                                                              f" · about {info['minuty']:.0f} min played · "
                                                              f"{w['liczba']} flicks ending in a shot"))
        if "r_mediana" not in w:
            self.etykieta_wynik.config(text=t("Za mało danych do oceny", "Not enough data yet"), fg=KOLOR["uwaga"])
            self.etykieta_wynik_pod.config(text=pod + t(". Zagraj dłużej - potrzeba co najmniej kilkudziesięciu flicków.",
                                                        ". Play longer - at least a few dozen flicks are needed."))
            self.pokaz_porady([], t("Porady pojawią się, gdy będzie więcej danych.",
                                    "Tips will appear when there is more data."))
            self.wstaw_obraz(ocena)
            self.odswiez_mapy()
            return

        nowa = w["nowa_sens"]
        if nowa != sens:
            self.etykieta_wynik.config(text=t("Zmień czułość", "Change your sensitivity"), fg=KOLOR["tekst"])
            self.pokaz_liczby(sens, nowa, w["zmiana"])
            pod += t("\nNowe eDPI ", "\nNew eDPI ") + f"{kfg.edpi(nowa, dpi):.0f} · {kfg.cm_na_360(nowa, dpi):.1f} cm/360°"
            self.komenda = f"sensitivity {nowa}"
            self.przycisk_kopiuj.config(state="normal")
            nowa_ocena = self.ocena_obrazu(nowa)  # whether the crosshair starts skipping pixels at the new sensitivity
            if nowa_ocena and nowa_ocena["stosunek"] > 1 and nowa_ocena["propozycja"]:
                d, s2 = nowa_ocena["propozycja"]
                pod += t(f"\nPrzy sens {nowa} celownik przeskakiwałby piksele w {self.ust['rozdzielczosc']} - "
                         f"lepiej ustaw DPI {d} i sens {s2} (ta sama czułość)",
                         f"\nAt sens {nowa} the crosshair would skip pixels at {self.ust['rozdzielczosc']} - "
                         f"better set DPI {d} and sens {s2} (same sensitivity)")
            pod += "\n" + raport.zrodla().get(w.get("zrodlo"), "")
        elif w.get("bez_zmiany") == "za_malo":
            self.etykieta_wynik.config(text=t("Za mało danych na zalecenie", "Not enough data for a recommendation"),
                                       fg=KOLOR["uwaga"])
            pod += "\n" + raport.powod_bez_zmiany(w)
        elif w.get("bez_zmiany") in ("krzywa", "niezgodne", "zapadka"):
            self.etykieta_wynik.config(text=t("Zostań przy tej czułości", "Stay on this sensitivity"), fg=KOLOR["ok"])
            pod += "\n" + raport.powod_bez_zmiany(w)
        else:
            self.etykieta_wynik.config(text=t("Czułość wygląda dobrze", "Your sensitivity looks fine"), fg=KOLOR["ok"])
            pod += t("\nBrak wyraźnego sygnału, żeby ją zmieniać.", "\nNo clear signal to change it.")
        if w["liczba"] < raport.MIN_FLICKOW and w.get("bez_zmiany") != "za_malo":
            pod += t(f"\nUwaga: tylko {w['liczba']} flicków (zalecane {raport.MIN_FLICKOW}+) - traktuj wynik ostrożnie.",
                     f"\nNote: only {w['liczba']} flicks ({raport.MIN_FLICKOW}+ recommended) - treat the result with care.")
        self.etykieta_wynik_pod.config(text=pod)
        self.przycisk_eksport.config(state="normal")

        # Score ring and the "score vs sensitivity" chart
        self.rysuj_pierscien(w["ocena"])
        self.ocena_pod.config(text=t(f"± {w.get('ocena_pm', 0)} · {w['liczba']} flicków",
                                     f"± {w.get('ocena_pm', 0)} · {w['liczba']} flicks"))
        self.punkty_wykresu = [(p["sens"], p["ocena"], False) for p in (info.get("porownanie") or [])]
        self.punkty_wykresu.append((sens, w["ocena"], True))
        self.rysuj_wykres()

        self.porady_klucze = raport.porady_z_kluczami(w) + self.porady_obrazu(ocena, sens)
        self.pokaz_porady(self.porady_klucze)

        self.szczegol(t("Gdzie kończy się Twój ruch główny", "Where your main movement ends"), "h")
        self.szczegol(t("100% = dokładnie na celu, 95% = idealnie (lekkie niedociągnięcie jest naturalne)",
                        "100% = exactly on target, 95% = ideal (slightly short is natural)"), "szary")
        self.szczegol(t(f"mediana {w['r_mediana']:.0%} (±{w['niepewnosc']:.0%})   przestrzał {w['przestrzal']:.0%}   "
                        f"w punkt {w['w_punkt']:.0%}   niedociągnięcie {w['niedociagniecie']:.0%}",
                        f"median {w['r_mediana']:.0%} (±{w['niepewnosc']:.0%})   overshoot {w['przestrzal']:.0%}   "
                        f"on target {w['w_punkt']:.0%}   undershoot {w['niedociagniecie']:.0%}"), "mono")
        if w.get("grupy"):
            self.szczegol(t("Małe, średnie i duże flicki osobno", "Small, medium and large flicks separately"), "h")
        for klucz, g in w.get("grupy", {}).items():
            self.szczegol(raport.linia_grupy(klucz, g), "mono")

        pm = w.get("ocena_pm", 0)
        self.szczegol(t(f"Ocena celowania: {w['ocena']} ± {pm}/100", f"Aim score: {w['ocena']} ± {pm}/100"), "h")
        self.szczegol(t("służy do porównywania czułości ze sobą - liczy celność, rozrzut, korekty i tempo",
                        "for comparing sensitivities - it counts accuracy, spread, corrections and pace"), "szary")
        for linia in raport.linie_oceny(w, info)[1:]:
            self.szczegol(linia, "mono")
        porownanie = raport.linie_porownania(info, sens, w["ocena"], pm)
        if porownanie:
            self.szczegol(t("Na innych czułościach (to samo DPI i rozdzielczość)",
                            "At other sensitivities (same DPI and resolution)"), "h")
            for linia in porownanie:
                self.szczegol(linia, "mono")
        if w.get("sygnaly"):
            self.szczegol(t("Sygnały", "Signals"), "h")
            for linia in raport.linie_sygnalow(w, sens):
                self.szczegol("• " + linia)
        self.wstaw_obraz(ocena)
        self.odswiez_mapy()

    # Training maps tab
    def zbuduj_mapy(self, rodzic):
        zawin(etykieta(rodzic, t("Mapy z warsztatu Steam dopasowane do wniosków z Twojego raportu. "
                                 "Link otwiera stronę mapy w warsztacie.",
                                 "Steam Workshop maps matched to the findings in your report. "
                                 "The link opens the map page in the Workshop."),
                       bg="tlo", fg="szary")).pack(anchor="w", fill="x")
        self.mapy_lista = tk.Frame(rodzic, bg=KOLOR["tlo"])
        self.mapy_lista.pack(fill="x", pady=(12, 0))
        etykieta(rodzic, t("Mapy są dodawane ręcznie przez autora programu.",
                           "Maps are added manually by the app author."),
                 bg="tlo", fg="szary", rozmiar=9).pack(anchor="w", pady=(4, 0))
        self.odswiez_mapy()

    def odswiez_mapy(self):
        if not hasattr(self, "mapy_lista"):
            return
        for w in self.mapy_lista.winfo_children():
            w.destroy()
        for mapa, tytuly in mapy.dopasuj([(p[0], p[1]) for p in self.porady_klucze]):
            zew, w = karta(self.mapy_lista, padx=18, pady=14)
            zew.pack(fill="x", pady=(0, 10))
            ttk.Button(w, text=t("Otwórz w warsztacie ↗", "Open in Workshop ↗"),
                       command=lambda m=mapa: webbrowser.open(mapy.adres(m))).pack(side="right", padx=(12, 0))
            lewa = tk.Frame(w, bg=KOLOR["panel"])
            lewa.pack(side="left", fill="x", expand=True)
            etykieta(lewa, mapa["nazwa"], rozmiar=12, gruba=True).pack(anchor="w")
            zawin(etykieta(lewa, mapa["opis"], fg="szary", rozmiar=9)).pack(anchor="w", fill="x", pady=(2, 0))
            if tytuly:
                zawin(etykieta(lewa, t("Dopasowane do raportu: ", "Matched to your report: ") + ", ".join(tytuly),
                               fg="akcent_tekst", rozmiar=9, gruba=True)).pack(anchor="w", fill="x", pady=(6, 0))

    # Settings log tab
    def zbuduj_dziennik(self, rodzic):
        zawin(etykieta(rodzic, t("SensFit zapisuje, kiedy w CS2 zmieniła się czułość lub DPI. Dzięki temu każdą "
                                 "sesję da się porównać z konkretnym ustawieniem.",
                                 "SensFit records when your sensitivity or DPI changed in CS2, so every session "
                                 "can be compared with an exact setting."),
                       bg="tlo", fg="szary")).pack(anchor="w", fill="x")
        zew, self.dziennik_wiersze = karta(rodzic, padx=20, pady=6)
        zew.pack(fill="x", pady=(12, 0))
        etykieta(self.dziennik_wiersze, t("Wczytuję…", "Loading…"), fg="szary").pack(anchor="w", pady=10)

    def odswiez_dziennik(self):
        def praca():
            try:
                self.kolejka.put(("dziennik", dziennik.statystyki()))
            except Exception:  # the log must not block the window
                self.kolejka.put(("dziennik", []))
        threading.Thread(target=praca, daemon=True).start()

    def pokaz_dziennik(self, lista):
        ramka = self.dziennik_wiersze
        for w in ramka.winfo_children():
            w.destroy()
        if not lista:
            etykieta(ramka, t("Brak wpisów. Pierwszy pojawi się po zapisaniu DPI i czułości.",
                              "No entries yet. The first one appears after you save your DPI and sensitivity."),
                     fg="szary").pack(anchor="w", pady=10)
            return
        for i, (wpis, liczba, ocena) in enumerate(lista):
            if i:
                tk.Frame(ramka, bg=KOLOR["linia"], height=1).pack(fill="x")
            wiersz = tk.Frame(ramka, bg=KOLOR["panel"])
            wiersz.pack(fill="x", pady=12)
            try:
                kiedy = datetime.fromisoformat(wpis["czas"]).strftime("%d.%m.%Y · %H:%M")
            except ValueError:
                kiedy = wpis["czas"]
            etykieta(wiersz, kiedy, fg="szary", rozmiar=9, czcionka=MONO, width=18).pack(side="left", anchor="n")
            prawa = tk.Frame(wiersz, bg=KOLOR["panel"])
            prawa.pack(side="left", fill="x", expand=True, padx=(10, 0))
            etykieta(prawa, dziennik.tytul(wpis), rozmiar=11, gruba=True).pack(anchor="w")
            opis = dziennik.opis(wpis)
            if opis:
                zawin(etykieta(prawa, opis, fg="szary", rozmiar=9)).pack(anchor="w", fill="x")
            plakietki = tk.Frame(prawa, bg=KOLOR["panel"])
            plakietki.pack(anchor="w", pady=(6, 0))
            plakietka(plakietki, dziennik.liczba_sesji_tekst(liczba)).pack(side="left", padx=(0, 6))
            if ocena is not None:
                plakietka(plakietki, t(f"ocena {ocena}", f"score {ocena}")).pack(side="left", padx=(0, 6))
            zrodlo = {"start": t("pierwsze uruchomienie", "first launch"),
                      "cs2": t("wykryto w CS2", "detected in CS2"),
                      "ustawienia": t("zmienione w Ustawieniach", "changed in Settings")}.get(wpis.get("zrodlo"))
            if zrodlo:
                plakietka(plakietki, zrodlo, dobra=True).pack(side="left")

    # Settings tab
    def zbuduj_ustawienia(self, rodzic):
        self.przelacznik_ust = Przelacznik(rodzic, [("cs", t("Ustawienia CS2", "CS2 settings")),
                                                    ("app", t("Ustawienia aplikacji", "App settings"))],
                                           "cs", self.przelacz_ustawienia)
        self.przelacznik_ust.pack(anchor="w")
        self.zakladka_ust = "cs"
        self.ust_cs = tk.Frame(rodzic, bg=KOLOR["tlo"])
        self.ust_app = tk.Frame(rodzic, bg=KOLOR["tlo"])
        self.ust_cs.pack(fill="x", pady=(12, 0))
        self.zbuduj_ustawienia_cs2(self.ust_cs)
        self.zbuduj_ustawienia_aplikacji(self.ust_app)

    def przelacz_ustawienia(self, klucz):
        self.zakladka_ust = klucz
        self.przelacznik_ust.wybierz(klucz)
        pokaz, ukryj = (self.ust_app, self.ust_cs) if klucz == "app" else (self.ust_cs, self.ust_app)
        ukryj.pack_forget()
        pokaz.pack(fill="x", pady=(12, 0))

    def pokaz_ustawienia_cs2(self):
        self.zakladki.select("set")
        self.przelacz_ustawienia("cs")

    def wiersz_formularza(self, siatka, nr, tytul, opis=""):
        """A row with the description on the left and the control on the right. Returns the frame for the control."""
        lewa = tk.Frame(siatka, bg=KOLOR["panel"])
        lewa.grid(row=nr, column=0, sticky="w", pady=8)
        etykieta(lewa, tytul, gruba=True).pack(anchor="w")
        if opis:
            etykieta(lewa, opis, fg="szary", rozmiar=9, wraplength=300).pack(anchor="w")
        prawa = tk.Frame(siatka, bg=KOLOR["panel"])
        prawa.grid(row=nr, column=1, sticky="e", pady=8, padx=(16, 0))
        lewa.linia = None
        if nr:
            lewa.linia = tk.Frame(siatka, bg=KOLOR["linia"], height=1)
            lewa.linia.grid(row=nr, column=0, columnspan=2, sticky="new")
        return lewa, prawa

    def zbuduj_ustawienia_cs2(self, rodzic):
        zew, f = karta(rodzic, padx=20, pady=8)
        zew.pack(fill="x")
        siatka = tk.Frame(f, bg=KOLOR["panel"])
        siatka.pack(fill="x")
        siatka.columnconfigure(0, weight=1)

        _l, p = self.wiersz_formularza(siatka, 0, t("DPI myszki", "Mouse DPI"),
                                       t("z programu producenta myszki (G Hub, Synapse…)",
                                         "from the mouse software (G Hub, Synapse…)"))
        self.pole_dpi = ttk.Entry(p, width=14)
        self.pole_dpi.pack(side="right")

        _l, p = self.wiersz_formularza(siatka, 1, t("Czułość w CS2", "CS2 sensitivity"))
        ttk.Button(p, text=t("Odczytaj z CS2", "Read from CS2"), command=self.odczytaj_sens).pack(side="right")
        self.pole_sens = ttk.Entry(p, width=14)
        self.pole_sens.pack(side="right", padx=(0, 8))

        _l, p = self.wiersz_formularza(siatka, 2, t("Proporcje ekranu", "Aspect ratio"),
                                       t("proporcje obrazu w grze (ustawienie wideo CS2)",
                                         "aspect ratio of the game picture (CS2 video setting)"))
        self.pole_proporcje = ttk.Combobox(p, width=12, state="readonly", values=rozdz.PROPORCJE)
        self.pole_proporcje.pack(side="right")
        self.pole_proporcje.bind("<<ComboboxSelected>>", lambda _e: self.po_zmianie_proporcji())

        self.wiersz_skalowania = self.wiersz_formularza(
            siatka, 3, t("Skalowanie obrazu", "Picture scaling"),
            t("gdy proporcje gry są inne niż monitora", "when the game aspect ratio differs from the monitor"))
        self.pole_skalowanie = Przelacznik(self.wiersz_skalowania[1],
                                           [("rozciagniete", t("rozciągnięty", "stretched")),
                                            ("paski", t("czarne paski", "black bars"))],
                                           "paski" if self.ust.get("skalowanie") == "paski" else "rozciagniete")
        self.pole_skalowanie.pack(side="right")

        _l, p = self.wiersz_formularza(siatka, 4, t("Rozdzielczość w CS2", "CS2 resolution"),
                                       t("monitor: ", "monitor: ") + (self.ust.get("monitor") or "?").replace("x", "×")
                                       + t(" (wykryty z Windows)", " (detected from Windows)"))
        ttk.Button(p, text=t("Odczytaj z CS2", "Read from CS2"), command=self.odczytaj_rozdz).pack(side="right")
        self.pole_rozdz = ttk.Combobox(p, width=14, state="readonly")
        self.pole_rozdz.pack(side="right", padx=(0, 8))
        self.pole_rozdz.bind("<<ComboboxSelected>>", lambda _e: self.po_zmianie_rozdz(True))
        # The field for a custom resolution appears to the left of the list when "Custom" is chosen
        self.pole_wlasna = ttk.Entry(p, width=12)

        _l, p = self.wiersz_formularza(siatka, 5, "")
        ttk.Button(p, text=t("Zapisz", "Save"), style="AkcentMaly.TButton",
                   command=self.zapisz_ustawienia).pack(side="right")
        self.info_ustawien = etykieta(_l, fg="szary", rozmiar=9)
        self.info_ustawien.pack(anchor="w")
        zawin(self.info_ustawien)

        for pole, klucz in ((self.pole_dpi, "dpi"), (self.pole_sens, "sens")):
            if self.ust.get(klucz):
                pole.insert(0, str(self.ust[klucz]))
        self.wypelnij_obraz()

        self.info_obrazu = zawin(etykieta(rodzic, bg="tlo", fg="szary", rozmiar=9, czcionka=MONO))
        self.info_obrazu.pack(anchor="w", fill="x", pady=(8, 0))
        self.odswiez_ocene_obrazu()

        zew, g = karta(rodzic, padx=20, pady=14)
        zew.pack(fill="x", pady=(12, 0))
        etykieta(g, t("Połączenie z CS2 (plik GSI)", "Connection to CS2 (GSI file)"), rozmiar=11, gruba=True).pack(anchor="w")
        self.etykieta_folder = zawin(etykieta(g, fg="szary", rozmiar=9))
        self.etykieta_folder.pack(anchor="w", fill="x", pady=(4, 0))
        self.etykieta_plik_gsi = zawin(etykieta(g, fg="szary", rozmiar=9))
        self.etykieta_plik_gsi.pack(anchor="w", fill="x", pady=(2, 0))
        self.etykieta_wartosci_cs2 = zawin(etykieta(g, fg="szary", rozmiar=9))
        self.etykieta_wartosci_cs2.pack(anchor="w", fill="x", pady=(2, 10))
        rzad = tk.Frame(g, bg=KOLOR["panel"])
        rzad.pack(anchor="w")
        ttk.Button(rzad, text=t("Zainstaluj plik GSI", "Install GSI file"),
                   command=self.instaluj_gsi).pack(side="left", padx=(0, 8))
        ttk.Button(rzad, text=t("Wybierz folder CS2…", "Choose CS2 folder…"),
                   command=self.wybierz_folder).pack(side="left")
        self.odswiez_folder()

    def wypelnij_obraz(self):
        """Sets the aspect ratio and resolution lists according to self.ust."""
        if not hasattr(self, "pole_proporcje"):
            return
        prop = self.ust.get("proporcje") if self.ust.get("proporcje") in rozdz.PROPORCJE else "16:9"
        self.pole_proporcje.set(prop)
        self.ustaw_liste_rozdz(prop, self.ust.get("rozdzielczosc"))
        self.pokaz_skalowanie()

    def ustaw_liste_rozdz(self, prop, wybrana=None):
        lista = rozdz.rozdzielczosci_dla(prop)
        self.pole_rozdz.config(values=lista + [t("Niestandardowa", "Custom")])
        self.pole_wlasna.delete(0, "end")
        if wybrana in lista:
            self.pole_rozdz.set(wybrana)
        elif wybrana:
            self.pole_rozdz.set(t("Niestandardowa", "Custom"))
            self.pole_wlasna.insert(0, wybrana)
        else:  # default for the ratio: 1920 wide or 1080 high, otherwise the first one in the list
            domyslna = next((r for r in lista if r.startswith("1920x")), None) or \
                next((r for r in lista if r.endswith("x1080")), None) or lista[0]
            self.pole_rozdz.set(domyslna)
        self.po_zmianie_rozdz()

    def po_zmianie_proporcji(self):
        self.ustaw_liste_rozdz(self.pole_proporcje.get())
        self.pokaz_skalowanie()

    def po_zmianie_rozdz(self, fokus=False):
        wlasna = self.pole_rozdz.get() == t("Niestandardowa", "Custom")
        if wlasna:
            self.pole_wlasna.pack(side="right", padx=(0, 8))  # to the left of the list
            if fokus:
                self.pole_wlasna.focus_set()
        else:
            self.pole_wlasna.pack_forget()

    def pokaz_skalowanie(self):
        widoczne = self.pole_proporcje.get() != self.proporcje_monitora()
        for w in (*self.wiersz_skalowania, self.wiersz_skalowania[0].linia):
            if widoczne:
                w.grid()
            else:
                w.grid_remove()

    def wybrana_rozdz(self):
        if self.pole_rozdz.get() == t("Niestandardowa", "Custom"):
            return rozdz.parsuj(self.pole_wlasna.get())
        return rozdz.parsuj(self.pole_rozdz.get())

    def zbuduj_ustawienia_aplikacji(self, rodzic):
        zew, f = karta(rodzic, padx=20, pady=8)
        zew.pack(fill="x")
        siatka = tk.Frame(f, bg=KOLOR["panel"])
        siatka.pack(fill="x")
        siatka.columnconfigure(0, weight=1)

        _l, p = self.wiersz_formularza(siatka, 0, t("Język", "Language"),
                                       t("Język programu i raportów. Przy pierwszym uruchomieniu wybierany z języka "
                                         "systemu: polski → PL, każdy inny → EN.",
                                         "Language of the app and reports. On first launch it follows the system "
                                         "language: Polish → PL, anything else → EN."))
        _l.winfo_children()[-1].config(wraplength=430)
        Przelacznik(p, [("pl", "PL"), ("en", "EN")], jezyk.JEZYK, self.zmien_jezyk).pack(side="right")

        _l, p = self.wiersz_formularza(siatka, 1, t("Motyw", "Theme"),
                                       t("Ciemny jak HUD w grze albo jasny.", "Dark like the in-game HUD, or light."))
        Przelacznik(p, [("ciemny", t("Ciemny", "Dark")), ("jasny", t("Jasny", "Light"))],
                    MOTYW, self.zmien_motyw).pack(side="right")

        _l, p = self.wiersz_formularza(siatka, 2, t("Aktualizacje", "Updates"),
                                       t("Sprawdzane przy starcie. Pobieranie zawsze wymaga Twojego potwierdzenia.",
                                         "Checked at start-up. Downloading always needs your confirmation."))
        self.przycisk_akt_ust = ttk.Button(p, command=self.klik_aktualizuj)
        self.przycisk_akt_ust.pack(side="right")

        _l, p = self.wiersz_formularza(siatka, 3, t("Dane programu", "Program data"), r"%APPDATA%\SensFit")
        ttk.Button(p, text=t("Otwórz folder z danymi", "Open data folder"),
                   command=self.otworz_folder).pack(side="right")

        _l, p = self.wiersz_formularza(siatka, 4, t("Skrót nagrywania", "Recording shortcut"))
        self.etykieta_skrotu_ust = etykieta(_l, fg="szary", rozmiar=9, wraplength=330)
        self.etykieta_skrotu_ust.pack(anchor="w")
        ttk.Button(p, text=t("Wyłącz", "Turn off"), command=self.wylacz_skrot).pack(side="right")
        self.przycisk_skrotu = ttk.Button(p, text=t("Zmień klawisz", "Change key"), command=self.zmien_skrot)
        self.przycisk_skrotu.pack(side="right", padx=(0, 8))
        self.odswiez_skrot()

        if self.uzytkownik.get("nazwa"):
            _l, p = self.wiersz_formularza(siatka, 5, f"Discord: {self.uzytkownik['nazwa']}")
            ttk.Button(p, text=t("Wyloguj", "Log out"), command=self.wyloguj).pack(side="right")

    # Hotkey
    def opis_skrotu(self):
        ust = self.ust.get("skrot")
        if not ust:
            return t("Skrót klawiszowy wyłączony (Ustawienia → Ustawienia aplikacji)",
                     "Keyboard shortcut off (Settings → App settings)")
        if self.skrot.blad:
            return t(f"Skrót {ust['nazwa']} nie działa: {self.skrot.blad}. Wybierz inny klawisz w Ustawieniach.",
                     f"Shortcut {ust['nazwa']} does not work: {self.skrot.blad}. Choose another key in Settings.")
        return t(f"Skrót: {ust['nazwa']} - rozpoczyna i kończy nagrywanie, także w trakcie gry (z sygnałem dźwiękowym)",
                 f"Shortcut: {ust['nazwa']} - starts and stops recording, also during a game (with a beep)")

    def odswiez_skrot(self):
        for nazwa in ("etykieta_skrotu", "etykieta_skrotu_ust"):
            lbl = getattr(self, nazwa, None)
            if lbl is not None and lbl.winfo_exists():
                lbl.config(text=self.opis_skrotu(), fg=KOLOR["zle" if self.skrot.blad else "szary"])

    def klik_skrotu(self):
        """Hotkey press: does the same as the Start/Stop button, plus a sound (the player cannot see the window)."""
        przed = self.nagrywanie
        if przed or self.przycisk_start.instate(["!disabled"]):
            self.start_stop()
        if self.nagrywanie != przed:
            dzwiek(1000 if self.nagrywanie else 600, 2 if not self.nagrywanie else 1)
        else:
            dzwiek(None)  # it did not work (for example no DPI), and the message waits in the program window

    def zmien_skrot(self):
        """Waits for a key press in the program window. Esc cancels."""
        self.skrot.zatrzymaj()  # otherwise the current hotkey would not reach the window
        self.wybieram_skrot = True
        self.przycisk_skrotu.config(text=t("Naciśnij klawisz… (Esc = anuluj)", "Press a key… (Esc = cancel)"))
        self.root.bind("<KeyPress>", self.wybrano_skrot)
        self.root.focus_force()

    def wybrano_skrot(self, e):
        self.root.unbind("<KeyPress>")
        self.wybieram_skrot = False
        if e.keysym != "Escape" and e.keycode not in skrot.ZAKAZANE:
            nazwa = e.keysym.upper() if len(e.keysym) == 1 else e.keysym
            self.ust["skrot"] = {"nazwa": nazwa, "vk": e.keycode}  # on Windows keycode is the virtual-key code
            self.zapisz_cicho()
        self.skrot.ustaw((self.ust["skrot"] or {}).get("vk"))
        self.przycisk_skrotu.config(text=t("Zmień klawisz", "Change key"))
        self.odswiez_skrot()

    def wylacz_skrot(self):
        self.ust["skrot"] = None
        self.zapisz_cicho()
        self.skrot.ustaw(None)
        self.odswiez_skrot()

    def zmien_jezyk(self, kod):
        if kod == jezyk.JEZYK:
            return
        jezyk.ustaw(kod)
        self.ust["jezyk"] = kod
        self.zapisz_cicho()
        if self.akt_stan == "dostepna":
            self.sprawdz_aktualizacje()  # list of changes in the new language
        self.przebuduj()

    def zmien_motyw(self, nazwa):
        if nazwa == MOTYW:
            return
        ustaw_motyw(nazwa)
        self.ust["motyw"] = nazwa
        self.zapisz_cicho()
        self.przebuduj()

    def zapisz_cicho(self):
        try:
            kfg.zapisz_ustawienia(self.ust)
        except OSError:
            pass

    # Help tab
    def zbuduj_pomoc(self, rodzic):
        self.przelacznik_pomocy = Przelacznik(rodzic, [("help", t("Pomoc", "Help")), ("contact", t("Kontakt", "Contact"))],
                                              "help", self.przelacz_pomoc)
        self.przelacznik_pomocy.pack(anchor="w")
        self.pomoc = tk.Frame(rodzic, bg=KOLOR["tlo"])
        self.kontakt = tk.Frame(rodzic, bg=KOLOR["tlo"])
        self.pomoc.pack(fill="x", pady=(12, 0))
        self.zbuduj_pomoc_tekst(self.pomoc)
        self.zbuduj_kontakt(self.kontakt)

    def przelacz_pomoc(self, klucz):
        pokaz, ukryj = (self.kontakt, self.pomoc) if klucz == "contact" else (self.pomoc, self.kontakt)
        ukryj.pack_forget()
        pokaz.pack(fill="x", pady=(12, 0))

    def zbuduj_pomoc_tekst(self, rodzic):
        zew, c = karta(rodzic, padx=22, pady=14)
        zew.pack(fill="x")
        tresc = [
            (t("Pierwsze uruchomienie", "First launch"),
             t("1. Ustawienia → Ustawienia CS2 → wpisz DPI myszki i kliknij Zapisz. Czułość program odczyta sam z CS2.\n"
               "2. Kliknij „Zainstaluj plik GSI”, a potem uruchom CS2 ponownie.",
               "1. Settings → CS2 settings → enter your mouse DPI and click Save. The app reads your sensitivity "
               "from CS2 by itself.\n2. Click “Install GSI file”, then restart CS2.")),
            (t("Nagrywanie", "Recording"),
             t("3. Nagrywanie → Rozpocznij nagrywanie. Zielona kropka przy „CS2” oznacza, że gra wysyła dane.\n"
               "4. Graj 20–30 min (deathmatch, karabin lub pistolet). Status NAGRYWAM pojawia się, gdy żyjesz i "
               "trzymasz broń.\n5. Wróć do SensFit i kliknij „Zakończ i analizuj”.",
               "3. Recording → Start recording. A green dot next to “CS2” means the game is sending data.\n"
               "4. Play 20–30 min (deathmatch, rifle or pistol). RECORDING shows while you are alive and holding "
               "a weapon.\n5. Come back to SensFit and click “Stop and analyse”.")),
            (t("Wyniki", "Results"),
             t("Zalecenie mówi, czy zmienić czułość. Kliknij „Kopiuj komendę”, w CS2 otwórz konsolę (~) i wklej. "
               "Graj na nowej czułości 3–4 dni, potem nagraj nową sesję. Kolejne sesje na tym samym eDPI są "
               "łączone, więc wynik jest coraz dokładniejszy. „Eksportuj raport” zapisuje wynik jako obrazek "
               "PNG albo plik tekstowy.",
               "The recommendation says whether to change your sensitivity. Click “Copy command”, open the console "
               "in CS2 (~) and paste. Play on the new sensitivity for 3–4 days, then record a new session. Sessions "
               "on the same eDPI are combined, so the result gets more accurate. “Export report” saves the result "
               "as a PNG image or a text file.")),
            (t("Jak program ocenia", "How the app scores you"),
             t("Flicki zakończone zabójstwem (dane z GSI) liczą się potrójnie, a te, w których śledziłeś ruchomy "
               "cel - w połowie. Ruch w trakcie serii (kontrola odrzutu) jest pomijany. Podnoszenie myszy w trakcie "
               "obrotu wskazuje na za niską czułość, a drżenie celownika na za wysoką. Ocena celowania (0–100) "
               "pozwala porównać różne czułości.",
               "Flicks that end in a kill (GSI data) count three times, and those where you tracked a moving target "
               "count half. Movement during a spray (recoil control) is skipped. Lifting the mouse mid-turn points to "
               "a sensitivity that is too low, and crosshair shake to one that is too high. The aim score (0–100) "
               "lets you compare sensitivities.")),
            (t("Dziennik ustawień", "Settings log"),
             t("Program sam zapisuje każdą zmianę czułości (z plików CS2) i DPI (z Ustawień). Jeśli eDPI się nie "
               "zmieniło (np. 400 DPI × 2.4 → 800 DPI × 1.2), sesje liczą się razem.",
               "The app records every change of sensitivity (from the CS2 files) and DPI (from Settings). If eDPI "
               "did not change (e.g. 400 DPI × 2.4 → 800 DPI × 1.2), sessions are counted together.")),
            (t("Rozdzielczość", "Resolution"),
             t("cm/360 w CS2 nie zależy od rozdzielczości. Zmienia się pole widzenia i - przy obrazie 4:3 "
               "rozciągniętym - szybkość, z jaką obraz przesuwa się w poziomie. Wybierz proporcje i rozdzielczość "
               "w Ustawieniach CS2; monitor program wykrywa sam. Sesje z różnych rozdzielczości są liczone osobno.",
               "cm/360 in CS2 does not depend on resolution. The field of view changes and, with a stretched 4:3 "
               "picture, so does how fast the picture moves horizontally. Choose the aspect ratio and resolution in "
               "CS2 settings; the app detects your monitor by itself. Sessions at different resolutions are counted "
               "separately.")),
            (t("Problemy", "Problems"),
             t("Czerwona kropka przy CS2: plik GSI nie jest zainstalowany albo gra nie była zrestartowana. "
               "Jeśli program nie znalazł gry, wskaż folder „Counter-Strike Global Offensive” przyciskiem "
               "„Wybierz folder CS2”. Program nie czyta pamięci gry i nic do niej nie wysyła - korzysta z "
               "oficjalnej funkcji GSI od Valve. Inne pytania: Pomoc → Kontakt.",
               "Red dot next to CS2: the GSI file is not installed or the game was not restarted. If the app did not "
               "find the game, choose the “Counter-Strike Global Offensive” folder with “Choose CS2 folder”. The app "
               "does not read game memory and sends nothing to the game - it uses Valve's official GSI feature. "
               "Other questions: Help → Contact.")),
        ]
        for i, (naglowek, akapit) in enumerate(tresc):
            etykieta(c, naglowek, fg="akcent_tekst", rozmiar=11, gruba=True).pack(anchor="w", pady=(12 if i else 0, 2))
            zawin(etykieta(c, akapit)).pack(anchor="w", fill="x")
        etykieta(c, f"SensFit {WERSJA}", fg="szary", rozmiar=9).pack(anchor="w", pady=(14, 0))

    def zbuduj_kontakt(self, rodzic):
        zew, c = karta(rodzic, padx=22, pady=16)
        zew.pack(fill="x")
        etykieta(c, t("Pytania i zgłaszanie problemów", "Questions and problem reports"), rozmiar=15,
                 gruba=True, fg="mocny").pack(anchor="w")
        zawin(etykieta(c, t("Masz pytanie albo coś nie działa? Napisz na serwerze Discord SensFit. Odpowiada autor "
                            "programu i inni testerzy.",
                            "Have a question or something doesn't work? Write on the SensFit Discord server. The "
                            "author and other testers answer."), fg="szary")).pack(anchor="w", fill="x", pady=(2, 12))
        ttk.Button(c, text=t("Dołącz do serwera Discord ↗", "Join the Discord server ↗"), style="AkcentMaly.TButton",
                   command=lambda: webbrowser.open(DISCORD)).pack(anchor="w")
        etykieta(c, DISCORD.replace("https://", ""), rozmiar=9, czcionka=MONO).pack(anchor="w", pady=(10, 0))
        zawin(etykieta(c, t("Po wejściu wybierz język (Polski albo English), żeby zobaczyć kanały.",
                            "After joining, pick your language (Polski or English) to see the channels."),
                       fg="szary", rozmiar=9)).pack(anchor="w", fill="x")

        kafle = tk.Frame(rodzic, bg=KOLOR["tlo"])
        kafle.pack(fill="x", pady=(14, 0))
        for i in range(3):
            kafle.columnconfigure(i, weight=1, uniform="kontakt")
        for i, (tytul, opis) in enumerate((
                (t("Pytania", "Questions"),
                 t("Kanał #ogólny albo #faq: jak coś ustawić lub zrozumieć wynik.",
                   "Channel #general or #faq: how to set something up or understand a result.")),
                (t("Zgłoszenie błędu", "Bug report"),
                 t("Forum #bugi (dla testerów): opisz, co się stało, i dołącz plik z danymi.",
                   "Forum #bug-reports (testers): describe what happened and attach the data file.")),
                (t("Wyniki testów", "Test results"),
                 t("Forum #wyniki-testów (dla testerów): wklej raport i napisz, czy zalecenie pasowało.",
                   "Forum #test-results (testers): paste your report and say whether the recommendation felt right.")))):
            zew, w = karta(kafle, padx=14, pady=12)
            zew.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
            etykieta(w, tytul, gruba=True).pack(anchor="w")
            zawin(etykieta(w, opis, fg="szary", rozmiar=9)).pack(anchor="w", fill="x", pady=(4, 0))

        zew, a = karta(rodzic, padx=22, pady=14)
        zew.pack(fill="x", pady=(14, 0))
        nadtytul(a, t("Przy zgłoszeniu dołącz", "Attach to your report")).pack(anchor="w")
        for punkt in (t("plik ostatni_raport.txt (przycisk poniżej)", "the ostatni_raport.txt file (button below)"),
                      t(f"wersję programu: {WERSJA}", f"app version: {WERSJA}"),
                      t("wersję Windows i opis, co się stało", "Windows version and what happened")):
            etykieta(a, "•  " + punkt).pack(anchor="w", pady=(4, 0))
        rzad = tk.Frame(a, bg=KOLOR["panel"])
        rzad.pack(anchor="w", pady=(12, 0))
        ttk.Button(rzad, text=t("Otwórz folder z danymi", "Open data folder"),
                   command=self.otworz_folder).pack(side="left", padx=(0, 8))
        self.przycisk_dane = ttk.Button(rzad, text=t("Kopiuj dane do zgłoszenia", "Copy details for the report"),
                                        command=self.kopiuj_dane_zgloszenia)
        self.przycisk_dane.pack(side="left")

    def kopiuj_dane_zgloszenia(self):
        tekst = f"SensFit {WERSJA}, {opis_windows()}, " + t("język", "language") + f": {jezyk.JEZYK.upper()}"
        self.root.clipboard_clear()
        self.root.clipboard_append(tekst)
        self.przycisk_dane.config(text=t("Skopiowano dane do zgłoszenia.", "Report details copied."))
        self.root.after(3000, lambda: self.przycisk_dane.winfo_exists() and self.przycisk_dane.config(
            text=t("Kopiuj dane do zgłoszenia", "Copy details for the report")))

    # Refreshing the views
    def odswiez_naglowek(self):
        sens, dpi = self.ust["sens"], self.ust["dpi"]
        if sens and dpi:
            self.naglowek.config(text=f"sens {sens} · {dpi} DPI · eDPI {kfg.edpi(sens, dpi):.0f} · "
                                      f"{kfg.cm_na_360(sens, dpi):.1f} cm/360°")
        else:
            self.naglowek.config(text=t("uzupełnij ustawienia", "fill in your settings"))

    def odswiez_statusy(self):
        if self.mysz_ok:
            self.ustaw_status(self.status_mysz, True, t("Odczyt myszy działa", "Mouse input works"))
        else:
            self.ustaw_status(self.status_mysz, False, t("Odczyt myszy nie działa: ", "Mouse input does not work: ")
                              + str(self.nagrywacz.blad))

        if kfg.gsi_zainstalowane(self.ust["folder_cfg"]):
            self.ustaw_status(self.status_gsi, True, t("Plik GSI zainstalowany w CS2", "GSI file installed in CS2"))
        else:
            self.ustaw_status(self.status_gsi, False, t("Plik GSI nie jest zainstalowany - zakładka Ustawienia",
                                                        "GSI file is not installed - see the Settings tab"))

        if self.blad_gsi:
            self.ustaw_status(self.status_cs2, False, self.blad_gsi)
        elif self.cs2_polaczone():
            self.ustaw_status(self.status_cs2, True, t("CS2 wysyła dane", "CS2 is sending data"))
        elif self.cs2_dziala and kfg.gsi_zainstalowane(self.ust["folder_cfg"]):
            self.ustaw_status(self.status_cs2, False, t(
                "CS2 działa, ale nie wysyła danych - uruchom grę ponownie (plik GSI wczytuje się tylko przy starcie). "
                "Jeśli to nie pomoże, sprawdź ścieżkę pliku GSI w Ustawieniach.",
                "CS2 is running but sends no data - restart the game (the GSI file is only loaded at start). "
                "If that does not help, check the GSI file path in Settings."))
        else:
            self.ustaw_status(self.status_cs2, None, t("Brak sygnału z CS2 - uruchom grę (po instalacji pliku: restart)",
                                                       "No signal from CS2 - start the game (restart it after "
                                                       "installing the file)"))

        if self.blad_gsi:
            self.kropka_menu.config(fg=KOLOR["zle"])
            self.tekst_menu.config(text=t("CS2: błąd portu", "CS2: port error"))
        elif self.cs2_polaczone():
            self.kropka_menu.config(fg=KOLOR["ok"])
            self.tekst_menu.config(text=t("CS2 wysyła dane", "CS2 is sending data"))
        else:
            self.kropka_menu.config(fg=KOLOR["uwaga"])
            self.tekst_menu.config(text=t("CS2: brak sygnału", "CS2: no signal"))

        if self.nagrywanie and self.czy_nagrywac():
            self.etykieta_stan.config(text=t("● NAGRYWAM", "● RECORDING"), fg=KOLOR["ok"])
            self.etykieta_powod.config(text=t("ruch myszy jest zapisywany", "mouse movement is being recorded")
                                       if self.bez_gsi else self.stan.powod)
        elif self.nagrywanie:
            self.etykieta_stan.config(text=t("❚❚ PAUZA", "❚❚ PAUSED"), fg=KOLOR["uwaga"])
            self.etykieta_powod.config(text=self.stan.powod)
        else:
            self.etykieta_stan.config(text=t("Gotowy do nagrywania", "Ready to record"), fg=KOLOR["tekst"])
            self.etykieta_powod.config(text="")
        minuty, sekundy = divmod(int(self.czas_gry_s), 60)
        self.licznik_czas.config(text=f"{minuty}:{sekundy:02d}")
        self.licznik_strzaly.config(text=str(len(self.nagrywacz.klikniecia)))
        self.licznik_zabojstw.config(text=str(len(self.stan.zabojstwa)))
        self.licznik_flickow.config(text=f"{self.liczba_flickow}/{CEL_FLICKOW}",
                                    fg=KOLOR["ok" if self.liczba_flickow >= CEL_FLICKOW else "tekst"])

    def odswiez_folder(self):
        folder = self.ust["folder_cfg"]
        self.etykieta_folder.config(text=t("Folder CS2: ", "CS2 folder: ") + folder if folder else
                                    t("Nie znaleziono folderu CS2 - wskaż go ręcznie.",
                                      "CS2 folder not found - choose it manually."))
        plik = kfg.plik_gsi(folder)
        self.etykieta_plik_gsi.config(text=(t("Plik GSI: ", "GSI file: ") + plik + "  " + (
            t("(jest)", "(present)") if kfg.gsi_zainstalowane(folder) else t("(brak)", "(missing)"))) if plik else "")
        self.etykieta_wartosci_cs2.config(text=t("Ustawienia myszy w CS2: ", "CS2 mouse settings: ") + kfg.opis_cs2())

    def pokaz_info_ustawien(self, tekst, rodzaj="ok"):
        self.info_ustawien.config(text=tekst, fg=KOLOR[rodzaj])

    def odswiez_ocene_obrazu(self):
        """Summary of the resolution effect under the form in the CS2 settings."""
        if not hasattr(self, "info_obrazu"):
            return
        o = self.ocena_obrazu() if self.ust.get("sens") and self.ust.get("dpi") else None
        self.info_obrazu.config(text="\n".join(rozdz.opis(o)) if o else "")

    # Updates
    def sprawdz_aktualizacje(self, recznie=False):
        self.akt_stan, self.akt_recznie = "sprawdzam", recznie
        self.odswiez_aktualizacje_widok()

        def praca():
            try:
                self.kolejka.put(("aktualizacja", aktualizacja.sprawdz(), None))
            except aktualizacja.BladAktualizacji as e:
                self.kolejka.put(("aktualizacja", None, str(e)))
            except Exception as e:  # must not block the program
                self.kolejka.put(("aktualizacja", None, str(e)))
        threading.Thread(target=praca, daemon=True).start()

    def po_sprawdzeniu(self, info, blad):
        recznie = self.akt_recznie
        self.akt_recznie = False
        if blad:
            self.akt_stan, self.akt_info = "blad", None
            if recznie:
                messagebox.showwarning("SensFit", t("Nie udało się sprawdzić aktualizacji.\n\n",
                                                    "Could not check for updates.\n\n") + blad)
        elif info:
            self.akt_stan, self.akt_info = "dostepna", info
            if recznie:
                self.otworz_aktualizacje()
        else:
            self.akt_stan, self.akt_info = "aktualna", None
            if recznie:
                messagebox.showinfo("SensFit", t("Masz najnowszą wersję.", "You have the latest version."))
        self.odswiez_aktualizacje_widok()

    def odswiez_aktualizacje_widok(self):
        if not hasattr(self, "przycisk_akt"):
            return
        if self.akt_stan == "dostepna":
            tekst, styl = t("Aktualizuj", "Update") + f" · {self.akt_info['wersja']}", "AkcentMaly.TButton"
        elif self.akt_stan == "sprawdzam":
            tekst, styl = t("Sprawdzam…", "Checking…"), "TButton"
        else:
            tekst, styl = t("Sprawdź aktualizacje", "Check for updates"), "TButton"
        stan = "disabled" if self.akt_stan == "sprawdzam" else "normal"
        for p in (self.przycisk_akt, getattr(self, "przycisk_akt_ust", None)):
            if p is not None and p.winfo_exists():
                p.config(text=tekst, state=stan)
                ustaw_styl_przycisku(p, styl)
        if self.akt_stan == "dostepna" and not self.baner_ukryty:
            self.baner_tekst.config(text=t("Dostępna nowa wersja ", "A new version is available: ") + self.akt_info["wersja"])
            self.baner.pack(fill="x", padx=(24, 24), pady=(12, 0), before=self.tresc)
        else:
            self.baner.pack_forget()

    def ukryj_baner(self):
        self.baner_ukryty = True
        self.odswiez_aktualizacje_widok()

    def klik_aktualizuj(self):
        if self.akt_stan == "dostepna":
            self.otworz_aktualizacje()
        elif self.akt_stan != "sprawdzam":
            self.sprawdz_aktualizacje(recznie=True)

    def otworz_aktualizacje(self):
        if self.akt_info:
            OknoAktualizacji(self, self.akt_info)

    # Export
    def otworz_eksport(self):
        if self.ostatni and self.ostatni[0] and "r_mediana" in self.ostatni[0]:
            OknoEksportu(self)

    # Button actions
    def zapisz_ustawienia(self):
        try:
            dpi = int(float(self.pole_dpi.get().replace(",", ".")))
            sens = round(float(self.pole_sens.get().replace(",", ".")), 4)
            if not (50 <= dpi <= 50000 and 0.01 <= sens <= 20):
                raise ValueError
        except ValueError:
            self.pokaz_info_ustawien(t("DPI musi być liczbą 50–50000, a czułość liczbą 0.01–20 (np. 1.25).",
                                       "DPI must be a number 50–50000 and sensitivity a number 0.01–20 (e.g. 1.25)."),
                                     "zle")
            return
        gra = self.wybrana_rozdz()
        if not gra:
            self.pokaz_info_ustawien(t("Rozdzielczość wpisz jako szerokość x wysokość, np. 1600x900.",
                                       "Enter the resolution as width x height, e.g. 1600x900."), "zle")
            self.pole_wlasna.focus_set()
            return
        self.ust["dpi"], self.ust["sens"] = dpi, sens
        self.ust["rozdzielczosc"] = f"{gra[0]}x{gra[1]}"
        self.ust["proporcje"] = self.pole_proporcje.get()
        self.ust["skalowanie"] = self.pole_skalowanie.wybrana
        try:
            kfg.zapisz_ustawienia(self.ust)
        except OSError as e:
            self.pokaz_info_ustawien(t("Nie udało się zapisać: ", "Could not save: ") + str(e), "zle")
            return
        dziennik.zanotuj(sens, dpi, "ustawienia")
        self.pokaz_info_ustawien(t("Zapisano.", "Saved."), "ok")
        self.odswiez_naglowek()
        self.odswiez_ocene_obrazu()
        self.uruchom_analize()

    def odczytaj_rozdz(self):
        gra = rozdz.odczytaj_z_cs2(kfg.folder_steam())
        if gra is None:
            self.pokaz_info_ustawien(t("Nie znaleziono ustawień wideo CS2 - wybierz rozdzielczość z listy "
                                       "albo wpisz własną (Niestandardowa).",
                                       "CS2 video settings not found - pick a resolution from the list "
                                       "or enter your own (Custom)."), "uwaga")
            return
        nazwa = rozdz.proporcje_nazwa(*gra)
        if nazwa in rozdz.PROPORCJE:
            self.pole_proporcje.set(nazwa)
        self.ustaw_liste_rozdz(self.pole_proporcje.get(), f"{gra[0]}x{gra[1]}")
        self.pokaz_skalowanie()
        self.pokaz_info_ustawien(t(f"Odczytano z CS2: {gra[0]}x{gra[1]}. Kliknij Zapisz.",
                                   f"Read from CS2: {gra[0]}x{gra[1]}. Click Save."), "ok")

    def odczytaj_sens(self):
        sens = kfg.odczytaj_sens_z_cs2()
        if sens is None:
            self.pokaz_info_ustawien(t("Nie znaleziono ustawień CS2 - wpisz czułość ręcznie.",
                                       "CS2 settings not found - enter your sensitivity manually."), "uwaga")
            return
        self.pole_sens.delete(0, "end")
        self.pole_sens.insert(0, str(sens))
        self.pokaz_info_ustawien(t(f"Odczytano z CS2: {sens}. Kliknij Zapisz.", f"Read from CS2: {sens}. Click Save."), "ok")

    def instaluj_gsi(self):
        ok, komunikat = kfg.zainstaluj_gsi(self.ust["folder_cfg"])
        self.pokaz_info_ustawien(komunikat, "ok" if ok else "zle")
        self.odswiez_folder()

    def wybierz_folder(self):
        wybrany = filedialog.askdirectory(title=t("Wskaż folder Counter-Strike Global Offensive",
                                                  "Choose the Counter-Strike Global Offensive folder"))
        if not wybrany:
            return
        cfg = kfg.popraw_folder_cs2(wybrany)
        if not cfg:
            self.pokaz_info_ustawien(t("W tym folderze nie ma CS2. Wskaż folder „Counter-Strike Global "
                                       "Offensive” (w Steam: PPM na CS2 → Zarządzaj → Przeglądaj pliki lokalne).",
                                       "CS2 is not in this folder. Choose the “Counter-Strike Global Offensive” "
                                       "folder (in Steam: right-click CS2 → Manage → Browse local files)."), "zle")
            return
        self.ust["folder_cfg"] = cfg
        kfg.zapisz_ustawienia(self.ust)
        self.odswiez_folder()
        self.instaluj_gsi()

    def otworz_folder(self):
        os.makedirs(kfg.FOLDER, exist_ok=True)
        try:
            os.startfile(kfg.FOLDER)
        except (AttributeError, OSError):
            pass

    def wyloguj(self):
        if messagebox.askyesno("SensFit", t("Wylogować? Program się zamknie, a przy następnym uruchomieniu "
                                            "trzeba będzie zalogować się przez Discord.",
                                            "Log out? The app will close, and next time you will need to log in "
                                            "with Discord.")):
            if self.pozwol_zamknac():
                dostep.usun_bilet()
                self.root.destroy()

    def kopiuj_komende(self):
        if self.komenda:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.komenda)
            self.przycisk_kopiuj.config(text=t("Skopiowano - wklej w konsoli CS2 (~)", "Copied - paste it into the CS2 console (~)"))
            self.root.after(3000, lambda: self.przycisk_kopiuj.winfo_exists() and self.przycisk_kopiuj.config(
                text=t("Kopiuj komendę do konsoli CS2", "Copy command for the CS2 console")))

    def usun_sesje(self):
        sens, dpi = self.ust["sens"], self.ust["dpi"]
        if messagebox.askyesno("SensFit", t(f"Usunąć wszystkie sesje nagrane na eDPI {kfg.edpi(sens, dpi):.0f} "
                                            f"(sens {sens}, {dpi} DPI) i {self.klucz_obrazu()}?",
                                            f"Delete all sessions recorded at eDPI {kfg.edpi(sens, dpi):.0f} "
                                            f"(sens {sens}, {dpi} DPI) and {self.klucz_obrazu()}?")):
            sesje.usun(sens, dpi, self.klucz_obrazu(), kfg.m_yaw())
            self.ostatni = None
            self.uruchom_analize()


# Dialog windows
class Okno(tk.Toplevel):
    """Dialog centred on the program window, blocking the main window until it is closed."""

    def __init__(self, app, tytul, szer=560):
        super().__init__(app.root, bg=KOLOR["panel"])
        self.app = app
        self.title(tytul)
        self.resizable(False, False)
        self.transient(app.root)
        try:
            self.iconbitmap(sciezka_zasobu("ikona.ico"))
        except tk.TclError:
            pass
        self.tresc = tk.Frame(self, bg=KOLOR["panel"], width=szer)
        self.tresc.pack(fill="both", expand=True, padx=24, pady=20)
        self.bind("<Escape>", lambda _e: self.zamknij())
        self.protocol("WM_DELETE_WINDOW", self.zamknij)

    def pokaz(self):
        self.update_idletasks()
        r = self.app.root
        x = r.winfo_rootx() + (r.winfo_width() - self.winfo_reqwidth()) // 2
        y = r.winfo_rooty() + max(20, (r.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.focus_set()

    def zamknij(self):
        self.grab_release()
        self.destroy()


class OknoAktualizacji(Okno):
    def __init__(self, app, info):
        super().__init__(app, t("Aktualizacja SensFit", "SensFit update"))
        self.info = info
        self.przerwano = False
        self.kolejka = queue.Queue()
        c = self.tresc
        etykieta(c, t("Aktualizacja SensFit", "SensFit update"), rozmiar=15, gruba=True, fg="mocny").pack(anchor="w")
        etykieta(c, t(f"Z wersji {wersja.NUMER} do {info['wersja']}", f"From version {wersja.NUMER} to {info['wersja']}"),
                 fg="szary").pack(anchor="w", pady=(2, 10))
        if info["zmiany"]:
            etykieta(c, t("Co nowego:", "What's new:"), gruba=True).pack(anchor="w")
            for punkt in info["zmiany"]:
                etykieta(c, "•  " + punkt, wraplength=500).pack(anchor="w", pady=(3, 0))
        self.cialo = tk.Frame(c, bg=KOLOR["panel"])
        self.cialo.pack(fill="x", pady=(14, 0))
        if self.app.pobrany_instalator and os.path.exists(self.app.pobrany_instalator):
            self.gotowe(self.app.pobrany_instalator)
        elif info["reczna"] or not info["gotowa"]:
            self.recznie()
        else:
            self.start()
        self.pokaz()

    def wyczysc(self):
        for w in self.cialo.winfo_children():
            w.destroy()

    def przyciski(self):
        rzad = tk.Frame(self.cialo, bg=KOLOR["panel"])
        rzad.pack(anchor="w", pady=(12, 0))
        return rzad

    def recznie(self):
        self.wyczysc()
        tekst = (t("Tej wersji nie da się zaktualizować w programie. Pobierz instalator ręcznie.",
                   "This version cannot be updated from inside the app. Download the installer manually.")
                 if self.info["reczna"] else
                 t("Nowa wersja nie jest jeszcze gotowa do pobrania w programie (brak sumy SHA-256, adresu "
                   "instalatora albo podpisu). Spróbuj później albo pobierz ją ręcznie.",
                   "The new version is not ready to download in the app yet (missing SHA-256 hash, installer "
                   "address or signature). Try later or download it manually."))
        etykieta(self.cialo, tekst, fg="uwaga", wraplength=500).pack(anchor="w")
        rzad = self.przyciski()
        ttk.Button(rzad, text=t("Pobierz ręcznie ↗", "Download manually ↗"),
                   command=lambda: webbrowser.open(self.info["strona"])).pack(side="left", padx=(0, 8))
        ttk.Button(rzad, text=t("Zamknij", "Close"), command=self.zamknij).pack(side="left")

    def start(self):
        self.wyczysc()
        rzad = self.przyciski()
        ttk.Button(rzad, text=t("Pobierz i zainstaluj", "Download and install"), style="AkcentMaly.TButton",
                   command=self.pobierz).pack(side="left", padx=(0, 8))
        ttk.Button(rzad, text=t("Anuluj", "Cancel"), command=self.zamknij).pack(side="left")

    def kroki(self, etap):
        """List of steps: 0 is downloading, 1 is checking the sum, 2 is done."""
        for i, tekst in enumerate((t("Pobieranie instalatora", "Downloading the installer"),
                                   t("Sprawdzanie sumy SHA-256", "Checking the SHA-256 hash"),
                                   t("Gotowe do instalacji", "Ready to install"))):
            znak, kolor = ("✓", "ok") if i < etap or etap == 2 else (("●", "akcent_tekst") if i == etap else ("○", "szary"))
            etykieta(self.cialo, f"{znak}  {tekst}", fg=kolor, gruba=i == etap).pack(anchor="w", pady=1)

    def pobierz(self):
        self.wyczysc()
        self.kroki(0)
        self.pasek = ttk.Progressbar(self.cialo, length=500, mode="determinate", maximum=100)
        self.pasek.pack(anchor="w", pady=(10, 2))
        self.procent = etykieta(self.cialo, "0%", fg="szary", rozmiar=9)
        self.procent.pack(anchor="w")
        rzad = self.przyciski()
        ttk.Button(rzad, text=t("Anuluj", "Cancel"), command=self.zamknij).pack(side="left")

        def praca():
            try:
                plik = aktualizacja.pobierz(self.info, lambda p, r: self.kolejka.put(("postep", p, r)),
                                            lambda: self.przerwano)
                self.kolejka.put(("gotowe", plik))
            except aktualizacja.BladAktualizacji as e:
                self.kolejka.put(("blad", str(e)))
            except Exception as e:
                self.kolejka.put(("blad", str(e)))
        threading.Thread(target=praca, daemon=True).start()
        self.odbierz()

    def odbierz(self):
        if not self.winfo_exists():
            return
        ostatni = None
        while not self.kolejka.empty():
            ostatni = self.kolejka.get()
            if ostatni[0] != "postep":
                break
        if ostatni:
            if ostatni[0] == "postep":
                _, pobrane, rozmiar = ostatni
                nazwa = os.path.basename(self.info["url"])
                if rozmiar:
                    procent = min(100, pobrane * 100 // rozmiar)
                    self.pasek.config(value=procent)
                    self.procent.config(text=f"{procent}%  ·  {nazwa}")
                else:
                    self.procent.config(text=f"{pobrane / 1048576:.1f} MB  ·  {nazwa}")
            elif ostatni[0] == "gotowe":
                return self.gotowe(ostatni[1])
            else:
                return self.blad(ostatni[1])
        self.after(100, self.odbierz)

    def gotowe(self, plik):
        self.app.pobrany_instalator = plik
        self.wyczysc()
        self.kroki(2)
        etykieta(self.cialo, t("Suma SHA-256 zgadza się z plikiem wersja.json.", "The SHA-256 hash matches wersja.json."),
                 fg="ok").pack(anchor="w", pady=(8, 0))
        rzad = self.przyciski()
        ttk.Button(rzad, text=t("Zamknij SensFit i uruchom instalator", "Close SensFit and run the installer"),
                   style="AkcentMaly.TButton", command=lambda: self.instaluj(plik)).pack(side="left", padx=(0, 8))
        ttk.Button(rzad, text=t("Później", "Later"), command=self.zamknij).pack(side="left")
        for uwaga in (t(r"Program się zamknie. Ustawienia i sesje w %APPDATA%\SensFit zostają.",
                        r"The app will close. Your settings and sessions in %APPDATA%\SensFit are kept."),
                      t("Windows może pokazać ostrzeżenie SmartScreen, bo instalator nie ma płatnego podpisu. "
                        "Kliknij „Więcej informacji” → „Uruchom mimo to”.",
                        "Windows may show a SmartScreen warning because the installer has no paid signature. "
                        "Click “More info” → “Run anyway”.")):
            etykieta(self.cialo, uwaga, fg="szary", rozmiar=9, wraplength=500).pack(anchor="w", pady=(8, 0))

    def blad(self, tekst):
        self.wyczysc()
        etykieta(self.cialo, tekst, fg="zle", wraplength=500).pack(anchor="w")
        rzad = self.przyciski()
        ttk.Button(rzad, text=t("Spróbuj ponownie", "Try again"), command=self.pobierz).pack(side="left", padx=(0, 8))
        ttk.Button(rzad, text=t("Zamknij", "Close"), command=self.zamknij).pack(side="left")

    def instaluj(self, plik):
        if not self.app.pozwol_zamknac(self):
            return
        try:
            aktualizacja.uruchom_instalator(plik)
        except aktualizacja.BladAktualizacji as e:
            return self.blad(str(e))
        self.app.root.destroy()

    def zamknij(self):
        self.przerwano = True
        super().zamknij()


class OknoEksportu(Okno):
    def __init__(self, app):
        super().__init__(app, t("Eksport raportu", "Export report"), szer=640)
        w, info, sens, dpi = app.ostatni
        self.tekst_raportu = eksport.tekst(w, info, sens, dpi, app.ocena_obrazu(sens))
        self.dane = eksport.dane_raportu(w, info, sens, dpi, [p[1] for p in app.porady_klucze])
        c = self.tresc
        etykieta(c, t("Eksport raportu", "Export report"), rozmiar=15, gruba=True, fg="mocny").pack(anchor="w")
        etykieta(c, t("Wyślij wynik trenerowi albo znajomym bez zrzutów ekranu. Raport nie zawiera nazwy "
                      "użytkownika Windows ani folderów.",
                      "Send your result to a coach or friends without screenshots. The report contains no "
                      "Windows user name or folders."), fg="szary", wraplength=600).pack(anchor="w", pady=(2, 12))
        self.pillow = eksport.pillow_dostepny()
        opcje = ([("img", t("Obrazek", "Image"))] if self.pillow else []) + [("txt", t("Plik tekstowy", "Text file"))]
        self.przelacznik = Przelacznik(c, opcje, opcje[0][0], self.pokaz_widok)
        self.przelacznik.pack(anchor="w")
        self.obszar = tk.Frame(c, bg=KOLOR["panel"])
        self.obszar.pack(fill="x", pady=(12, 0))
        self.info = etykieta(c, fg="ok", rozmiar=9)
        self.info.pack(anchor="w", pady=(8, 0))
        self.pokaz_widok(opcje[0][0])
        self.pokaz()

    def pokaz_widok(self, klucz):
        for w in self.obszar.winfo_children():
            w.destroy()
        self.info.config(text="")
        rzad = tk.Frame(self.obszar, bg=KOLOR["panel"])
        if klucz == "img":
            obraz = eksport.obrazek(self.dane, sciezka_zasobu("ikona_48.png")).resize((600, 315))
            bufor = io.BytesIO()
            obraz.save(bufor, "PNG")
            self.podglad = tk.PhotoImage(data=base64.b64encode(bufor.getvalue()))
            tk.Label(self.obszar, image=self.podglad, bg=KOLOR["panel"], bd=0).pack(anchor="w")
            rzad.pack(anchor="w", pady=(12, 0))
            ttk.Button(rzad, text=t("Zapisz jako PNG…", "Save as PNG…"), style="AkcentMaly.TButton",
                       command=self.zapisz_png).pack(side="left", padx=(0, 8))
        else:
            pole = tk.Text(self.obszar, width=78, height=18, wrap="word", bg=KOLOR["pole"], fg=KOLOR["tekst"],
                           relief="flat", font=(MONO, 9), padx=10, pady=8, highlightthickness=1,
                           highlightbackground=KOLOR["linia"])
            pole.insert("1.0", self.tekst_raportu.strip("\n"))
            pole.config(state="disabled")
            pole.pack(anchor="w", fill="x")
            rzad.pack(anchor="w", pady=(12, 0))
            ttk.Button(rzad, text=t("Zapisz jako TXT…", "Save as TXT…"), style="AkcentMaly.TButton",
                       command=self.zapisz_txt).pack(side="left", padx=(0, 8))
            ttk.Button(rzad, text=t("Kopiuj tekst", "Copy text"), command=self.kopiuj).pack(side="left", padx=(0, 8))
        ttk.Button(rzad, text=t("Zamknij", "Close"), command=self.zamknij).pack(side="left")

    def nazwa_pliku(self, rozszerzenie):
        return f"SensFit_{t('raport', 'report')}_{datetime.now():%Y%m%d}.{rozszerzenie}"

    def zapisz_png(self):
        sciezka = filedialog.asksaveasfilename(parent=self, defaultextension=".png", initialfile=self.nazwa_pliku("png"),
                                               filetypes=[("PNG", "*.png")])
        if sciezka:
            try:
                eksport.zapisz_obrazek(sciezka, self.dane, sciezka_zasobu("ikona_48.png"))
                self.info.config(text=t("Zapisano obrazek.", "Image saved."), fg=KOLOR["ok"])
            except OSError as e:
                self.info.config(text=t("Nie udało się zapisać: ", "Could not save: ") + str(e), fg=KOLOR["zle"])

    def zapisz_txt(self):
        sciezka = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialfile=self.nazwa_pliku("txt"),
                                               filetypes=[(t("Plik tekstowy", "Text file"), "*.txt")])
        if sciezka:
            try:
                eksport.zapisz_tekst(sciezka, self.tekst_raportu)
                self.info.config(text=t("Zapisano plik.", "File saved."), fg=KOLOR["ok"])
            except OSError as e:
                self.info.config(text=t("Nie udało się zapisać: ", "Could not save: ") + str(e), fg=KOLOR["zle"])

    def kopiuj(self):
        self.clipboard_clear()
        self.clipboard_append(self.tekst_raportu)
        self.info.config(text=t("Skopiowano.", "Copied."), fg=KOLOR["ok"])


def przygotuj_jezyk_i_motyw():
    """On the first start the language comes from the system (Polish gives PL, otherwise EN), later from the settings."""
    ust = kfg.wczytaj_ustawienia()
    if ust.get("jezyk") not in jezyk.JEZYKI:
        ust["jezyk"] = jezyk.jezyk_systemu()
        try:
            kfg.zapisz_ustawienia(ust)
        except OSError:
            pass
    jezyk.ustaw(ust["jezyk"])
    ustaw_motyw(ust.get("motyw"))


def main():
    if sys.platform == "win32":
        try:  # sharp fonts on monitors with 125 to 150% scaling
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    przygotuj_jezyk_i_motyw()
    root = tk.Tk()
    root.report_callback_exception = _blad_globalny
    EkranDostepu(root, lambda uzytkownik: Aplikacja(root, uzytkownik))
    root.mainloop()
