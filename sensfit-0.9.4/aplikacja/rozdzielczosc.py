import glob
import math
import os
import re

M_YAW = 0.022
TYPOWE = ["1920x1080", "2560x1440", "3840x2160", "1600x900", "1280x720",
          "1920x1200", "1680x1050", "1440x1080", "1280x960", "1024x768", "1280x1024"]
DPI_STANDARDOWE = [400, 800, 1600, 3200, 6400]
PROG_PIKSELA = 0.9  # bezpieczny zapas: count ma być mniejszy niż 90% piksela


def parsuj(tekst):
    """'1280x960', '1280×960' albo '1280 x 960' -> (1280, 960); błędny tekst -> None."""
    trafienie = re.fullmatch(r"\s*(\d{3,5})\s*[x×X*]\s*(\d{3,5})\s*", tekst or "")
    if not trafienie:
        return None
    w, h = int(trafienie.group(1)), int(trafienie.group(2))
    return (w, h) if 320 <= w <= 16000 and 240 <= h <= 9000 else None


def proporcje_nazwa(w, h):
    a = w / h
    for nazwa, wartosc in (("4:3", 4 / 3), ("5:4", 5 / 4), ("16:10", 16 / 10), ("16:9", 16 / 9), ("21:9", 64 / 27)):
        if abs(a - wartosc) < 0.02:
            return nazwa
    return f"{a:.2f}:1"


def fov_poziomy(w, h):
    """Poziome pole widzenia CS2 w stopniach dla danych proporcji obrazu."""
    return 2 * math.degrees(math.atan(math.tan(math.radians(45)) * (w / h) / (4 / 3)))


def stopnie_na_piksel(w, h):
    """O ile stopni trzeba obrócić kamerę, żeby przesunąć obraz o 1 piksel na środku ekranu."""
    polowa = math.tan(math.radians(fov_poziomy(w, h) / 2))
    return math.degrees(math.atan(polowa / (w / 2)))


def odczytaj_z_cs2(folder_steam):
    """Rozdzielczość z pliku ustawień wideo CS2 (cs2_video.txt) albo None."""
    wzor = os.path.join(folder_steam, "userdata", "*", "730", "local", "cfg", "cs2_video.txt")
    for plik in sorted(glob.glob(wzor), key=os.path.getmtime, reverse=True):
        try:
            with open(plik, encoding="utf-8", errors="ignore") as f:
                tresc = f.read()
        except OSError:
            continue
        w = re.search(r'"setting\.defaultres"\s+"(\d+)"', tresc)
        h = re.search(r'"setting\.defaultresheight"\s+"(\d+)"', tresc)
        if w and h:
            return int(w.group(1)), int(h.group(1))
    return None


