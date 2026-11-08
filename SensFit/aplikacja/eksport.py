"""Report export: a PNG image to send to friends or a coach, and a text file.

The report contains neither the Windows user name nor folder paths. The image is drawn with Pillow
(bundled into the .exe at build time). Without Pillow only the text export works.
"""
import os

import dziennik
import raport
import wersja
from jezyk import t
from konfiguracja import cm_na_360, edpi

SZER, WYS = 1200, 630
KOLORY = {"tlo": "#14161a", "panel": "#1b1f26", "linia": "#2a2f38", "tekst": "#e8eaed",
          "szary": "#9aa1ac", "akcent": "#ffb020", "ok": "#4ade80"}


def pillow_dostepny():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def dane_raportu(w, info, sens, dpi, porady):
    """Key numbers for the image. porady is a list of titles (most important first)."""
    return {"sens": sens, "dpi": dpi, "nowa": w.get("nowa_sens", sens), "zmiana": w.get("zmiana", 0.0),
            "ocena": w.get("ocena"), "flicki": w.get("liczba", 0), "sesje": info.get("sesje", 0),
            "porady": list(porady)[:3]}


def tekst(w, info, sens, dpi, ocena_obrazu=None):
    """Text report with a version header (no personal data)."""
    return f"SensFit {wersja.NUMER}" + raport.formatuj(w, sens, dpi, info.get("sesje", 0), info.get("minuty", 0),
                                                      ocena_obrazu, info)


def zapisz_tekst(sciezka, tresc):
    with open(sciezka, "w", encoding="utf-8") as f:
        f.write(tresc)


def _czcionka(rozmiar, gruba=False):
    from PIL import ImageFont
    windows = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    kandydaci = ([os.path.join(windows, "segoeuib.ttf"), os.path.join(windows, "arialbd.ttf"),
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if gruba else
                 [os.path.join(windows, "segoeui.ttf"), os.path.join(windows, "arial.ttf"),
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for plik in kandydaci:
        try:
            return ImageFont.truetype(plik, rozmiar)
        except OSError:
            continue
    try:
        return ImageFont.load_default(rozmiar)
    except TypeError:  # older Pillow
        return ImageFont.load_default()


def _skroc(rysunek, tekst_, czcionka, maks):
    if rysunek.textlength(tekst_, font=czcionka) <= maks:
        return tekst_
    while tekst_ and rysunek.textlength(tekst_ + "…", font=czcionka) > maks:
        tekst_ = tekst_[:-1]
    return tekst_.rstrip() + "…"


def obrazek(d, logo=None):
    """PIL image with the result card (1200x630, previews well on Discord and Messenger)."""
    from PIL import Image, ImageDraw
    k = KOLORY
    img = Image.new("RGB", (SZER, WYS), k["tlo"])
    r = ImageDraw.Draw(img)
    r.rounded_rectangle((32, 32, SZER - 32, WYS - 32), radius=24, fill=k["panel"], outline=k["linia"], width=2)
    r.rectangle((32, 70, 38, 150), fill=k["akcent"])

    x = 80
    f_male = _czcionka(22, True)
    zmiana = d["nowa"] != d["sens"]
    r.text((x, 76), (t("ZALECENIE", "RECOMMENDATION") if zmiana else t("CZUŁOŚĆ", "SENSITIVITY")),
           font=f_male, fill=k["akcent"])
    if zmiana:
        f_stara, f_nowa = _czcionka(64, True), _czcionka(92, True)
        stara = f"{d['sens']:g}"
        r.text((x, 128), stara, font=f_stara, fill=k["szary"])
        x2 = x + r.textlength(stara, font=f_stara) + 24
        r.text((x2, 128), "→", font=f_stara, fill=k["akcent"])
        x3 = x2 + r.textlength("→", font=f_stara) + 24
        nowa = f"{d['nowa']:g}"
        r.text((x3, 104), nowa, font=f_nowa, fill="#ffffff")
        x4 = x3 + r.textlength(nowa, font=f_nowa) + 20
        r.text((x4, 150), f"{d['zmiana']:+.0%}".replace("-", "−"), font=_czcionka(36, True), fill=k["akcent"])
    else:
        r.text((x, 120), t("Wygląda dobrze", "Looks good"), font=_czcionka(68, True), fill=k["ok"])
        r.text((x, 206), f"sens {d['sens']:g}", font=_czcionka(30), fill=k["szary"])

    ustawienia = (f"sens {d['sens']:g} · {d['dpi']} DPI · eDPI {edpi(d['sens'], d['dpi']):.0f} · "
                  f"{cm_na_360(d['sens'], d['dpi']):.1f} cm/360°")
    r.text((x, 262), ustawienia, font=_czcionka(26), fill=k["szary"])

    if d["porady"]:
        r.text((x, 322), t("CO POPRAWIĆ", "WHAT TO IMPROVE"), font=f_male, fill=k["szary"])
        f_porada = _czcionka(30)
        for i, tytul in enumerate(d["porady"]):
            y = 364 + i * 48
            r.ellipse((x, y + 12, x + 12, y + 24), fill=k["akcent"])
            r.text((x + 28, y), _skroc(r, tytul, f_porada, 760), font=f_porada, fill=k["tekst"])

    # Ring with the aim score
    cx, cy, promien, grubosc = 1000, 250, 110, 22
    ramka = (cx - promien, cy - promien, cx + promien, cy + promien)
    r.ellipse(ramka, outline=k["linia"], width=grubosc)
    if d["ocena"] is not None:
        kat = 3.6 * max(0, min(100, d["ocena"]))
        if kat > 0:
            r.arc(ramka, start=-90, end=-90 + kat, fill=k["akcent"], width=grubosc)
        f_ocena = _czcionka(76, True)
        napis = str(d["ocena"])
        r.text((cx - r.textlength(napis, font=f_ocena) / 2, cy - 54), napis, font=f_ocena, fill="#ffffff")
        f_z = _czcionka(22)
        z100 = t("z 100", "out of 100")
        r.text((cx - r.textlength(z100, font=f_z) / 2, cy + 34), z100, font=f_z, fill=k["szary"])
    f_pod = _czcionka(24, True)
    podpis = t("Ocena celowania", "Aim score")
    r.text((cx - r.textlength(podpis, font=f_pod) / 2, cy + promien + 22), podpis, font=f_pod, fill=k["szary"])

    # Footer
    r.line((80, WYS - 112, SZER - 80, WYS - 112), fill=k["linia"], width=2)
    stopka = dziennik.liczba_sesji_tekst(d["sesje"]) + " · " + t(f"{d['flicki']} flicków", f"{d['flicki']} flicks")
    f_stopka = _czcionka(24)
    r.text((80, WYS - 92), stopka, font=f_stopka, fill=k["szary"])
    marka = f"SensFit {wersja.NUMER}"
    f_marka = _czcionka(26, True)
    szer_marki = r.textlength(marka, font=f_marka)
    r.text((SZER - 80 - szer_marki, WYS - 94), marka, font=f_marka, fill=k["tekst"])
    if logo:
        try:
            ikona = Image.open(logo).convert("RGBA").resize((40, 40))
            img.paste(ikona, (int(SZER - 80 - szer_marki - 52), WYS - 98), ikona)
        except OSError:
            pass
    return img


def zapisz_obrazek(sciezka, d, logo=None):
    obrazek(d, logo).save(sciezka, "PNG", optimize=True)
