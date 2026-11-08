"""Saving recorded sessions to disk and analysing all sessions for the current settings.

Sessions are only combined when the eDPI (sensitivity x DPI) and the display settings (resolution
and stretching) match, because a player aims differently on a different setting. Sessions with a
different DPI but the same eDPI (for example 400 x 2.4 and 800 x 1.2) count together, since the
hand movement gives the same camera rotation.

Other details:
- eDPI is computed with the m_yaw that was read (a different m_yaw means a different rotation at
  the same sens x DPI),
- the merge tolerance is 2% (0.74 and 0.743 are one setting),
- the flicks of every file are computed once and cached, so the raw movement does not stay in memory,
- the direction from recent sessions and the ratchet lock (analiza.zastosuj_zgodnosc and zastosuj_zapadke).
"""
import glob
import json
import os
from datetime import datetime

import analiza
import raport
import wersja
from konfiguracja import FOLDER, FOLDER_SESJI, M_YAW, zapisz_json

TOLERANCJA_EDPI = 0.02
POLA_META = ("wersja", "sens", "dpi", "obraz", "minuty", "m_yaw", "m_pitch")
_pamiec = {}  # (file, modification time) -> (meta, (flicks, shots in movement, extras) or None)


def zapisz(sens, dpi, minuty, kubelki, klikniecia, obraz=None, puszczenia=None, zabojstwa=None,
           m_yaw=M_YAW, m_pitch=M_YAW):
    plik = os.path.join(FOLDER_SESJI, f"sesja_{datetime.now():%Y%m%d_%H%M%S}.json")
    zapisz_json(plik, {"wersja": wersja.NUMER, "sens": sens, "dpi": dpi, "obraz": obraz, "minuty": minuty,
                       "m_yaw": m_yaw, "m_pitch": m_pitch, "kubelki": kubelki, "klikniecia": klikniecia,
                       "puszczenia": puszczenia or [], "zabojstwa": zabojstwa or []})
    return plik


def _wpis(plik):
    """Session meta from memory or from disk (raw data is turned into flicks right away and then dropped)."""
    klucz = (plik, os.path.getmtime(plik))
    if klucz not in _pamiec:
        with open(plik, encoding="utf-8") as f:
            dane = json.load(f)
        meta = {k: dane.get(k) for k in POLA_META}
        meta["dzien"] = os.path.basename(plik)[6:14]
        przetworzone = None
        if dane.get("sens") and dane.get("kubelki"):
            przetworzone = analiza.znajdz_flicki(dane["kubelki"], dane["klikniecia"], dane["sens"],
                                                 dane.get("puszczenia"), dane.get("zabojstwa"),
                                                 dane.get("dpi"), dane.get("m_yaw") or M_YAW, dane.get("m_pitch"))
        _pamiec[klucz] = (meta, przetworzone)
    return _pamiec[klucz]


