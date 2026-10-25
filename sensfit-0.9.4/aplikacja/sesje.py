import glob
import json
import os
from datetime import datetime

import analiza
import raport
from konfiguracja import FOLDER, FOLDER_SESJI


def zapisz(sens, dpi, minuty, kubelki, klikniecia, obraz=None, puszczenia=None, zabojstwa=None):
    os.makedirs(FOLDER_SESJI, exist_ok=True)
    plik = os.path.join(FOLDER_SESJI, f"sesja_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(plik, "w", encoding="utf-8") as f:
        json.dump({"wersja": "0.9.3", "sens": sens, "dpi": dpi, "obraz": obraz, "minuty": minuty,
                   "kubelki": kubelki, "klikniecia": klikniecia,
                   "puszczenia": puszczenia or [], "zabojstwa": zabojstwa or []}, f)
    return plik


def wszystkie():
    """Wszystkie zapisane sesje: lista (plik, dane)."""
    wynik = []
    for plik in sorted(glob.glob(os.path.join(FOLDER_SESJI, "sesja_*.json"))):
        try:
            with open(plik, encoding="utf-8") as f:
                wynik.append((plik, json.load(f)))
        except (OSError, ValueError):
            continue
    return wynik


def pliki_dla(sens, dpi, obraz=None, sesje=None):
    """Sesje nagrane na tej samej czułości, DPI i ustawieniach obrazu.

    Sesje z wersji 0.9.1 i starszych nie mają zapisanej rozdzielczości - liczymy je zawsze.
    """
    return [(p, d) for p, d in (sesje if sesje is not None else wszystkie())
            if d.get("sens") == sens and d.get("dpi") == dpi and d.get("obraz") in (None, obraz)]


def _policz(sesje, sens):
    """Analiza listy sesji tej samej czułości. Zwraca (wynik, info)."""
    flicki, w_ruchu, dodatkowe, minuty = [], 0, [], 0.0
    for _, dane in sesje:
        # Starsze sesje nie mają puszczeń ani zabójstw (None = brak danych, nie "zero zabójstw")
        f_sesji, wr, dod = analiza.znajdz_flicki(dane["kubelki"], dane["klikniecia"], sens,
                                                  dane.get("puszczenia"), dane.get("zabojstwa"))
        flicki += f_sesji
        w_ruchu += wr
        dodatkowe.append(dod)
        minuty += dane.get("minuty", 0)
    polaczone = analiza.polacz_dodatkowe(dodatkowe)
    wynik = analiza.podsumuj(flicki, w_ruchu, sens, polaczone, minuty)
    info = {"sesje": len(sesje), "minuty": minuty,
            "z_zabojstwami": sum(1 for d in dodatkowe if d["ma_zabojstwa"])}
    return wynik, info


def porownanie(dpi, obraz, sesje, pomin_sens):
    """Ocena celowania na innych czułościach (to samo DPI i obraz) - lista (sens, ocena, flicki)."""
    czulosci = sorted({d.get("sens") for _, d in sesje
                       if d.get("dpi") == dpi and d.get("obraz") in (None, obraz) and d.get("sens") != pomin_sens})
    wynik = []
    for s in czulosci[-6:]:  # najwyżej 6 czułości - żeby analiza nie trwała za długo
        w, _ = _policz(pliki_dla(s, dpi, obraz, sesje), s)
        if "ocena" in w:
            wynik.append((s, w["ocena"], w["liczba"]))
    return wynik


def analizuj(sens, dpi, obraz=None, ocena_obrazu=None):
    """Zwraca (wynik analizy, info) albo (None, info), gdy brak sesji."""
    wszystkie_sesje = wszystkie()
    sesje = pliki_dla(sens, dpi, obraz, wszystkie_sesje)
    info = {"sesje": len(sesje), "minuty": sum(d.get("minuty", 0) for _, d in sesje)}
    if not sesje:
        return None, info

    wynik, info = _policz(sesje, sens)
    info["porownanie"] = porownanie(dpi, obraz, wszystkie_sesje, sens)
    # Kopia raportu w pliku tekstowym - łatwo wysłać komuś do porównania
    tekst = raport.formatuj(wynik, sens, dpi, info["sesje"], info["minuty"], ocena_obrazu, info)
    try:
        with open(os.path.join(FOLDER, "ostatni_raport.txt"), "w", encoding="utf-8") as f:
            f.write(tekst)
    except OSError:
        pass
    return wynik, info


def usun(sens, dpi, obraz=None):
    for plik, _ in pliki_dla(sens, dpi, obraz):
        try:
            os.remove(plik)
        except OSError:
            pass