def rozdzielczosc_monitora():
    """Rozdzielczość głównego monitora z Windows albo None."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        return (w, h) if w and h else None
    except (AttributeError, OSError):
        return None


def klucz_sesji(gra, monitor, skalowanie):
    """Tekst odróżniający ustawienia obrazu - sesje z różnych ustawień nie są łączone."""
    if not gra:
        return None
    klucz = f"{gra[0]}x{gra[1]}"
    if monitor and abs(gra[0] / gra[1] - monitor[0] / monitor[1]) > 0.02:
        klucz += "-" + skalowanie
    return klucz


def ocen(sens, dpi, gra, monitor, skalowanie):
    """Liczy wszystko, co rozdzielczość zmienia w celowaniu. Zwraca słownik albo None."""
    if not (sens and dpi and gra):
        return None
    w, h = gra
    monitor = monitor or gra
    st_piksel = stopnie_na_piksel(w, h)
    st_count = sens * M_YAW
    wynik = {
        "gra": gra, "monitor": monitor, "proporcje": proporcje_nazwa(w, h),
        "fov": fov_poziomy(w, h), "st_piksel": st_piksel, "st_count": st_count,
        "stosunek": st_count / st_piksel,
    }
    # Jak szybko obraz przesuwa się w poziomie na monitorze, w porównaniu z natywną rozdzielczością
    inne_proporcje = abs(w / h - monitor[0] / monitor[1]) > 0.02
    wynik["rozciagniete"] = inne_proporcje and skalowanie == "rozciagniete"
    wynik["paski"] = inne_proporcje and skalowanie != "rozciagniete"
    if wynik["rozciagniete"]:
        szerokosc_na_ekranie = monitor[0]
    elif wynik["paski"]:
        szerokosc_na_ekranie = monitor[1] * w / h
    else:
        szerokosc_na_ekranie = monitor[0]
    px_na_tan = szerokosc_na_ekranie / (2 * math.tan(math.radians(wynik["fov"] / 2)))
    px_na_tan_natywnie = monitor[0] / (2 * math.tan(math.radians(fov_poziomy(*monitor) / 2)))
    wynik["predkosc_pozioma"] = px_na_tan / px_na_tan_natywnie

    # Propozycja DPI, przy której celownik nie przeskakuje pikseli (eDPI bez zmian)
    wynik["propozycja"] = None
    if wynik["stosunek"] > 1:
        potrzebne = dpi * wynik["stosunek"] / PROG_PIKSELA
        nowe_dpi = next((d for d in DPI_STANDARDOWE if d >= potrzebne), None)
        if nowe_dpi:
            wynik["propozycja"] = (nowe_dpi, round(sens * dpi / nowe_dpi, 3))
    return wynik


def opis(o):
    """Krótkie podsumowanie do wyświetlenia (lista linii)."""
    gra, mon = o["gra"], o["monitor"]
    linie = [f"{gra[0]}×{gra[1]} ({o['proporcje']})"
             + (f" rozciągnięte na {mon[0]}×{mon[1]}" if o["rozciagniete"] else "")
             + (" z czarnymi paskami" if o["paski"] else "")
             + f" · pole widzenia w poziomie {o['fov']:.0f}°",
             f"1 piksel na środku = {o['st_piksel']:.4f}° · 1 ruch myszy (count) = {o['st_count']:.4f}°"]
    if o["stosunek"] > 1:
        linie.append("celownik przeskakuje piksele")
    else:
        linie.append(f"celownik nie przeskakuje pikseli (count = {o['stosunek']:.0%} piksela)")
    if abs(o["predkosc_pozioma"] - 1) > 0.03:
        linie.append(f"w poziomie obraz przesuwa się o {o['predkosc_pozioma'] - 1:+.0%} "
                     "względem natywnej rozdzielczości monitora")
    return linie


def porady(o, sens):
    """Porady zależne od rozdzielczości: lista (tytuł, co się dzieje, jak to poprawić)."""
    lista = []
    if not o:
        return lista
    if o["stosunek"] > 1:
        jak = ("Zwiększ DPI w myszce i zmniejsz sens w grze w tej samej proporcji – eDPI i cm/360 "
               "zostaną takie same, a celownik będzie się ruszał płynniej.")
        if o["propozycja"]:
            nowe_dpi, nowy_sens = o["propozycja"]
            jak += f" Np. DPI {nowe_dpi} i sens {nowy_sens}."
        lista.append(("Celownik przeskakuje piksele",
                      f"Przy {o['gra'][0]}×{o['gra'][1]} piksel na środku ekranu to {o['st_piksel']:.4f}°, "
                      f"a jeden ruch myszy obraca o {o['st_count']:.4f}°. Nie da się wycelować w każdy piksel.",
                      jak))
    if o["rozciagniete"] and o["predkosc_pozioma"] > 1.03:
        p = o["predkosc_pozioma"]
        lista.append(("Rozciągnięty obraz – w poziomie wydaje się szybciej",
                      f"Obraz {o['proporcje']} rozciągnięty na monitor przesuwa się w poziomie o {p - 1:.0%} "
                      "szybciej niż w natywnej rozdzielczości, choć cm/360 się nie zmienia. W pionie bez zmian.",
                      "Nie musisz zmieniać czułości – zalecenie SensFit liczy się z tego, jak naprawdę celujesz "
                      "na tym ustawieniu. Jeśli chcesz, żeby w poziomie czuło się jak natywnie, ustaw sens "
                      f"ok. {sens / p:.2f} (w pionie będzie wtedy wolniej). Po zmianie nagraj nową sesję."))
    return lista
