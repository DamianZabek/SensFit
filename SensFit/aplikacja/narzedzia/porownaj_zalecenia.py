"""Compares the recommendations of two SensFit versions (for example 0.9.5.1 and 0.9.6) on real sessions.
For the author only, it is not part of the .exe.

Usage (Windows, in the aplikacja folder of the new version):
    py -3.12 narzedzia\\porownaj_zalecenia.py <sessions folder> [<aplikacja folder of the old version>]
The sessions folder holds the sesja_*.json files from a tester (from %APPDATA%\\SensFit\\sesje).
For every setting (eDPI + resolution) it prints the number of sessions and flicks, the score,
the recommendation of the old and the new version and the reason. Nothing is written to the tester's folder.
"""
import os
import sys
import tempfile

TU = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULY = ("analiza", "raport", "rozdzielczosc", "sesje", "konfiguracja", "jezyk", "wersja", "dziennik")


def wczytaj_wersje(folder, nazwa):
    """Loads the analiza and sesje modules from the given folder under separate names."""
    sys.path.insert(0, folder)
    for m in MODULY:
        sys.modules.pop(m, None)
    __import__("sesje")
    try:
        __import__("dziennik")  # sesje imports dziennik only during the analysis
    except ImportError:
        pass
    moduly = {m: sys.modules[m] for m in ("analiza", "sesje", "raport")}
    sys.path.remove(folder)  # modules stay in sys.modules until the next load, so the new version has to be loaded last
    return moduly


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    folder_sesji = os.path.abspath(sys.argv[1])
    stara = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else None
    os.environ["APPDATA"] = tempfile.mkdtemp()  # the text report goes to a temporary folder
    wersje = [("stara", wczytaj_wersje(stara, "stara"))] if stara else []
    wersje.append(("nowa", wczytaj_wersje(TU, "nowa")))
    for nazwa, m in wersje:
        m["sesje"].FOLDER_SESJI = folder_sesji
    sesje_nowe = wersje[-1][1]["sesje"]
    lista = sesje_nowe.wszystkie()
    grupy = {}
    for _, d in lista:
        if d.get("sens") and d.get("dpi"):
            grupy.setdefault((round(d["sens"] * d["dpi"]), d.get("obraz")), d)
    print(f"Sesji: {len(lista)}, ustawień: {len(grupy)}\n")
    for (e, obraz), d in sorted(grupy.items(), key=lambda x: x[0][0]):
        print(f"eDPI {e} (sens {d['sens']}, {d['dpi']} DPI, {obraz or 'obraz ?'})")
        for nazwa, m in wersje:
            w, info = m["sesje"].analizuj(d["sens"], d["dpi"], obraz)
            if not w or "ocena" not in w:
                print(f"  {nazwa}: za mało danych ({w and w.get('liczba')} flicków)")
                continue
            powod = w.get("zrodlo") or w.get("bez_zmiany") or "bez zmiany"
            print(f"  {nazwa}: {info['sesje']} sesji, {w['liczba']} flicków, ocena {w['ocena']}, "
                  f"zalecenie {d['sens']} -> {w['nowa_sens']} ({w['zmiana']:+.0%}), powód: {powod}, "
                  f"sygnały: {[s['klucz'] for s in w.get('sygnaly', [])]}")
        print()


if __name__ == "__main__":
    main()
