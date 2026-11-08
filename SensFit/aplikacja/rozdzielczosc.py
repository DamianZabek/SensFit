"""How resolution and aspect ratio affect aiming in CS2.

In CS2 the camera rotation per mouse count is sens x 0.022 degrees and does NOT depend on the
resolution, so cm/360 stays the same. Resolution does change three other things:

1. Horizontal field of view (FOV). CS2 keeps a fixed 90 degrees for a 4:3 picture, and wider
   aspect ratios show more on the sides: 16:10 gives 100.4, 16:9 gives 106.3 degrees.
       FOV = 2 * atan( tan(45 deg) * aspect / (4/3) )
2. Stretching. A 4:3 picture stretched over a 16:9 monitor is 33% wider. Players look wider,
   but the picture moves 33% faster horizontally for the same mouse movement, which feels like a
   higher sensitivity. Vertically nothing changes.
3. Pixel size in degrees. If one count turns the camera by more than the width of a pixel at the
   centre of the screen, the crosshair skips pixels and not every pixel can be aimed at. A higher
   mouse DPI and a lower in-game sens help (eDPI and cm/360 stay the same).
"""
import glob
import math
import os
import re

import konfiguracja as kfg
from jezyk import t

TYPOWE = ["1920x1080", "2560x1440", "3840x2160", "1600x900", "1280x720",
          "1920x1200", "1680x1050", "1440x1080", "1280x960", "1024x768", "1280x1024"]
DPI_STANDARDOWE = [400, 800, 1600, 3200, 6400]
PROG_PIKSELA = 0.9  # safety margin: a count should be smaller than 90% of a pixel

# List of "Aspect ratio" options and the resolutions that fit each one
PROPORCJE = ["16:9", "16:10", "4:3", "5:4", "3:2", "1:1", "21:9", "32:9"]
ROZDZIELCZOSCI = {
    "16:9": ["1280x720", "1366x768", "1600x900", "1920x1080", "2560x1440", "3840x2160"],
    "16:10": ["1280x800", "1440x900", "1680x1050", "1920x1200", "2560x1600"],
    "4:3": ["1024x768", "1280x960", "1440x1080", "1600x1200", "1920x1440"],
    "5:4": ["1280x1024"],
    "3:2": ["1920x1280", "2256x1504", "3000x2000"],
    "1:1": ["1024x1024", "1080x1080", "1440x1440"],
    "21:9": ["2560x1080", "3440x1440", "3840x1600"],
    "32:9": ["3840x1080", "5120x1440"],
}
WARTOSCI_PROPORCJI = {"16:9": 16 / 9, "16:10": 16 / 10, "4:3": 4 / 3, "5:4": 5 / 4, "3:2": 3 / 2,
                      "1:1": 1.0, "21:9": 64 / 27, "32:9": 32 / 9}


def parsuj(tekst):
    """'1280x960', '1280×960' or '1280 x 960' gives (1280, 960); invalid text gives None."""
    trafienie = re.fullmatch(r"\s*(\d{3,5})\s*[x×X*]\s*(\d{3,5})\s*", tekst or "")
    if not trafienie:
        return None
    w, h = int(trafienie.group(1)), int(trafienie.group(2))
    return (w, h) if 320 <= w <= 16000 and 240 <= h <= 9000 else None


def proporcje_nazwa(w, h):
    a = w / h
    if 2.3 < a < 2.45:  # 21:9 is 2.33 to 2.40 in practice
        return "21:9"
    for nazwa, wartosc in WARTOSCI_PROPORCJI.items():
        if abs(a - wartosc) < 0.02:
            return nazwa
    return f"{a:.2f}:1"


def rozdzielczosci_dla(proporcje):
    """Resolutions from the list for the chosen aspect ratio (an empty list for an unknown one)."""
    return list(ROZDZIELCZOSCI.get(proporcje, []))


def fov_poziomy(w, h):
    """Horizontal CS2 field of view in degrees for the given aspect ratio."""
    return 2 * math.degrees(math.atan(math.tan(math.radians(45)) * (w / h) / (4 / 3)))


def stopnie_na_piksel(w, h):
    """How many degrees the camera has to turn to move the picture by 1 pixel at the centre of the screen."""
    polowa = math.tan(math.radians(fov_poziomy(w, h) / 2))
    return math.degrees(math.atan(polowa / (w / 2)))


