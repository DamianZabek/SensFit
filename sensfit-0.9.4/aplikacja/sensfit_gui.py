import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import dostep
import gsi
import konfiguracja as kfg
import raport
import rozdzielczosc as rozdz
import sesje
from mysz_windows import NagrywaczMyszy

WERSJA = "0.9.4 (test)"
MIN_MINUT = 3  # krótsze nagrania nie mają sensu

# Paleta: ciemny grafit jak HUD w grze, bursztyn jako akcent, semantyczne zielony/żółty/czerwony
KOLOR = {
    "tlo": "#14161a", "panel": "#1b1f26", "panel2": "#222630", "linia": "#2a2f38",
    "tekst": "#e8eaed", "szary": "#9aa1ac", "akcent": "#ffb020", "na_akcencie": "#1a1204",
    "ok": "#4ade80", "uwaga": "#fbbf24", "zle": "#f97373", "pasek": "#0e1013",
}
CZCIONKA = "Segoe UI"


def sciezka_zasobu(nazwa):
    """Ścieżka do pliku dołączonego do .exe (np. ikony)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), nazwa)


def wczytaj_logo(nazwa):
    """Obrazek z ikoną (PNG) albo None, gdy pliku brak."""
    try:
        return tk.PhotoImage(file=sciezka_zasobu(nazwa))
    except tk.TclError:
        return None


class Zakladki:
    """Boczne menu zamiast ttk.Notebook: przyciski po lewej, treść po prawej."""

    def __init__(self, menu, tresc, po_zmianie=None):
        self.menu, self.tresc = menu, tresc
        self.po_zmianie = po_zmianie
        self.pozycje = []  # (ramka, wiersz, pasek, etykieta)
        self.nazwy = {}
        self.aktywna = None

    def add(self, ramka, text):
        k = KOLOR
        wiersz = tk.Frame(self.menu, bg=k["pasek"], cursor="hand2")
        wiersz.pack(fill="x", pady=1)
        pasek = tk.Frame(wiersz, bg=k["pasek"], width=3)
        pasek.pack(side="left", fill="y")
        etykieta = tk.Label(wiersz, text=text, bg=k["pasek"], fg=k["szary"], anchor="w",
                            font=(CZCIONKA, 11), padx=14, pady=10, cursor="hand2")
        etykieta.pack(side="left", fill="x", expand=True)
        for w in (wiersz, etykieta):
            w.bind("<Button-1>", lambda _e, r=ramka: self.select(r))
            w.bind("<Enter>", lambda _e, r=ramka: self._tlo(r, True))
            w.bind("<Leave>", lambda _e, r=ramka: self._tlo(r, False))
        self.pozycje.append((ramka, wiersz, pasek, etykieta))
        self.nazwy[ramka] = text
        if self.aktywna is None:
            self.select(ramka)

    def _tlo(self, ramka, nad):
        for r, wiersz, _p, etykieta in self.pozycje:
            if r is ramka and r is not self.aktywna:
                kolor = KOLOR["panel"] if nad else KOLOR["pasek"]
                wiersz.config(bg=kolor)
                etykieta.config(bg=kolor)

    def select(self, ramka):
        k = KOLOR
        self.aktywna = ramka
        for r, wiersz, pasek, etykieta in self.pozycje:
            aktywna = r is ramka
            wiersz.config(bg=k["panel2"] if aktywna else k["pasek"])
            etykieta.config(bg=k["panel2"] if aktywna else k["pasek"],
                            fg="#ffffff" if aktywna else k["szary"],
                            font=(CZCIONKA, 11, "bold" if aktywna else "normal"))
            pasek.config(bg=k["akcent"] if aktywna else k["pasek"])
            if aktywna:
                r.pack(fill="both", expand=True)
            else:
                r.pack_forget()
        if self.po_zmianie:
            self.po_zmianie(self.nazwy[ramka])


class EkranDostepu:
    """Pierwszy ekran: sprawdza bilet dostępu, a gdy go brak – logowanie przez Discord.

    Sieć działa w osobnym wątku, okno co 0,2 s odbiera wynik (tak jak w Aplikacji).
    """

    def __init__(self, root, gdy_wpuszczony):
        self.root = root
        self.gdy_wpuszczony = gdy_wpuszczony
        self.kolejka = queue.Queue()
        self.anuluj = False
        root.title("SensFit")
        root.geometry("1000x780")
        root.minsize(900, 700)
        root.configure(bg=KOLOR["tlo"])
        try:
            root.iconbitmap(default=sciezka_zasobu("ikona.ico"))
        except tk.TclError:
            pass

        k = KOLOR
        self.ramka = tk.Frame(root, bg=k["tlo"])
        self.ramka.place(relx=0.5, rely=0.45, anchor="center")
        self.logo = wczytaj_logo("ikona_128.png")
        if self.logo:
            tk.Label(self.ramka, image=self.logo, bg=k["tlo"]).pack(pady=(0, 14))
        tk.Label(self.ramka, text="SensFit", bg=k["tlo"], fg="#ffffff",
                 font=(CZCIONKA, 28, "bold")).pack()
        tk.Label(self.ramka, text="wersja testowa – dostęp dla testerów z serwera Discord",
                 bg=k["tlo"], fg=k["szary"], font=(CZCIONKA, 10)).pack(pady=(2, 28))
        self.napis = tk.Label(self.ramka, bg=k["tlo"], fg=k["tekst"], font=(CZCIONKA, 11),
                              wraplength=480, justify="center")
        self.napis.pack()
        self.przycisk = tk.Button(self.ramka, text="Zaloguj przez Discord", command=self.zaloguj,
                                  bg="#5865F2", fg="white", activebackground="#4752c4",
                                  activeforeground="white", relief="flat", bd=0, cursor="hand2",
                                  font=(CZCIONKA, 12, "bold"), padx=24, pady=10)
        self.przycisk_anuluj = tk.Button(self.ramka, text="Anuluj", command=self.przerwij,
                                         bg=k["linia"], fg=k["tekst"], activebackground="#343a46",
                                         activeforeground=k["tekst"], relief="flat", bd=0,
                                         font=(CZCIONKA, 10), padx=16, pady=6)
        self.blad = tk.Label(self.ramka, bg=k["tlo"], fg=k["zle"], font=(CZCIONKA, 10),
                             wraplength=480, justify="center")
        self.blad.pack(pady=(16, 0))
        tk.Label(self.ramka, text="Nie masz dostępu? Dołącz do serwera Discord SensFit i poproś o rolę testera.",
                 bg=k["tlo"], fg=k["szary"], font=(CZCIONKA, 9), wraplength=480).pack(pady=(28, 0))

        if not dostep.skonfigurowany():
            self.pokaz_logowanie("Ta kopia SensFit nie ma ustawionego serwera dostępu. "
                                 "Pobierz aktualną wersję od autora.")
            self.przycisk.config(state="disabled")
            return
        self.napis.config(text="Sprawdzam dostęp…")
        self.w_tle(dostep.sprawdz_przy_starcie)
        self.odbierz()

    def w_tle(self, praca):
        def watek():
            try:
                self.kolejka.put(("wynik", praca()))
            except dostep.BladDostepu as e:
                self.kolejka.put(("blad", str(e)))
            except dostep.BrakPolaczenia as e:
                self.kolejka.put(("blad", f"{e} Sprawdź internet i spróbuj ponownie."))
            except Exception as e:  # nie zostawiaj okna w stanie „czekam”
                self.kolejka.put(("blad", f"Nieoczekiwany błąd: {e}"))
        threading.Thread(target=watek, daemon=True).start()

    def odbierz(self):
        while not self.kolejka.empty():
            rodzaj, tresc = self.kolejka.get()
            if rodzaj == "blad":
                self.pokaz_logowanie("", tresc)
            elif isinstance(tresc, tuple):  # wynik sprawdz_przy_starcie
                stan, dane = tresc
                if stan == "ok":
                    return self.wpusc(dane)
                self.pokaz_logowanie("", dane)
            else:  # bilet po zalogowaniu
                return self.wpusc(dostep.odczytaj_bilet(tresc))
        self.root.after(200, self.odbierz)

    def pokaz_logowanie(self, napis="", blad=""):
        self.napis.config(text=napis or "Zaloguj się kontem Discord, na którym masz rolę testera SensFit.")
        self.blad.config(text=blad)
        self.przycisk_anuluj.pack_forget()
        self.przycisk.config(state="normal")
        self.przycisk.pack(before=self.blad, pady=(18, 0))

    def zaloguj(self):
        self.anuluj = False
        self.blad.config(text="")
        self.napis.config(text="Dokończ logowanie w przeglądarce, która się otworzyła…")
        self.przycisk.pack_forget()
        self.przycisk_anuluj.pack(before=self.blad, pady=(18, 0))
        self.w_tle(lambda: dostep.zaloguj(lambda: self.anuluj))

    def przerwij(self):
        self.anuluj = True

    def wpusc(self, dane):
        self.ramka.destroy()
        self.gdy_wpuszczony(dane or {})


class Aplikacja:
    def __init__(self, root, uzytkownik=None):
        self.root = root
        self.uzytkownik = uzytkownik or {}
        self.ust = kfg.wczytaj_ustawienia()
        sens_cs2 = kfg.odczytaj_sens_z_cs2()
        if sens_cs2:
            self.ust["sens"] = sens_cs2
        self.wczytaj_obraz()

        # Serwer GSI - odbiera z CS2 informację, czy grasz
        self.stan = gsi.StanGry()
        try:
            gsi.uruchom_serwer(self.stan)
            self.blad_gsi = None
        except OSError:
            self.blad_gsi = (f"Port {gsi.PORT} jest zajęty. Czy SensFit nie jest już uruchomiony? "
                             "Jeśli nie, zamknij program, który używa tego portu.")

        # Odczyt myszy działa cały czas, ale zapisuje ruch tylko gdy czy_nagrywac() == True
        self.nagrywanie = False
        self.bez_gsi = False
        self.czas_gry_s = 0.0
        self.ostatni_tik = time.monotonic()
        self.nagrywacz = NagrywaczMyszy(self.czy_nagrywac)
        self.mysz_ok = self.nagrywacz.start()

        self.kolejka = queue.Queue()  # wyniki z wątku analizy
        self.zbuduj_okno()
        self.odswiez()

        if not self.ust["dpi"]:
            self.zakladki.select(self.tab_ustawienia)
            self.pole_dpi.focus_set()
            self.pokaz_info_ustawien("Na start wpisz DPI swojej myszki i kliknij „Zapisz”.", "uwaga")
        else:
            self.uruchom_analize()

    # ------------------------------------------------------------------ obraz (rozdzielczość)
    def wczytaj_obraz(self):
        """Uzupełnia rozdzielczość gry i monitora: z plików CS2 i z Windows, potem z ustawień."""
        self.ust.setdefault("skalowanie", "rozciagniete")
        if not rozdz.parsuj(self.ust.get("monitor")):
            mon = rozdz.rozdzielczosc_monitora()
            self.ust["monitor"] = f"{mon[0]}x{mon[1]}" if mon else "1920x1080"
        gra = rozdz.odczytaj_z_cs2(kfg.folder_steam())
        if gra:
            self.ust["rozdzielczosc"] = f"{gra[0]}x{gra[1]}"
        elif not rozdz.parsuj(self.ust.get("rozdzielczosc")):
            self.ust["rozdzielczosc"] = self.ust["monitor"]

    def obraz(self):
        """(rozdzielczość gry, rozdzielczość monitora, skalowanie)"""
        return (rozdz.parsuj(self.ust.get("rozdzielczosc")), rozdz.parsuj(self.ust.get("monitor")),
                self.ust.get("skalowanie", "rozciagniete"))

    def klucz_obrazu(self):
        return rozdz.klucz_sesji(*self.obraz())

    def ocena_obrazu(self, sens=None):
        return rozdz.ocen(sens or self.ust["sens"], self.ust["dpi"], *self.obraz())

    # ------------------------------------------------------------------ logika
    def czy_nagrywac(self):
        """Wywoływane z wątku myszy - tylko czyta proste pola."""
        return self.nagrywanie and (self.bez_gsi or self.stan.czy_nagrywac())

    def cs2_polaczone(self):
        return time.monotonic() - self.stan.ostatnia_wiadomosc < 30

    def start_stop(self):
        if self.nagrywanie:
            self.nagrywanie = False
            self.przycisk_start.config(text="Analizuję…", state="disabled")
            self.root.after(150, self.zakoncz_nagrywanie)  # chwila, żeby wątek myszy skończył
            return

        if not self.ust["dpi"] or not self.ust["sens"]:
            messagebox.showwarning("SensFit", "Najpierw uzupełnij DPI i czułość w zakładce Ustawienia.")
            self.zakladki.select(self.tab_ustawienia)
            return
        if not self.mysz_ok:
            messagebox.showerror("SensFit", f"Nie można odczytać myszy: {self.nagrywacz.blad}")
            return
        sens_cs2 = kfg.odczytaj_sens_z_cs2()  # gracz mógł zmienić czułość od startu programu
        if sens_cs2 and sens_cs2 != self.ust["sens"]:
            self.ust["sens"] = sens_cs2
            self.odswiez_naglowek()
        gra = rozdz.odczytaj_z_cs2(kfg.folder_steam())  # ...i rozdzielczość
        if gra and f"{gra[0]}x{gra[1]}" != self.ust.get("rozdzielczosc"):
            self.ust["rozdzielczosc"] = f"{gra[0]}x{gra[1]}"
            self.pole_rozdz.set(self.ust["rozdzielczosc"])
            self.odswiez_naglowek()
            self.odswiez_ocene_obrazu()

        self.bez_gsi = self.var_bez_gsi.get()
        self.nagrywacz.reset()
        self.stan.zabojstwa = []  # liczymy zabójstwa tylko z tej sesji
        self.czas_gry_s = 0.0
        self.nagrywanie = True
        self.przycisk_start.config(text="Zakończ i analizuj")
        self.check_bez_gsi.config(state="disabled")

    def zakoncz_nagrywanie(self):
        kubelki, klikniecia, puszczenia = self.nagrywacz.pobierz()
        zabojstwa = list(self.stan.zabojstwa)
        minuty = self.czas_gry_s / 60
        self.check_bez_gsi.config(state="normal")
        self.przycisk_start.config(text="Rozpocznij nagrywanie", state="normal")

        if minuty < MIN_MINUT or not kubelki:
            messagebox.showinfo("SensFit", f"Nagrano tylko {minuty:.1f} min gry. Sesja nie została zapisana – "
                                f"potrzeba co najmniej {MIN_MINUT} min (zalecane 20–30).")
            return
        sesje.zapisz(self.ust["sens"], self.ust["dpi"], minuty, kubelki, klikniecia, self.klucz_obrazu(),
                     puszczenia, zabojstwa)
        self.uruchom_analize(przelacz=True)

    def uruchom_analize(self, przelacz=False):
        sens, dpi = self.ust["sens"], self.ust["dpi"]
        if not sens or not dpi:
            return
        self.etykieta_wynik.config(text="Analizuję sesje…", foreground=KOLOR["szary"])
        obraz, ocena = self.klucz_obrazu(), self.ocena_obrazu()

        def praca():
            try:
                self.kolejka.put(("wynik", sesje.analizuj(sens, dpi, obraz, ocena), sens, dpi, przelacz))
            except Exception as e:  # uszkodzony plik itp. - pokaż, zamiast cicho paść
                self.kolejka.put(("blad", str(e)))
        threading.Thread(target=praca, daemon=True).start()

    def odswiez(self):
        """Co 0,5 s: liczy czas gry, aktualizuje statusy i odbiera wyniki analizy."""
        teraz = time.monotonic()
        if self.czy_nagrywac():
            self.czas_gry_s += teraz - self.ostatni_tik
        self.ostatni_tik = teraz

        while not self.kolejka.empty():
            wiadomosc = self.kolejka.get()
            if wiadomosc[0] == "wynik":
                (wynik, info), sens, dpi, przelacz = wiadomosc[1:]
                self.pokaz_wynik(wynik, info, sens, dpi)
                if przelacz:
                    self.zakladki.select(self.tab_wyniki)
            else:
                self.etykieta_wynik.config(text=f"Błąd analizy: {wiadomosc[1]}", foreground=KOLOR["zle"])

        self.odswiez_statusy()
        self.root.after(500, self.odswiez)

    # ------------------------------------------------------------------ wygląd
    def zbuduj_okno(self):
        r = self.root
        r.title("SensFit")
        r.geometry("1000x780")
        r.minsize(900, 700)
        r.configure(bg=KOLOR["tlo"])
        try:
            r.iconbitmap(default=sciezka_zasobu("ikona.ico"))
        except tk.TclError:
            pass

        s = ttk.Style()
        s.theme_use("clam")
        k = KOLOR
        s.configure(".", background=k["tlo"], foreground=k["tekst"], font=(CZCIONKA, 10),
                    bordercolor=k["linia"], focuscolor=k["akcent"])
        s.configure("TFrame", background=k["tlo"])
        s.configure("Panel.TFrame", background=k["panel"])
        s.configure("TLabel", background=k["tlo"], foreground=k["tekst"])
        s.configure("Panel.TLabel", background=k["panel"])
        s.configure("Szary.TLabel", foreground=k["szary"])
        s.configure("PanelSzary.TLabel", background=k["panel"], foreground=k["szary"])
        s.configure("Tytul.TLabel", font=(CZCIONKA, 15, "bold"))
        s.configure("Duzy.TLabel", background=k["panel"], font=(CZCIONKA, 20, "bold"))
        s.configure("Licznik.TLabel", background=k["panel"], font=("Consolas", 18, "bold"))
        s.configure("Naglowek.TLabel", background=k["panel"], foreground=k["szary"], font=("Consolas", 10))
        ramki = dict(bordercolor=k["tlo"], lightcolor=k["tlo"], darkcolor=k["tlo"])
        s.configure("TSeparator", background=k["linia"])
        s.configure("Vertical.TScrollbar", background=k["linia"], troughcolor="#0e1013",
                    arrowcolor=k["szary"], borderwidth=0, **ramki)
        s.map("Vertical.TScrollbar", background=[("active", "#343a46")])
        s.configure("TButton", background=k["linia"], foreground=k["tekst"], padding=(12, 6), borderwidth=0)
        s.map("TButton", background=[("active", "#343a46"), ("disabled", k["panel"])],
              foreground=[("disabled", k["szary"])])
        s.configure("Akcent.TButton", background=k["akcent"], foreground=k["na_akcencie"],
                    font=(CZCIONKA, 12, "bold"), padding=(20, 12))
        s.map("Akcent.TButton", background=[("active", "#ffc457"), ("disabled", k["linia"])])
        s.configure("TCheckbutton", background=k["panel"], foreground=k["tekst"],
                    indicatorbackground="#0e1013", indicatorforeground=k["akcent"])
        s.map("TCheckbutton", background=[("active", k["panel"])],
              indicatorbackground=[("disabled", k["panel"])])
        s.configure("TEntry", fieldbackground="#0e1013", foreground=k["tekst"], insertcolor=k["tekst"],
                    padding=5, bordercolor=k["linia"], lightcolor=k["linia"], darkcolor=k["linia"])
        s.map("TEntry", bordercolor=[("focus", k["akcent"])], lightcolor=[("focus", k["akcent"])])
        s.configure("TCombobox", fieldbackground="#0e1013", background=k["linia"], foreground=k["tekst"],
                    arrowcolor=k["tekst"], padding=4, bordercolor=k["linia"], lightcolor=k["linia"],
                    darkcolor=k["linia"], selectbackground="#0e1013", selectforeground=k["tekst"])
        s.map("TCombobox", fieldbackground=[("readonly", "#0e1013")], foreground=[("readonly", k["tekst"])],
              bordercolor=[("focus", k["akcent"])])
        r.option_add("*TCombobox*Listbox.background", "#0e1013")
        r.option_add("*TCombobox*Listbox.foreground", k["tekst"])
        r.option_add("*TCombobox*Listbox.selectBackground", k["akcent"])
        r.option_add("*TCombobox*Listbox.selectForeground", "#1a1204")
        s.configure("AkcentMaly.TButton", background=k["akcent"], foreground="#1a1204",
                    font=(CZCIONKA, 10, "bold"), padding=(18, 7))
        s.map("AkcentMaly.TButton", background=[("active", "#ffc457")])

        # Boczne menu (po lewej) + treść (po prawej)
        menu = tk.Frame(r, bg=k["pasek"], width=210, highlightthickness=0)
        menu.pack(side="left", fill="y")
        menu.pack_propagate(False)
        tk.Frame(r, bg=k["linia"], width=1).pack(side="left", fill="y")
        glowna = tk.Frame(r, bg=k["tlo"])
        glowna.pack(side="left", fill="both", expand=True)

        self.logo = wczytaj_logo("ikona_48.png")
        naglowek_menu = tk.Frame(menu, bg=k["pasek"])
        naglowek_menu.pack(fill="x", padx=14, pady=(22, 22))
        if self.logo:
            tk.Label(naglowek_menu, image=self.logo, bg=k["pasek"]).pack(side="left")
        tk.Label(naglowek_menu, text="SensFit", bg=k["pasek"], fg="#ffffff",
                 font=(CZCIONKA, 17, "bold")).pack(side="left", padx=(10, 0))
        self.menu_pozycje = tk.Frame(menu, bg=k["pasek"])
        self.menu_pozycje.pack(fill="x", padx=8)

        stopka = tk.Frame(menu, bg=k["pasek"])
        stopka.pack(side="bottom", fill="x", padx=14, pady=16)
        rzad_cs2 = tk.Frame(stopka, bg=k["pasek"])
        rzad_cs2.pack(anchor="w")
        self.kropka_menu = tk.Label(rzad_cs2, text="●", bg=k["pasek"], fg=k["uwaga"], font=(CZCIONKA, 10))
        self.kropka_menu.pack(side="left")
        self.tekst_menu = tk.Label(rzad_cs2, text="CS2: brak sygnału", bg=k["pasek"], fg=k["tekst"],
                                   font=(CZCIONKA, 9))
        self.tekst_menu.pack(side="left", padx=(6, 0))
        tk.Label(stopka, text=f"v{WERSJA}", bg=k["pasek"], fg=k["szary"], font=(CZCIONKA, 9)).pack(anchor="w", pady=(6, 0))

        # Pasek u góry treści: obecne ustawienia jako „plakietka"
        gora = tk.Frame(glowna, bg=k["tlo"])
        gora.pack(fill="x", padx=24, pady=(18, 0))
        self.tytul_strony = tk.Label(gora, bg=k["tlo"], fg="#ffffff", font=(CZCIONKA, 18, "bold"))
        self.tytul_strony.pack(side="left")
        self.naglowek = tk.Label(gora, bg=k["panel2"], fg=k["szary"], font=("Consolas", 10), padx=12, pady=6)
        self.naglowek.pack(side="right")
        self.odswiez_naglowek()

        self.tresc = tk.Frame(glowna, bg=k["tlo"])
        self.tresc.pack(fill="both", expand=True, padx=24, pady=(14, 20))
        self.zakladki = Zakladki(self.menu_pozycje, self.tresc,
                                 lambda nazwa: self.tytul_strony.config(text=nazwa))
        self.tab_nagrywanie = self.zbuduj_nagrywanie()
        self.tab_wyniki = self.zbuduj_wyniki()
        self.tab_ustawienia = self.zbuduj_ustawienia()
        self.tab_pomoc = self.zbuduj_pomoc()
        self.zakladki.select(self.tab_nagrywanie)

    def nowa_zakladka(self, nazwa):
        ramka = ttk.Frame(self.tresc, style="Panel.TFrame", padding=22)
        self.zakladki.add(ramka, nazwa)
        return ramka

    def zbuduj_nagrywanie(self):
        t = self.nowa_zakladka("Nagrywanie")
        # Lista kontrolna - trzy warunki, żeby nagrywanie miało sens
        self.status_mysz = self.wiersz_statusu(t)
        self.status_gsi = self.wiersz_statusu(t)
        self.status_cs2 = self.wiersz_statusu(t)

        ttk.Separator(t).pack(fill="x", pady=14)
        self.etykieta_stan = ttk.Label(t, style="Duzy.TLabel")
        self.etykieta_stan.pack(anchor="w")
        self.etykieta_powod = ttk.Label(t, style="PanelSzary.TLabel")
        self.etykieta_powod.pack(anchor="w", pady=(2, 12))

        liczniki = ttk.Frame(t, style="Panel.TFrame")
        liczniki.pack(anchor="w", pady=(0, 16))
        self.licznik_czas = self.licznik(liczniki, "czas gry")
        # Kliknięcia, nie pociski: mysz zgłasza jedno wciśnięcie na całą serię
        self.licznik_strzaly = self.licznik(liczniki, "kliknięcia")
        self.licznik_zabojstw = self.licznik(liczniki, "zabójstwa (GSI)")

        self.przycisk_start = ttk.Button(t, text="Rozpocznij nagrywanie", style="Akcent.TButton",
                                         command=self.start_stop)
        self.przycisk_start.pack(anchor="w")
        self.var_bez_gsi = tk.BooleanVar(value=False)
        self.check_bez_gsi = ttk.Checkbutton(
            t, variable=self.var_bez_gsi,
            text="Nagrywaj bez połączenia z CS2 (awaryjnie – nagrywa też menu, mniej dokładne)")
        self.check_bez_gsi.pack(anchor="w", pady=(12, 0))
        ttk.Label(t, style="PanelSzary.TLabel", wraplength=700, justify="left",
                  text="Kliknij „Rozpocznij”, przełącz się do CS2 i graj 20–30 min deathmatchu karabinem "
                       "lub pistoletem. Program sam wstrzymuje nagrywanie w menu, po śmierci i przy nożu, "
                       "granatach i AWP. Na koniec wróć tutaj i kliknij „Zakończ i analizuj”."
                  ).pack(anchor="w", pady=(16, 0))
        return t

    def wiersz_statusu(self, rodzic):
        ramka = ttk.Frame(rodzic, style="Panel.TFrame")
        ramka.pack(fill="x", pady=2)
        kropka = ttk.Label(ramka, text="●", style="Panel.TLabel", font=(CZCIONKA, 11))
        kropka.pack(side="left", padx=(0, 8))
        tekst = ttk.Label(ramka, style="Panel.TLabel")
        tekst.pack(side="left")
        return kropka, tekst

    def ustaw_status(self, wiersz, ok, tekst):
        kolor = {True: KOLOR["ok"], False: KOLOR["zle"], None: KOLOR["uwaga"]}[ok]
        wiersz[0].config(foreground=kolor)
        wiersz[1].config(text=tekst)

    def licznik(self, rodzic, podpis):
        ramka = ttk.Frame(rodzic, style="Panel.TFrame")
        ramka.pack(side="left", padx=(0, 40))
        wartosc = ttk.Label(ramka, text="0", style="Licznik.TLabel")
        wartosc.pack(anchor="w")
        ttk.Label(ramka, text=podpis.upper(), style="PanelSzary.TLabel", font=(CZCIONKA, 8)).pack(anchor="w")
        return wartosc

    def karta(self, rodzic, **opcje):
        k = KOLOR
        return tk.Frame(rodzic, bg=k["panel2"], highlightbackground=k["linia"], highlightthickness=1, **opcje)

    def zbuduj_wyniki(self):
        t = self.nowa_zakladka("Wyniki")
        k = KOLOR
        gora = ttk.Frame(t, style="Panel.TFrame")
        gora.pack(fill="x")

        # Karta zalecenia
        hero = self.karta(gora)
        hero.pack(side="left", fill="both", expand=True)
        wnetrze = tk.Frame(hero, bg=k["panel2"])
        wnetrze.pack(fill="both", expand=True, padx=22, pady=16)
        tk.Label(wnetrze, text="ZALECENIE", bg=k["panel2"], fg=k["akcent"],
                 font=(CZCIONKA, 9, "bold")).pack(anchor="w")
        self.etykieta_wynik = tk.Label(wnetrze, bg=k["panel2"], fg=k["tekst"], font=(CZCIONKA, 17, "bold"),
                                       wraplength=440, justify="left", anchor="w",
                                       text="Brak wyników – nagraj pierwszą sesję.")
        self.etykieta_wynik.pack(anchor="w", pady=(4, 0))
        # Duże liczby „stara → nowa” - widoczne tylko, gdy program zaleca zmianę
        self.liczby = tk.Frame(wnetrze, bg=k["panel2"])
        self.liczba_stara = tk.Label(self.liczby, bg=k["panel2"], fg="#7d8590", font=(CZCIONKA, 28, "bold"))
        self.liczba_stara.pack(side="left")
        tk.Label(self.liczby, text="  →  ", bg=k["panel2"], fg=k["akcent"],
                 font=(CZCIONKA, 22, "bold")).pack(side="left")
        self.liczba_nowa = tk.Label(self.liczby, bg=k["panel2"], fg="#ffffff", font=(CZCIONKA, 38, "bold"))
        self.liczba_nowa.pack(side="left")
        self.liczba_zmiana = tk.Label(self.liczby, bg=k["panel2"], fg=k["akcent"], font=(CZCIONKA, 16, "bold"))
        self.liczba_zmiana.pack(side="left", padx=(14, 0), pady=(10, 0))
        self.etykieta_wynik_pod = tk.Label(wnetrze, bg=k["panel2"], fg=k["szary"], font=(CZCIONKA, 10),
                                           wraplength=440, justify="left", anchor="w")
        self.etykieta_wynik_pod.pack(anchor="w", pady=(6, 10))
        self.przycisk_kopiuj = ttk.Button(wnetrze, text="Kopiuj komendę do konsoli CS2", style="AkcentMaly.TButton",
                                          command=self.kopiuj_komende, state="disabled")
        self.przycisk_kopiuj.pack(anchor="w")

        # Karta oceny (pierścień)
        ocena = self.karta(gora)
        ocena.pack(side="right", fill="y", padx=(16, 0))
        hero.pack_forget()
        hero.pack(side="left", fill="both", expand=True)
        tk.Label(ocena, text="OCENA CELOWANIA", bg=k["panel2"], fg=k["szary"],
                 font=(CZCIONKA, 9, "bold")).pack(anchor="w", padx=18, pady=(14, 0))
        self.pierscien = tk.Canvas(ocena, width=170, height=170, bg=k["panel2"], highlightthickness=0)
        self.pierscien.pack(padx=18, pady=(4, 0))
        self.ocena_pod = tk.Label(ocena, bg=k["panel2"], fg=k["szary"], font=(CZCIONKA, 9))
        self.ocena_pod.pack(pady=(0, 12))

        # Karta wykresu „ocena a czułość”
        wykres_karta = self.karta(t)
        wykres_karta.pack(fill="x", pady=(16, 0))
        naglowek = tk.Frame(wykres_karta, bg=k["panel2"])
        naglowek.pack(fill="x", padx=18, pady=(12, 0))
        tk.Label(naglowek, text="OCENA A CZUŁOŚĆ", bg=k["panel2"], fg=k["szary"],
                 font=(CZCIONKA, 9, "bold")).pack(side="left")
        self.wykres_najlepsza = tk.Label(naglowek, bg=k["panel2"], fg=k["akcent"], font=(CZCIONKA, 9, "bold"))
        self.wykres_najlepsza.pack(side="right")
        self.wykres = tk.Canvas(wykres_karta, height=140, bg=k["panel2"], highlightthickness=0)
        self.wykres.pack(fill="x", padx=18, pady=(0, 10))
        self.wykres.bind("<Configure>", lambda _e: self.rysuj_wykres())
        self.punkty_wykresu = []

        przyciski = ttk.Frame(t, style="Panel.TFrame")
        przyciski.pack(anchor="w", pady=(12, 8))
        ttk.Button(przyciski, text="Analizuj ponownie", command=self.uruchom_analize).pack(side="left", padx=(0, 8))
        ttk.Button(przyciski, text="Usuń sesje z tej czułości", command=self.usun_sesje).pack(side="left")

        # Szczegóły i porady w polu tekstowym z przewijaniem
        ramka = ttk.Frame(t, style="Panel.TFrame")
        ramka.pack(fill="both", expand=True)
        self.tekst_wyniki = tk.Text(ramka, wrap="word", bg=k["pasek"], fg=k["tekst"], relief="flat",
                                    padx=14, pady=10, font=(CZCIONKA, 10), height=6,
                                    highlightthickness=0, cursor="arrow")
        pasek = ttk.Scrollbar(ramka, command=self.tekst_wyniki.yview, style="Vertical.TScrollbar")
        self.tekst_wyniki.config(yscrollcommand=pasek.set)
        pasek.pack(side="right", fill="y")
        self.tekst_wyniki.pack(side="left", fill="both", expand=True)
        tw = self.tekst_wyniki
        tw.tag_config("h", font=(CZCIONKA, 11, "bold"), foreground=KOLOR["akcent"], spacing1=10, spacing3=4)
        tw.tag_config("tytul", font=(CZCIONKA, 10, "bold"), spacing1=8)
        tw.tag_config("szary", foreground=KOLOR["szary"])
        tw.tag_config("mono", font=("Consolas", 10))
        tw.config(state="disabled")
        self.rysuj_pierscien(None)
        return t

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
        c.create_text(85, 82, text=str(ocena), fill="#ffffff", font=(CZCIONKA, 38, "bold"))
        c.create_text(85, 116, text="z 100", fill=k["szary"], font=(CZCIONKA, 9))

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
                          text="Nagraj sesje na kilku czułościach (to samo DPI i rozdzielczość),\n"
                               "a pojawi się tu krzywa „ocena a czułość”.")
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
                c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=k["panel2"], outline=k["akcent"], width=3)
            etykieta = f"{sens:g}" + (" (teraz)" if teraz else "")
            c.create_text(x, wys - 12, text=etykieta, fill=k["tekst"] if teraz else k["szary"],
                          font=(CZCIONKA, 8, "bold" if teraz else "normal"))
        self.wykres_najlepsza.config(text=f"najlepsza: {najlepsza[0]:g}")

    def zeruj_karty(self):
        """Czyści pierścień, wykres i duże liczby przed pokazaniem nowego wyniku."""
        self.liczby.pack_forget()
        self.rysuj_pierscien(None)
        self.ocena_pod.config(text="")
        self.punkty_wykresu = []
        self.wykres_najlepsza.config(text="")
        self.rysuj_wykres()

    def pokaz_liczby(self, stara, nowa, zmiana):
        self.liczba_stara.config(text=f"{stara:g}")
        self.liczba_nowa.config(text=f"{nowa:g}")
        self.liczba_zmiana.config(text=f"{zmiana:+.0%}".replace("-", "−"))
        self.liczby.pack(anchor="w", before=self.etykieta_wynik_pod)

    def zbuduj_ustawienia(self):
        t = self.nowa_zakladka("Ustawienia")
        siatka = ttk.Frame(t, style="Panel.TFrame")
        siatka.pack(fill="x")
        siatka.columnconfigure(2, weight=1)

        ttk.Label(siatka, text="DPI myszki", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=6)
        self.pole_dpi = ttk.Entry(siatka, width=10)
        self.pole_dpi.grid(row=0, column=1, sticky="w", padx=12)
        ttk.Label(siatka, text="z programu producenta myszki (G Hub, Synapse…)",
                  style="PanelSzary.TLabel").grid(row=0, column=2, sticky="w")

        ttk.Label(siatka, text="Czułość w CS2", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        self.pole_sens = ttk.Entry(siatka, width=10)
        self.pole_sens.grid(row=1, column=1, sticky="w", padx=12)
        ttk.Button(siatka, text="Odczytaj z CS2", command=self.odczytaj_sens).grid(row=1, column=2, sticky="w")

        ttk.Label(siatka, text="Rozdzielczość w CS2", style="Panel.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        self.pole_rozdz = ttk.Combobox(siatka, width=12, values=rozdz.TYPOWE)
        self.pole_rozdz.grid(row=2, column=1, sticky="w", padx=12)
        ttk.Button(siatka, text="Odczytaj z CS2", command=self.odczytaj_rozdz).grid(row=2, column=2, sticky="w")

        ttk.Label(siatka, text="Monitor", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=6)
        self.pole_monitor = ttk.Entry(siatka, width=12)
        self.pole_monitor.grid(row=3, column=1, sticky="w", padx=12)
        ttk.Label(siatka, text="wykryty z Windows – popraw, jeśli grasz na innym",
                  style="PanelSzary.TLabel").grid(row=3, column=2, sticky="w")

        ttk.Label(siatka, text="Obraz 4:3 / 5:4", style="Panel.TLabel").grid(row=4, column=0, sticky="w", pady=6)
        self.pole_skalowanie = ttk.Combobox(siatka, width=12, state="readonly",
                                            values=["rozciągnięty", "czarne paski"])
        self.pole_skalowanie.grid(row=4, column=1, sticky="w", padx=12)
        ttk.Label(siatka, text="gdy proporcje gry są inne niż monitora",
                  style="PanelSzary.TLabel").grid(row=4, column=2, sticky="w")

        for pole, klucz in ((self.pole_dpi, "dpi"), (self.pole_sens, "sens"), (self.pole_monitor, "monitor")):
            if self.ust.get(klucz):
                pole.insert(0, str(self.ust[klucz]))
        self.pole_rozdz.set(self.ust.get("rozdzielczosc", ""))
        self.pole_skalowanie.set("czarne paski" if self.ust.get("skalowanie") == "paski" else "rozciągnięty")

        self.info_obrazu = ttk.Label(t, style="PanelSzary.TLabel", wraplength=720, justify="left",
                                     font=("Consolas", 9))
        self.info_obrazu.pack(anchor="w", pady=(6, 0))
        ttk.Button(t, text="Zapisz", style="AkcentMaly.TButton", command=self.zapisz_ustawienia).pack(anchor="w", pady=(10, 4))
        self.info_ustawien = ttk.Label(t, style="PanelSzary.TLabel", wraplength=700, justify="left")
        self.info_ustawien.pack(anchor="w")
        self.odswiez_ocene_obrazu()

        ttk.Separator(t).pack(fill="x", pady=12)
        ttk.Label(t, text="Połączenie z CS2 (plik GSI)", style="Panel.TLabel",
                  font=(CZCIONKA, 11, "bold")).pack(anchor="w")
        self.etykieta_folder = ttk.Label(t, style="PanelSzary.TLabel", wraplength=700, justify="left")
        self.etykieta_folder.pack(anchor="w", pady=(4, 8))
        rzad = ttk.Frame(t, style="Panel.TFrame")
        rzad.pack(anchor="w")
        ttk.Button(rzad, text="Zainstaluj plik GSI", command=self.instaluj_gsi).pack(side="left", padx=(0, 8))
        ttk.Button(rzad, text="Wybierz folder CS2…", command=self.wybierz_folder).pack(side="left")

        ttk.Separator(t).pack(fill="x", pady=16)
        ttk.Label(t, text=f"Dane programu: {kfg.FOLDER}", style="PanelSzary.TLabel").pack(anchor="w")
        rzad = ttk.Frame(t, style="Panel.TFrame")
        rzad.pack(fill="x", pady=(6, 0))
        ttk.Button(rzad, text="Otwórz folder z danymi", command=self.otworz_folder).pack(side="left")
        if self.uzytkownik.get("nazwa"):
            ttk.Button(rzad, text="Wyloguj", command=self.wyloguj).pack(side="right")
            ttk.Label(rzad, text=f"Discord: {self.uzytkownik['nazwa']}",
                      style="PanelSzary.TLabel").pack(side="right", padx=(0, 10))
        self.odswiez_folder()
        return t

    def zbuduj_pomoc(self):
        t = self.nowa_zakladka("Pomoc")
        tekst = tk.Text(t, wrap="word", bg=KOLOR["panel"], fg=KOLOR["tekst"], relief="flat",
                        font=(CZCIONKA, 10), highlightthickness=0, padx=4, cursor="arrow")
        tekst.pack(fill="both", expand=True)
        tekst.tag_config("h", font=(CZCIONKA, 11, "bold"), foreground=KOLOR["akcent"], spacing1=10, spacing3=4)
        tekst.tag_config("szary", foreground=KOLOR["szary"])
        tresc = [
            ("Pierwsze uruchomienie\n", "h"),
            ("1. Ustawienia → wpisz DPI myszki i kliknij Zapisz. Czułość program odczyta sam z CS2.\n"
             "2. Kliknij „Zainstaluj plik GSI”, a potem uruchom CS2 ponownie.\n", None),
            ("Nagrywanie\n", "h"),
            ("3. Nagrywanie → Rozpocznij nagrywanie. Zielona kropka przy „CS2” oznacza, że gra wysyła dane.\n"
             "4. Graj 20–30 min (deathmatch, karabin lub pistolet). Status NAGRYWAM pojawia się, gdy żyjesz i "
             "trzymasz broń.\n"
             "5. Wróć do SensFit i kliknij „Zakończ i analizuj”.\n", None),
            ("Wyniki\n", "h"),
            ("Zalecenie mówi, czy zmienić czułość. Kliknij „Kopiuj komendę”, w CS2 otwórz konsolę (~) i wklej. "
             "Graj na nowej czułości 3–4 dni, potem nagraj nową sesję. Kolejne sesje na tej samej czułości "
             "są łączone, więc wynik jest coraz dokładniejszy.\n", None),
            ("Jak program ocenia\n", "h"),
            ("Flicki zakończone zabójstwem (dane z GSI) liczą się potrójnie, a te, w których śledziłeś ruchomy "
             "cel – w połowie. Ruch w trakcie serii (kontrola odrzutu) jest pomijany. Podnoszenie myszy w trakcie "
             "obrotu wskazuje na za niską czułość, a drżenie celownika na za wysoką. Ocena celowania (0–100) "
             "pozwala porównać różne czułości – SensFit pokazuje oceny ze wszystkich czułości, na których "
             "nagrywałeś.\n", None),
            ("Rozdzielczość\n", "h"),
            ("cm/360 w CS2 nie zależy od rozdzielczości. Zmienia się pole widzenia i – przy obrazie 4:3 "
             "rozciągniętym – szybkość, z jaką obraz przesuwa się w poziomie. Ustaw rozdzielczość w zakładce "
             "Ustawienia; sesje z różnych rozdzielczości są liczone osobno.\n", None),
            ("Problemy\n", "h"),
            ("Czerwona kropka przy CS2: plik GSI nie jest zainstalowany albo gra nie była zrestartowana. "
             "Jeśli program nie znalazł gry, wskaż folder „Counter-Strike Global Offensive” przyciskiem "
             "„Wybierz folder CS2”.\n"
             "Program nie czyta pamięci gry i nic do niej nie wysyła – korzysta z oficjalnej funkcji GSI od Valve.\n",
             None),
            (f"\nSensFit {WERSJA}", "szary"),
        ]
        for fragment, tag in tresc:
            tekst.insert("end", fragment, tag)
        tekst.config(state="disabled")
        return t

    # ------------------------------------------------------------------ odświeżanie widoków
    def odswiez_naglowek(self):
        sens, dpi = self.ust["sens"], self.ust["dpi"]
        if sens and dpi:
            gra, _, _ = self.obraz()
            o = self.ocena_obrazu()
            obraz = (f"  ·  {gra[0]}×{gra[1]}" + (" rozc." if o and o["rozciagniete"] else "")) if gra else ""
            self.naglowek.config(text=f"sens {sens}  ·  {dpi} DPI  ·  eDPI {kfg.edpi(sens, dpi):.0f}  ·  "
                                      f"{kfg.cm_na_360(sens, dpi):.1f} cm/360°{obraz}")
        else:
            self.naglowek.config(text="uzupełnij ustawienia")

    def odswiez_statusy(self):
        if self.mysz_ok:
            self.ustaw_status(self.status_mysz, True, "Odczyt myszy działa")
        else:
            self.ustaw_status(self.status_mysz, False, f"Odczyt myszy nie działa: {self.nagrywacz.blad}")

        if kfg.gsi_zainstalowane(self.ust["folder_cfg"]):
            self.ustaw_status(self.status_gsi, True, "Plik GSI zainstalowany w CS2")
        else:
            self.ustaw_status(self.status_gsi, False, "Plik GSI nie jest zainstalowany – zakładka Ustawienia")

        if self.blad_gsi:
            self.ustaw_status(self.status_cs2, False, self.blad_gsi)
        elif self.cs2_polaczone():
            self.ustaw_status(self.status_cs2, True, "CS2 wysyła dane")
        else:
            self.ustaw_status(self.status_cs2, None, "Brak sygnału z CS2 – uruchom grę (po instalacji pliku: restart)")

        if self.blad_gsi:
            self.kropka_menu.config(fg=KOLOR["zle"])
            self.tekst_menu.config(text="CS2: błąd portu")
        elif self.cs2_polaczone():
            self.kropka_menu.config(fg=KOLOR["ok"])
            self.tekst_menu.config(text="CS2 wysyła dane")
        else:
            self.kropka_menu.config(fg=KOLOR["uwaga"])
            self.tekst_menu.config(text="CS2: brak sygnału")

        if self.nagrywanie and self.czy_nagrywac():
            self.etykieta_stan.config(text="● NAGRYWAM", foreground=KOLOR["ok"])
            self.etykieta_powod.config(text="ruch myszy jest zapisywany" if self.bez_gsi else self.stan.powod)
        elif self.nagrywanie:
            self.etykieta_stan.config(text="❚❚ PAUZA", foreground=KOLOR["uwaga"])
            self.etykieta_powod.config(text=self.stan.powod)
        else:
            self.etykieta_stan.config(text="Gotowy do nagrywania", foreground=KOLOR["tekst"])
            self.etykieta_powod.config(text="")
        minuty, sekundy = divmod(int(self.czas_gry_s), 60)
        self.licznik_czas.config(text=f"{minuty}:{sekundy:02d}")
        self.licznik_strzaly.config(text=str(len(self.nagrywacz.klikniecia)))
        self.licznik_zabojstw.config(text=str(len(self.stan.zabojstwa)))

    def odswiez_folder(self):
        folder = self.ust["folder_cfg"]
        self.etykieta_folder.config(text=f"Folder CS2: {folder}" if folder else
                                    "Nie znaleziono folderu CS2 – wskaż go ręcznie.")

    def pokaz_info_ustawien(self, tekst, rodzaj="ok"):
        self.info_ustawien.config(text=tekst, foreground=KOLOR[rodzaj])

    def odswiez_ocene_obrazu(self):
        """Podsumowanie wpływu rozdzielczości pod polami w Ustawieniach."""
        o = self.ocena_obrazu() if self.ust.get("sens") and self.ust.get("dpi") else None
        self.info_obrazu.config(text="\n".join(rozdz.opis(o)) if o else "")

    def wstaw_obraz(self, tw, ocena):
        if not ocena:
            return
        tw.insert("end", "Obraz i rozdzielczość\n", "h")
        tw.insert("end", "cm/360 nie zależy od rozdzielczości, ale zmienia się pole widzenia i to, "
                         "jak szybko obraz przesuwa się na monitorze\n", "szary")
        for linia in rozdz.opis(ocena):
            tw.insert("end", linia + "\n", "mono")

    def pokaz_wynik(self, w, info, sens, dpi):
        tw = self.tekst_wyniki
        ocena = self.ocena_obrazu(sens)
        tw.config(state="normal")
        tw.delete("1.0", "end")
        self.przycisk_kopiuj.config(state="disabled")
        self.komenda = None
        self.zeruj_karty()

        if w is None:
            self.etykieta_wynik.config(text="Brak wyników – nagraj pierwszą sesję.", foreground=KOLOR["tekst"])
            self.etykieta_wynik_pod.config(text=f"Sesje są liczone osobno dla każdej czułości, DPI i "
                                                f"rozdzielczości (teraz: sens {sens}, {dpi} DPI, "
                                                f"{self.klucz_obrazu() or 'rozdzielczość nieznana'}).")
            self.wstaw_obraz(tw, ocena)
            for i, (tytul, co, jak) in enumerate(rozdz.porady(ocena, sens), 1):
                tw.insert("end", f"{i}. {tytul}\n", "tytul")
                tw.insert("end", f"{co}\n", "szary")
                tw.insert("end", f"Jak: {jak}\n")
            tw.config(state="disabled")
            return

        pod = f"{info['sesje']} sesji · ok. {info['minuty']:.0f} min gry · {w['liczba']} flicków zakończonych strzałem"
        if "r_mediana" not in w:
            self.etykieta_wynik.config(text="Za mało danych do oceny", foreground=KOLOR["uwaga"])
            self.etykieta_wynik_pod.config(text=pod + ". Zagraj dłużej – potrzeba co najmniej kilkudziesięciu flicków.")
            self.wstaw_obraz(tw, ocena)
            tw.config(state="disabled")
            return

        nowa = w["nowa_sens"]
        if nowa != sens:
            self.etykieta_wynik.config(text="Zmień czułość", foreground=KOLOR["tekst"])
            self.pokaz_liczby(sens, nowa, w["zmiana"])
            pod += f"\nNowe eDPI {kfg.edpi(nowa, dpi):.0f} · {kfg.cm_na_360(nowa, dpi):.1f} cm/360°"
            self.komenda = f"sensitivity {nowa}"
            self.przycisk_kopiuj.config(state="normal")
            nowa_ocena = self.ocena_obrazu(nowa)  # czy przy nowej czułości celownik nie zacznie skakać po pikselach
            if nowa_ocena and nowa_ocena["stosunek"] > 1 and nowa_ocena["propozycja"]:
                d, s2 = nowa_ocena["propozycja"]
                pod += (f"\nPrzy sens {nowa} celownik przeskakiwałby piksele w {self.ust['rozdzielczosc']} – "
                        f"lepiej ustaw DPI {d} i sens {s2} (ta sama czułość)")
            pod += "\n" + raport.ZRODLA.get(w.get("zrodlo"), "")
        else:
            self.etykieta_wynik.config(text="Czułość wygląda dobrze", foreground=KOLOR["ok"])
            pod += "\nBrak wyraźnego sygnału, żeby ją zmieniać."
        if w["liczba"] < raport.MIN_FLICKOW:
            pod += f"\nUwaga: tylko {w['liczba']} flicków (zalecane {raport.MIN_FLICKOW}+) – traktuj wynik ostrożnie."
        self.etykieta_wynik_pod.config(text=pod)

        # Pierścień oceny i wykres „ocena a czułość”
        self.rysuj_pierscien(w["ocena"])
        self.ocena_pod.config(text=f"{w['liczba']} flicków")
        self.punkty_wykresu = [(s2, o2, False) for s2, o2, _ in (info.get("porownanie") or [])]
        self.punkty_wykresu.append((sens, w["ocena"], True))
        self.rysuj_wykres()

        tw.insert("end", "Gdzie kończy się Twój ruch główny\n", "h")
        tw.insert("end", "100% = dokładnie na celu, 95% = idealnie (lekkie niedociągnięcie jest naturalne)\n", "szary")
        tw.insert("end", f"mediana {w['r_mediana']:.0%} (±{w['niepewnosc']:.0%})   "
                         f"przestrzał {w['przestrzal']:.0%}   w punkt {w['w_punkt']:.0%}   "
                         f"niedociągnięcie {w['niedociagniecie']:.0%}\n", "mono")
        for klucz, (r, n) in w.get("grupy", {}).items():
            tw.insert("end", f"flicki {raport.NAZWY_GRUP.get(klucz, klucz)}: {r:.0%}  (n={n})\n", "mono")

        tw.insert("end", f"Ocena celowania: {w['ocena']}/100\n", "h")
        linie = raport.linie_oceny(w, info)
        tw.insert("end", "służy do porównywania czułości ze sobą – liczy celność, rozrzut, korekty i tempo\n", "szary")
        for linia in linie[1:]:
            tw.insert("end", linia + "\n", "mono")
        porownanie = raport.linie_porownania(info, sens, w["ocena"])
        if porownanie:
            tw.insert("end", "Na innych czułościach (to samo DPI i rozdzielczość)\n", "tytul")
            for linia in porownanie:
                tw.insert("end", linia + "\n", "mono")
        if w.get("sygnaly"):
            tw.insert("end", "Sygnały\n", "h")
            for s in w["sygnaly"]:
                tw.insert("end", "• " + raport.opis_sygnalu(s) + "\n")
        self.wstaw_obraz(tw, ocena)

        porady = raport.porady(w) + rozdz.porady(ocena, sens)
        tw.insert("end", "Co poprawić\n", "h")
        if not porady:
            tw.insert("end", "Nie widać wyraźnych problemów. Tak trzymaj.\n")
        for i, (tytul, co, jak) in enumerate(porady, 1):
            tw.insert("end", f"{i}. {tytul}\n", "tytul")
            tw.insert("end", f"{co}\n", "szary")
            tw.insert("end", f"Jak: {jak}\n")
        tw.config(state="disabled")

    # ------------------------------------------------------------------ akcje przycisków
    def zapisz_ustawienia(self):
        try:
            dpi = int(float(self.pole_dpi.get().replace(",", ".")))
            sens = round(float(self.pole_sens.get().replace(",", ".")), 4)
            if not (50 <= dpi <= 50000 and 0.01 <= sens <= 20):
                raise ValueError
        except ValueError:
            self.pokaz_info_ustawien("DPI musi być liczbą 50–50000, a czułość liczbą 0.01–20 (np. 1.25).", "zle")
            return
        gra, monitor = rozdz.parsuj(self.pole_rozdz.get()), rozdz.parsuj(self.pole_monitor.get())
        if not gra or not monitor:
            self.pokaz_info_ustawien("Rozdzielczość wpisz jako szerokość x wysokość, np. 1280x960.", "zle")
            return
        self.ust["dpi"], self.ust["sens"] = dpi, sens
        self.ust["rozdzielczosc"], self.ust["monitor"] = f"{gra[0]}x{gra[1]}", f"{monitor[0]}x{monitor[1]}"
        self.ust["skalowanie"] = "paski" if self.pole_skalowanie.get() == "czarne paski" else "rozciagniete"
        try:
            kfg.zapisz_ustawienia(self.ust)
        except OSError as e:
            self.pokaz_info_ustawien(f"Nie udało się zapisać: {e}", "zle")
            return
        self.pokaz_info_ustawien("Zapisano.", "ok")
        self.odswiez_naglowek()
        self.odswiez_ocene_obrazu()
        self.uruchom_analize()

    def odczytaj_rozdz(self):
        gra = rozdz.odczytaj_z_cs2(kfg.folder_steam())
        if gra is None:
            self.pokaz_info_ustawien("Nie znaleziono ustawień wideo CS2 – wybierz rozdzielczość z listy "
                                     "albo wpisz ją ręcznie (np. 1280x960).", "uwaga")
            return
        self.pole_rozdz.set(f"{gra[0]}x{gra[1]}")
        self.pokaz_info_ustawien(f"Odczytano z CS2: {gra[0]}x{gra[1]}. Kliknij Zapisz.", "ok")

    def odczytaj_sens(self):
        sens = kfg.odczytaj_sens_z_cs2()
        if sens is None:
            self.pokaz_info_ustawien("Nie znaleziono ustawień CS2 – wpisz czułość ręcznie.", "uwaga")
            return
        self.pole_sens.delete(0, "end")
        self.pole_sens.insert(0, str(sens))
        self.pokaz_info_ustawien(f"Odczytano z CS2: {sens}. Kliknij Zapisz.", "ok")

    def instaluj_gsi(self):
        ok, komunikat = kfg.zainstaluj_gsi(self.ust["folder_cfg"])
        self.pokaz_info_ustawien(komunikat, "ok" if ok else "zle")

    def wybierz_folder(self):
        wybrany = filedialog.askdirectory(title="Wskaż folder Counter-Strike Global Offensive")
        if not wybrany:
            return
        cfg = kfg.popraw_folder_cs2(wybrany)
        if not cfg:
            self.pokaz_info_ustawien("W tym folderze nie ma CS2. Wskaż folder „Counter-Strike Global "
                                     "Offensive” (w Steam: PPM na CS2 → Zarządzaj → Przeglądaj pliki lokalne).", "zle")
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
        if messagebox.askyesno("SensFit", "Wylogować? Program się zamknie, a przy następnym "
                                          "uruchomieniu trzeba będzie zalogować się przez Discord."):
            dostep.usun_bilet()
            self.root.destroy()

    def kopiuj_komende(self):
        if self.komenda:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.komenda)
            self.przycisk_kopiuj.config(text="Skopiowano – wklej w konsoli CS2 (~)")
            self.root.after(3000, lambda: self.przycisk_kopiuj.config(text="Kopiuj komendę do konsoli CS2"))

    def usun_sesje(self):
        sens, dpi = self.ust["sens"], self.ust["dpi"]
        if messagebox.askyesno("SensFit", f"Usunąć wszystkie sesje nagrane na sens {sens}, {dpi} DPI i {self.klucz_obrazu()}?"):
            sesje.usun(sens, dpi, self.klucz_obrazu())
            self.uruchom_analize()


def main():
    if sys.platform == "win32":
        try:  # ostre czcionki na monitorach ze skalowaniem 125–150%
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    EkranDostepu(root, lambda uzytkownik: Aplikacja(root, uzytkownik))
    root.mainloop()

