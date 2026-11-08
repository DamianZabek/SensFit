"""Rounded backgrounds (cards, buttons, menu) and menu icons, drawn with Pillow.

Everything is drawn at 4 times the size and scaled down, which keeps the edges smooth. The images
reach Tk as PNG (tk.PhotoImage loads PNG itself, so PIL.ImageTk is not needed). Without Pillow the
program still works, only with square corners.
"""
import base64
import io
import math
import tkinter as tk

try:
    from PIL import Image, ImageDraw
except ImportError:  # running from source without Pillow
    Image = None

SKALA = 4
_pamiec = {}  # the same images are drawn once (Tk only keeps them while a reference exists)


def dostepne():
    return Image is not None


def _zaokraglony(d, ramka, r, **opcje):
    """rounded_rectangle with a radius of at most half a side (older Pillow raises an error otherwise)."""
    x0, y0, x1, y1 = ramka
    d.rounded_rectangle(ramka, max(0, min(r, (x1 - x0) / 2 - 1, (y1 - y0) / 2 - 1)), **opcje)


def _foto(obraz, w, h):
    bufor = io.BytesIO()
    obraz.resize((w, h), Image.LANCZOS).save(bufor, "PNG")
    return tk.PhotoImage(data=base64.b64encode(bufor.getvalue()))


def prostokat(w, h, r, wypelnienie, obrys=None, pasek=None):
    """Rounded rectangle with transparent corners. pasek is the colour of the stripe on the left (active menu item)."""
    klucz = ("p", w, h, r, wypelnienie, obrys, pasek)
    if klucz not in _pamiec:
        s = SKALA
        obraz = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(obraz)
        _zaokraglony(d, (0, 0, w * s - 1, h * s - 1), r * s, fill=wypelnienie,
                            outline=obrys, width=s if obrys else 0)
        if pasek:
            _zaokraglony(d, (0, h * s * 0.22, 3 * s, h * s * 0.78), 1.5 * s, fill=pasek)
        _pamiec[klucz] = _foto(obraz, w, h)
    return _pamiec[klucz]


def rogi(r, wypelnienie, obrys, tlo):
    """The four corners of a card (nw, ne, sw, se), r by r: parent background, rounding with a 1 px outline."""
    klucz = ("r", r, wypelnienie, obrys, tlo)
    if klucz not in _pamiec:
        s, n = SKALA, 2 * r + 2
        obraz = Image.new("RGB", (n * s, n * s), tlo)
        _zaokraglony(ImageDraw.Draw(obraz), (0, 0, n * s - 1, n * s - 1), r * s, fill=wypelnienie,
                     outline=obrys, width=s)
        maly = obraz.resize((n, n), Image.LANCZOS)
        wynik = []
        for x, y in ((0, 0), (n - r, 0), (0, n - r), (n - r, n - r)):
            bufor = io.BytesIO()
            maly.crop((x, y, x + r, y + r)).save(bufor, "PNG")
            wynik.append(tk.PhotoImage(data=base64.b64encode(bufor.getvalue())))
        _pamiec[klucz] = wynik
    return _pamiec[klucz]


def ikona(nazwa, kolor, rozmiar=18):
    """Menu icon: rec, res, maps, log, set, help."""
    klucz = ("i", nazwa, kolor, rozmiar)
    if klucz not in _pamiec:
        _pamiec[klucz] = _foto(rysuj_ikone(nazwa, kolor, rozmiar), rozmiar, rozmiar)
    return _pamiec[klucz]


def rysuj_ikone(nazwa, kolor, rozmiar=18):
    """Pillow image of the icon at scale SKALA (no Tk, used by tests)."""
    s = SKALA
    n = rozmiar * s
    g = 1.8 * s  # line width
    c = n / 2
    obraz = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(obraz)
    if nazwa == "rec":  # circle with a dot
        d.ellipse((g, g, n - g, n - g), outline=kolor, width=int(g))
        d.ellipse((c - 2.8 * s, c - 2.8 * s, c + 2.8 * s, c + 2.8 * s), fill=kolor)
    elif nazwa == "res":  # bars
        for i, wys in enumerate((0.45, 0.8, 0.6)):
            x = n * (0.12 + 0.29 * i)
            _zaokraglony(d, (x, n * (0.92 - 0.84 * wys), x + n * 0.18, n * 0.92), s, fill=kolor)
    elif nazwa == "maps":  # crosshair as in the logo
        d.ellipse((n * 0.2, n * 0.2, n * 0.8, n * 0.8), outline=kolor, width=int(g))
        for a, b in ((0.04, 0.3), (0.7, 0.96)):
            d.line((c, n * a, c, n * b), fill=kolor, width=int(g))
            d.line((n * a, c, n * b, c), fill=kolor, width=int(g))
    elif nazwa == "log":  # list
        for y in (0.25, 0.5, 0.75):
            d.ellipse((n * 0.08, n * y - 1.4 * s, n * 0.08 + 2.8 * s, n * y + 1.4 * s), fill=kolor)
            d.line((n * 0.32, n * y, n * 0.92, n * y), fill=kolor, width=int(g))
    elif nazwa == "set":  # gear
        for k in range(8):
            kat = k * math.pi / 4
            pkt = []
            for dx, dy in ((-0.08, 0.26), (0.08, 0.26), (0.08, 0.47), (-0.08, 0.47)):
                pkt.append((c + n * (dx * math.cos(kat) - dy * math.sin(kat)),
                            c + n * (dx * math.sin(kat) + dy * math.cos(kat))))
            d.polygon(pkt, fill=kolor)
        d.ellipse((c - n * 0.33, c - n * 0.33, c + n * 0.33, c + n * 0.33), fill=kolor)
        d.ellipse((c - n * 0.13, c - n * 0.13, c + n * 0.13, c + n * 0.13), fill=(0, 0, 0, 0))
    else:  # help: an "i" in a circle
        d.ellipse((g / 2, g / 2, n - g / 2, n - g / 2), outline=kolor, width=int(g))
        d.ellipse((c - 1.4 * s, n * 0.24, c + 1.4 * s, n * 0.24 + 2.8 * s), fill=kolor)
        _zaokraglony(d, (c - 1.2 * s, n * 0.42, c + 1.2 * s, n * 0.76), s, fill=kolor)
    return obraz