def wszystkie():
    """All stored sessions: a list of (file, meta). Meta holds sens, dpi, obraz, minuty, m_yaw and dzien."""
    wynik = []
    for plik in sorted(glob.glob(os.path.join(FOLDER_SESJI, "sesja_*.json"))):
        try:
            wynik.append((plik, _wpis(plik)[0]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return wynik


def edpi_obrotu(sens, dpi, m_yaw=None):
    """eDPI converted to m_yaw 0.022, comparable between players with a different m_yaw."""
    return sens * dpi * (m_yaw or M_YAW) / M_YAW


def to_samo_edpi(sens_a, dpi_a, sens_b, dpi_b, m_yaw_a=None, m_yaw_b=None):
    """eDPI values equal within TOLERANCJA_EDPI."""
    try:
        a, b = edpi_obrotu(sens_a, dpi_a, m_yaw_a), edpi_obrotu(sens_b, dpi_b, m_yaw_b)
    except TypeError:
        return False
    return a > 0 and abs(a - b) <= TOLERANCJA_EDPI * a


def pliki_dla(sens, dpi, obraz=None, sesje=None, m_yaw=None):
    """Sessions recorded with the same eDPI and display settings.

    Sessions from version 0.9.1 and older have no stored resolution, so they are always included.
    """
    return [(p, d) for p, d in (sesje if sesje is not None else wszystkie())
            if to_samo_edpi(d.get("sens"), d.get("dpi"), sens, dpi, d.get("m_yaw"), m_yaw)
            and d.get("obraz") in (None, obraz)]


def _policz(sesje, sens):
    """Analysis of a list of sessions with the same eDPI. Returns (result, info).

    Every session is computed with its own sensitivity (degrees per count) and the recommendation is given for `sens`.
    info["kierunki"] holds the direction of each session separately (oldest first).
    """
    flicki, w_ruchu, dodatkowe, minuty, kierunki = [], 0, [], 0.0, []
    for plik, meta in sesje:
        przetworzone = _wpis(plik)[1]
        if not przetworzone:
            continue
        f_sesji, wr, dod = przetworzone
        flicki += f_sesji
        w_ruchu += wr
        dodatkowe.append(dod)
        minuty += meta.get("minuty") or 0
        kierunki.append(analiza.kierunek_sesji(f_sesji))
    polaczone = analiza.polacz_dodatkowe(dodatkowe)
    wynik = analiza.podsumuj(flicki, w_ruchu, sens, polaczone, minuty)
    info = {"sesje": len(sesje), "minuty": minuty, "kierunki": kierunki,
            "z_zabojstwami": sum(1 for d in dodatkowe if d["ma_zabojstwa"])}
    return wynik, info


def _grupy_edpi(sesje, pomin):
    """Sessions of other settings, grouped when they differ by less than TOLERANCJA_EDPI."""
    lista = sorted((edpi_obrotu(d["sens"], d["dpi"], d.get("m_yaw")), p, d) for p, d in sesje)
    grupy = []
    for e, p, d in lista:
        if abs(e - pomin) <= TOLERANCJA_EDPI * pomin:
            continue
        if grupy and e - grupy[-1][0] <= TOLERANCJA_EDPI * grupy[-1][0]:
            grupy[-1][1].append((p, d))
        else:
            grupy.append((e, [(p, d)]))
    return grupy


def porownanie(dpi, obraz, sesje, pomin_sens, m_yaw=None):
    """Aim score on other settings (same picture).

    Returns a list of dicts {sens, ocena, pm, flicki, dni, r_mediana}. The sensitivity is converted to the
    current DPI and m_yaw, so the history does not vanish after a DPI change (400 x 2.4 shows up as 1.2 at 800 DPI).
    """
    pasujace = [(p, d) for p, d in sesje if d.get("sens") and d.get("dpi") and d.get("obraz") in (None, obraz)]
    obecne = edpi_obrotu(pomin_sens, dpi, m_yaw)
    grupy = sorted(_grupy_edpi(pasujace, obecne), key=lambda g: abs(g[0] - obecne))[:6]  # at most 6
    wynik = []
    for e, grupa in sorted(grupy, key=lambda g: g[0]):
        s = round(e / edpi_obrotu(1, dpi, m_yaw), 3)
        w, _ = _policz(grupa, s)
        if "ocena" in w:
            wynik.append({"sens": s, "ocena": w["ocena"], "pm": w["ocena_pm"], "flicki": w["liczba"],
                          "dni": len({d["dzien"] for _, d in grupa}), "r_mediana": w["r_mediana"]})
    return wynik


def poprzednie_ustawienie(sens, dpi):
    """(sens, dpi) from before the last eDPI change according to the log, or None."""
    import dziennik  # imported here, because dziennik imports sesje
    wpisy = dziennik.wczytaj()
    for i in range(len(wpisy) - 1, -1, -1):
        if to_samo_edpi(wpisy[i].get("sens"), wpisy[i].get("dpi"), sens, dpi):
            for poprzedni in reversed(wpisy[:i]):
                if not to_samo_edpi(poprzedni.get("sens"), poprzedni.get("dpi"), sens, dpi):
                    return poprzedni["sens"], poprzedni["dpi"]
            return None
    return None


def analizuj(sens, dpi, obraz=None, ocena_obrazu=None, m_yaw=None):
    """Returns (analysis result, info) or (None, info) when there are no sessions."""
    wszystkie_sesje = wszystkie()
    sesje = pliki_dla(sens, dpi, obraz, wszystkie_sesje, m_yaw)
    info = {"sesje": len(sesje), "minuty": sum(d.get("minuty") or 0 for _, d in sesje)}
    if not sesje:
        return None, info

    wynik, info = _policz(sesje, sens)
    info["porownanie"] = porownanie(dpi, obraz, wszystkie_sesje, sens, m_yaw)
    analiza.zastosuj_zgodnosc(wynik, sens, info["kierunki"])
    analiza.zastosuj_krzywa(wynik, sens, info["porownanie"])
    poprzednie = poprzednie_ustawienie(sens, dpi)
    if poprzednie:
        e = edpi_obrotu(*poprzednie)
        punkt = [p for p in info["porownanie"] if abs(edpi_obrotu(p["sens"], dpi, m_yaw) - e) <= TOLERANCJA_EDPI * e]
        if punkt:
            analiza.zastosuj_zapadke(wynik, sens, punkt[0])
    # A copy of the report in a text file, easy to send to someone for comparison
    tekst = raport.formatuj(wynik, sens, dpi, info["sesje"], info["minuty"], ocena_obrazu, info)
    try:
        with open(os.path.join(FOLDER, "ostatni_raport.txt"), "w", encoding="utf-8") as f:
            f.write(tekst)
    except OSError:
        pass
    return wynik, info


def usun(sens, dpi, obraz=None, m_yaw=None):
    for plik, _ in pliki_dla(sens, dpi, obraz, m_yaw=m_yaw):
        try:
            os.remove(plik)
        except OSError:
            pass
