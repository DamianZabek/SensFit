"""Settings log: when the sensitivity or DPI changed.

The program adds an entry itself when a different sensitivity shows up in the CS2 files or when a
different DPI is saved in Settings. This way every session can be assigned to a specific setting.
File: %APPDATA%\\SensFit\\dziennik_ustawien.json (list of entries, oldest first).
"""
import json
import os
from datetime import datetime

import sesje
from jezyk import t
from konfiguracja import FOLDER, zapisz_json

PLIK = os.path.join(FOLDER, "dziennik_ustawien.json")
MAKS_WPISOW = 500


def wczytaj():
    try:
        with open(PLIK, encoding="utf-8") as f:
            wpisy = json.load(f)
        return [w for w in wpisy if isinstance(w, dict) and "czas" in w]
    except (OSError, ValueError):
        return []


def _zapisz(wpisy):
    zapisz_json(PLIK, wpisy[-MAKS_WPISOW:], indent=1)


def zanotuj(sens, dpi, zrodlo):
    """Adds an entry when the sensitivity or DPI differs from the last entry. Returns the entry or None.

    zrodlo: "cs2" (detected in the CS2 files) or "ustawienia" (saved in the program).
    """
    if not sens or not dpi:
        return None
    wpisy = wczytaj()
    ostatni = wpisy[-1] if wpisy else None
    if ostatni and ostatni.get("sens") == sens and ostatni.get("dpi") == dpi:
        return None
    wpis = {"czas": datetime.now().isoformat(timespec="seconds"), "sens": sens, "dpi": dpi,
            "zrodlo": zrodlo if ostatni else "start",
            "poprzedni": {"sens": ostatni["sens"], "dpi": ostatni["dpi"]} if ostatni else None}
    wpisy.append(wpis)
    try:
        _zapisz(wpisy)
    except OSError:
        return None
    return wpis


def _czas_sesji(plik):
    """Recording time taken from the file name sesja_RRRRMMDD_GGMMSS.json, or None."""
    try:
        return datetime.strptime(os.path.basename(plik)[6:21], "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def liczba_sesji_tekst(n):
    if n == 1:
        return t("1 sesja", "1 session")
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return t(f"{n} sesje", f"{n} sessions")
    return t(f"{n} sesji", f"{n} sessions")


def tytul(wpis):
    p = wpis.get("poprzedni")
    if not p:
        return t(f"Pierwsze ustawienie: czułość {wpis['sens']:g}, {wpis['dpi']} DPI",
                 f"First setup: sensitivity {wpis['sens']:g}, {wpis['dpi']} DPI")
    czesci = []
    if p["dpi"] != wpis["dpi"]:
        czesci.append(f"DPI {p['dpi']} → {wpis['dpi']}")
    if p["sens"] != wpis["sens"]:
        czesci.append(t("czułość", "sensitivity") + f" {p['sens']:g} → {wpis['sens']:g}")
    tekst = ", ".join(czesci)
    return tekst[:1].upper() + tekst[1:]


def opis(wpis):
    """Extra line: eDPI unchanged, or an empty string."""
    p = wpis.get("poprzedni")
    if p and p["dpi"] != wpis["dpi"] and sesje.to_samo_edpi(p["sens"], p["dpi"], wpis["sens"], wpis["dpi"]):
        e = wpis["sens"] * wpis["dpi"]
        return t(f"eDPI bez zmian ({e:.0f}), więc sesje liczą się razem.",
                 f"eDPI unchanged ({e:.0f}), so the sessions are counted together.")
    return ""


def statystyki(wpisy=None, wszystkie_sesje=None, maks=12):
    """Latest entries (newest first) with the number of sessions and the aim score.

    A session belongs to an entry when it was recorded after that entry and before the next one, on the
    same eDPI. Sessions from before the first entry belong to the first entry. Computing the score takes
    time, so call this from a separate thread. Returns a list of (entry, session count, score or None).
    """
    wpisy = wczytaj() if wpisy is None else wpisy
    wszystkie_sesje = sesje.wszystkie() if wszystkie_sesje is None else wszystkie_sesje
    wynik = []
    for i in range(len(wpisy) - 1, max(-1, len(wpisy) - 1 - maks), -1):
        wpis = wpisy[i]
        od = datetime.fromisoformat(wpis["czas"]) if i > 0 else None
        do = datetime.fromisoformat(wpisy[i + 1]["czas"]) if i + 1 < len(wpisy) else None
        pasujace = []
        for plik, dane in wszystkie_sesje:
            kiedy = _czas_sesji(plik)
            if kiedy is None or (od and kiedy < od) or (do and kiedy >= do):
                continue
            if sesje.to_samo_edpi(dane.get("sens"), dane.get("dpi"), wpis["sens"], wpis["dpi"]):
                pasujace.append((plik, dane))
        ocena = None
        if pasujace:
            try:
                w, _ = sesje._policz(pasujace, wpis["sens"])
                ocena = w.get("ocena")
            except Exception:  # a damaged session must not block the log
                ocena = None
        wynik.append((wpis, len(pasujace), ocena))
    return wynik