def odczytaj_z_cs2(folder_steam):
    """Resolution from the CS2 video settings file (cs2_video.txt), or None."""
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
    """Resolution of the main monitor from Windows, or None."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        return (w, h) if w and h else None
    except (AttributeError, OSError):
        return None


def klucz_sesji(gra, monitor, skalowanie):
    """Text that tells display settings apart. Sessions from different settings are not combined."""
    if not gra:
        return None
    klucz = f"{gra[0]}x{gra[1]}"
    if monitor and abs(gra[0] / gra[1] - monitor[0] / monitor[1]) > 0.02:
        klucz += "-" + skalowanie
    return klucz


def ocen(sens, dpi, gra, monitor, skalowanie):
    """Computes everything that resolution changes in aiming. Returns a dict or None."""
    if not (sens and dpi and gra):
        return None
    w, h = gra
    monitor = monitor or gra
    st_piksel = stopnie_na_piksel(w, h)
    st_count = sens * kfg.m_yaw()
    wynik = {
        "gra": gra, "monitor": monitor, "proporcje": proporcje_nazwa(w, h),
        "fov": fov_poziomy(w, h), "st_piksel": st_piksel, "st_count": st_count,
        "stosunek": st_count / st_piksel,
    }
    # How fast the picture moves horizontally on the monitor compared with the native resolution
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

    # DPI suggestion at which the crosshair does not skip pixels (eDPI unchanged)
    wynik["propozycja"] = None
    if wynik["stosunek"] > 1:
        potrzebne = dpi * wynik["stosunek"] / PROG_PIKSELA
        nowe_dpi = next((d for d in DPI_STANDARDOWE if d >= potrzebne), None)
        if nowe_dpi:
            wynik["propozycja"] = (nowe_dpi, round(sens * dpi / nowe_dpi, 3))
    return wynik


def opis(o):
    """Short summary for display (list of lines)."""
    gra, mon = o["gra"], o["monitor"]
    linie = [f"{gra[0]}×{gra[1]} ({o['proporcje']})"
             + (t(f" rozciągnięte na {mon[0]}×{mon[1]}", f" stretched to {mon[0]}×{mon[1]}") if o["rozciagniete"] else "")
             + (t(" z czarnymi paskami", " with black bars") if o["paski"] else "")
             + t(f" · pole widzenia w poziomie {o['fov']:.0f}°", f" · horizontal field of view {o['fov']:.0f}°"),
             t(f"1 piksel na środku = {o['st_piksel']:.4f}° · 1 ruch myszy (count) = {o['st_count']:.4f}°",
               f"1 pixel in the centre = {o['st_piksel']:.4f}° · 1 mouse count = {o['st_count']:.4f}°")]
    if o["stosunek"] > 1:
        linie.append(t("celownik przeskakuje piksele", "the crosshair skips pixels"))
    else:
        linie.append(t(f"celownik nie przeskakuje pikseli (count = {o['stosunek']:.0%} piksela)",
                       f"the crosshair does not skip pixels (count = {o['stosunek']:.0%} of a pixel)"))
    if abs(o["predkosc_pozioma"] - 1) > 0.03:
        linie.append(t(f"w poziomie obraz przesuwa się o {o['predkosc_pozioma'] - 1:+.0%} "
                       "względem natywnej rozdzielczości monitora",
                       f"horizontally the picture moves {o['predkosc_pozioma'] - 1:+.0%} "
                       "compared with the monitor's native resolution"))
    return linie


def porady(o, sens):
    """Advice that depends on the resolution: a list of (title, what is happening, how to improve it)."""
    lista = []
    if not o:
        return lista
    if o["stosunek"] > 1:
        jak = t("Zwiększ DPI w myszce i zmniejsz sens w grze w tej samej proporcji - eDPI i cm/360 "
                "zostaną takie same, a celownik będzie się ruszał płynniej.",
                "Raise your mouse DPI and lower your in-game sens by the same ratio - eDPI and cm/360 "
                "stay the same, and the crosshair moves more smoothly.")
        if o["propozycja"]:
            nowe_dpi, nowy_sens = o["propozycja"]
            jak += t(f" Np. DPI {nowe_dpi} i sens {nowy_sens}.", f" For example DPI {nowe_dpi} and sens {nowy_sens}.")
        lista.append((t("Celownik przeskakuje piksele", "Your crosshair skips pixels"),
                      t(f"Przy {o['gra'][0]}×{o['gra'][1]} piksel na środku ekranu to {o['st_piksel']:.4f}°, "
                        f"a jeden ruch myszy obraca o {o['st_count']:.4f}°. Nie da się wycelować w każdy piksel.",
                        f"At {o['gra'][0]}×{o['gra'][1]} a pixel in the centre of the screen is {o['st_piksel']:.4f}°, "
                        f"and one mouse count turns {o['st_count']:.4f}°. You cannot aim at every pixel."),
                      jak))
    return lista
