"""Mouse movement analysis: finds flicks that end with a shot and checks how accurate they are.

Idea (based on research on hand movements):
A fast movement toward a target consists of a MAIN MOVEMENT (large, fast) and small CORRECTIONS.
- A correction going BACK means the target was overshot, so the sensitivity is probably too high.
- A correction going FURTHER means the target was not reached, so the sensitivity is probably too low.

For every flick r = (main movement) / (distance to the shot position).
  r = 1.00: the main movement landed exactly
  r > 1.00: overshoot, r < 1.00: undershoot
People naturally undershoot a little and add a small correction (safer than overshooting),
so 0.95 is treated as the ideal value instead of 1.00.

Flick weights: a flick that ends with a kill (from GSI) counts 3 times, because the crosshair
was on the target. A flick with tracking of a moving target counts 0.5 times, because the target
was moving and r is less certain. Movement made during a spray (button still held) is recoil
control and is skipped.

Direction signals: lifting the mouse during a turn (sensitivity too low), crosshair tremor and
overshooting small flicks (too high), large flicks that fall short (too low). Every signal has a
minimum amount of data and counts as strong at twice its threshold. Two signals point up and two
point down.

Aim score 0 to 100: accuracy, spread, corrections and speed. It is meant for comparing
sensitivities with each other.

A recommendation is only given when there is enough data (MIN_FLICKOW_ZALECENIA flicks). A step
based on signals alone is only taken when no signal points the other way. The score curve
(zastosuj_krzywa) recommends another tested sensitivity when its score is clearly higher, and
never moves toward a sensitivity that scored worse than the current one.
"""
import bisect
import math
import random
import statistics
from dataclasses import dataclass

from konfiguracja import KUBELEK_S, M_YAW  # single place for the constants
PRZERWA_S = 0.040        # silence longer than 40 ms ends a movement
MIN_FLICK_DEG = 3.0      # smaller movements are micro corrections, not flicks
MIN_SZCZYT_DEG_S = 100.0 # a flick has to be reasonably fast
OKNO_STRZALU_S = 0.40    # a shot within 400 ms after the main movement means the player was aiming at something
OKNO_TRAFIENIA_S = 0.90  # a kill within 0.9 s after the shot counts as a hit (GSI is delayed by about 0.1 to 0.2 s)
CEL_R = 0.95             # natural slight undershoot
KONIEC_SPADEK = 0.35     # a correction starts only after the speed drops below 35% of the peak
PROG_KOREKTY = 0.10      # a correction counts from 10% of the peak speed
MAX_ZMIANA = 0.15        # the sensitivity never changes by more than 15% at once
KROK_Z_SYGNALOW = 0.05   # when r is not conclusive but the signals are clear, a small 5% step
WAGA_TRAFIENIA = 3.0
WAGA_SLEDZENIA = 0.5

# Signal thresholds (heuristics, to be tuned on tester data). The same rule applies to all:
# a signal appears at the threshold and is "strong" (strength 2) from SILNY_RAZY times the threshold.
PODNIESIENIA_NA_10_MIN = 4      # mouse lifts during a turn per 10 minutes (informational only)
PODNIESIENIE_OBROT_DEG = 90     # only a large turn counts (both parts together)
PODNIESIENIE_DROGA_CM = 15      # and a long mouse path in the first part
DRZENIE_DEG = 0.20              # crosshair tremor (about 40% of a head width from a distance) points to a sensitivity that is too high
ODCHYLENIE_GRUPY = 0.10         # median r of small or large flicks further from CEL_R than this...
ROZNICA_GRUP = 0.04             # ...and differing from the medium flicks by at least this much
SILNY_RAZY = 2.0
# Minimum amount of data for a signal to count at all
MIN_ZDARZEN_DRZENIA = 50
MIN_MINUT_PODNIESIEN = 10
MIN_PODNIESIEN = 3
MIN_FLICKOW_GRUPY = 30
# Recommendation
MIN_FLICKOW_ZALECENIA = 100     # fewer flicks means no recommendation (not enough data)
MIN_FLICKOW_KRZYWEJ = 60        # a point of the score curve counts from this many flicks
MARGINES_OCENY = 3              # another sensitivity needs a score higher by at least this much...
# ...and the uncertainty intervals (score +/- ocena_pm) must not overlap
MIN_DNI_KRZYWEJ = 2             # a curve point only decides with sessions from at least 2 different days


@dataclass
class Flick:
    rozmiar_deg: float      # distance from the start to the shot position
    r: float                # main movement divided by distance (see the module docstring)
    blad_boczny: float      # how far the main movement went sideways (fraction of the distance)
    korekta_pion_deg: float # vertical correction in degrees
    czas_korekty_s: float   # time from the end of the main movement to the shot
    liczba_korekt: int
    czas_do_strzalu_s: float = 0.0  # time from the start of the movement to the shot
    trafienie: bool = False         # a kill followed the shot (GSI)
    sledzenie: bool = False         # the crosshair smoothly followed a moving target before the shot

    @property
    def waga(self):
        if self.trafienie:
            return WAGA_TRAFIENIA
        return WAGA_SLEDZENIA if self.sledzenie else 1.0


# Helpers
def podziel_na_ruchy(kubelki):
    """Splits the list of buckets into separate movements divided by a moment of stillness."""
    ruchy, biezacy = [], []
    for k in kubelki:
        if biezacy and k[0] - biezacy[-1][0] > PRZERWA_S:
            ruchy.append(biezacy)
            biezacy = []
        biezacy.append(k)
    if biezacy:
        ruchy.append(biezacy)
    return ruchy


def predkosci(dx, dy):
    """Speed in degrees per second in every bucket, smoothed with the average of 3 neighbours."""
    v = [math.hypot(x, y) / KUBELEK_S for x, y in zip(dx, dy)]
    return [sum(v[max(0, i - 1):i + 2]) / len(v[max(0, i - 1):i + 2]) for i in range(len(v))]


def na_gesto(ruch, deg_na_count):
    """deg_na_count is a number (both axes) or a pair (horizontal, vertical) with m_yaw and m_pitch separately."""
    deg_x, deg_y = deg_na_count if isinstance(deg_na_count, tuple) else (deg_na_count, deg_na_count)
    """Ruch jako równe kroki co 4 ms (zera tam, gdzie mysz stała), w stopniach."""
    t0 = ruch[0][0]
    n = round((ruch[-1][0] - t0) / KUBELEK_S) + 1
    dx, dy = [0.0] * n, [0.0] * n
    for t, x, y in ruch:
        i = round((t - t0) / KUBELEK_S)
        dx[i] += x * deg_x
        dy[i] += y * deg_y
    return dx, dy


def wygladz(v, pol):
    """Moving average of 2*pol+1 buckets (as many as are available at the edges)."""
    return [sum(v[max(0, i - pol):i + pol + 1]) / len(v[max(0, i - pol):i + pol + 1]) for i in range(len(v))]


def koniec_ruchu(vg, szczyt, vmax):
    """Index of the last bucket of the main movement: the speed is almost zero, or it drops clearly
    (below KONIEC_SPADEK times the peak) and then rises for 2 buckets in a row (start of a correction).
    """
    n = len(vg)
    for i in range(szczyt + 1, n):
        if vg[i] < 0.08 * vmax:
            return i
        if vg[i] < KONIEC_SPADEK * vmax and i + 2 < n and vg[i + 2] > vg[i + 1] > vg[i]:
            return i
    return n - 1


def kwantyl_wazony(wartosci, wagi, q):
    """Weighted quantile (q=0.5 is the weighted median)."""
    pary = sorted(zip(wartosci, wagi))
    suma = sum(w for _, w in pary)
    prog, narastajaco = q * suma, 0.0
    for wartosc, waga in pary:
        narastajaco += waga
        if narastajaco >= prog:
            return wartosc
    return pary[-1][0]


class Serie:
    """Moments when the left button was held (from press to release)."""

    def __init__(self, klikniecia, puszczenia):
        self.wcisniecia = sorted(klikniecia)
        puszczenia = sorted(puszczenia or [])
        self.dostepne = bool(puszczenia)  # older sessions have no releases, so nothing is filtered
        self.konce = []
        for t in self.wcisniecia:
            j = bisect.bisect_right(puszczenia, t)
            self.konce.append(puszczenia[j] if j < len(puszczenia) else t + 0.15)

    def w_trakcie_serii(self, t):
        """Whether a spray was in progress at time t (button held for longer than a fraction of a second)."""
        if not self.dostepne:
            return False
        i = bisect.bisect_right(self.wcisniecia, t) - 1
        return i >= 0 and self.wcisniecia[i] + 0.03 < t < self.konce[i]


# One movement to flick
def analizuj_ruch(ruch, klikniecia, deg_na_count, serie=None, zabojstwa=None):
    """Returns (Flick or None, shot_during_movement, skipped_because_of_spray)."""
    t0 = ruch[0][0]
    if serie and serie.w_trakcie_serii(t0):
        return None, False, True          # recoil control during a spray, not a flick
    dx, dy = na_gesto(ruch, deg_na_count)
    n = len(dx)

    v = predkosci(dx, dy)
    szczyt = max(range(n), key=lambda i: v[i])
    vmax = v[szczyt]
    if vmax < MIN_SZCZYT_DEG_S:
        return None, False, False

    # The end of the main movement is looked for in a more strongly smoothed speed (5 buckets = 20 ms):
    # hand tremor and read noise caused brief dips that cut the movement short and faked an undershoot.
    vg = wygladz(v, 2)
    szczyt_g = max(range(n), key=lambda i: vg[i])
    vmax_g = vg[szczyt_g]
    koniec = koniec_ruchu(vg, szczyt_g, vmax_g)
    t_koniec = t0 + (koniec + 1) * KUBELEK_S

    # First shot near the end of the main movement
    j = bisect.bisect_left(klikniecia, t0)
    if j >= len(klikniecia) or klikniecia[j] > t_koniec + OKNO_STRZALU_S:
        return None, False, False           # no shot, so this was not a flick at a target
    t_strzalu = klikniecia[j]
    if t_strzalu < t_koniec - 0.02:
        return None, True, False            # shot before the crosshair stopped

    px, py = sum(dx[:koniec + 1]), sum(dy[:koniec + 1])        # main movement
    do_strzalu = min(n, int((t_strzalu - t0) / KUBELEK_S))
    kx, ky = sum(dx[koniec + 1:do_strzalu]), sum(dy[koniec + 1:do_strzalu])  # corrections
    cx, cy = px + kx, py + ky                                  # target = shot position
    odl = math.hypot(cx, cy)
    if odl < MIN_FLICK_DEG or math.hypot(px, py) < MIN_FLICK_DEG:
        return None, False, False

    r = (px * cx + py * cy) / odl ** 2          # projection of the main movement on the direction to the target
    if not 0.4 <= r <= 1.8:
        return None, False, False               # most likely not a single flick at a single target
    boczny = abs(px * cy - py * cx) / odl ** 2

    korekty = sum(1 for i in range(koniec + 1, min(do_strzalu, n - 1))
                  if vg[i] > vg[i - 1] and vg[i] >= vg[i + 1] and vg[i] > max(30, PROG_KOREKTY * vmax_g))

    # Tracking: smooth movement in one direction for at least 150 ms after the main movement, the target was moving
    faza = range(koniec + 1, do_strzalu)
    ruchome = [i for i in faza if v[i] > 15]
    sledzenie = False
    if len(ruchome) * KUBELEK_S >= 0.15:
        sx, sy = sum(dx[i] for i in ruchome), sum(dy[i] for i in ruchome)
        droga = sum(math.hypot(dx[i], dy[i]) for i in ruchome)
        sledzenie = droga > 0 and math.hypot(sx, sy) / droga >= 0.8

    trafienie = False
    if zabojstwa:
        k = bisect.bisect_left(zabojstwa, t_strzalu)
        trafienie = k < len(zabojstwa) and zabojstwa[k] <= t_strzalu + OKNO_TRAFIENIA_S

    return Flick(odl, r, boczny, abs(ky), max(0.0, t_strzalu - t_koniec), korekty,
                 t_strzalu - t0, trafienie, sledzenie), False, False


# Signals from the whole session
def opis_ruchu(ruch, deg_na_count):
    """Short description of a movement, needed to detect lifts and tremor."""
    dx, dy = na_gesto(ruch, deg_na_count)
    v = predkosci(dx, dy)
    vmax = max(v)
    koncowka = v[-3:]
    return {
        "start": ruch[0][0], "koniec": ruch[-1][0] + KUBELEK_S,
        "sx": sum(dx), "sy": sum(dy), "droga": sum(math.hypot(a, b) for a, b in zip(dx, dy)),
        "vmax": vmax, "kubelki": len(dx),
        # Cut-off end: the movement ends at high speed without braking, typical for lifting the mouse
        "urwany": vmax > 0 and sum(koncowka) / len(koncowka) > 0.3 * vmax,
    }


def wykryj_podniesienia(opisy, klikniecia=(), deg_na_cm=None):
    """Mouse lift during a turn: a fast movement is cut off without braking and, after a short
    pause (up to 0.35 s), continues in the same direction.

    Strict on purpose, because two flicks in a row used to be counted: together at least
    PODNIESIENIE_OBROT_DEG, the first part at least PODNIESIENIE_DROGA_CM of mouse travel
    (when the DPI is known) and no shot between the start of the first part and the start of the second.
    """
    klikniecia = sorted(klikniecia)
    licznik = 0
    for a, b in zip(opisy, opisy[1:]):
        przerwa = b["start"] - a["koniec"]
        if not (0.03 <= przerwa <= 0.35):
            continue
        if not (a["urwany"] and a["vmax"] >= 150 and a["droga"] >= 15 and b["droga"] >= 5):
            continue
        if a["droga"] + b["droga"] < PODNIESIENIE_OBROT_DEG:
            continue
        if deg_na_cm and a["droga"] / deg_na_cm < PODNIESIENIE_DROGA_CM:
            continue
        i = bisect.bisect_left(klikniecia, a["start"])
        if i < len(klikniecia) and klikniecia[i] <= b["start"]:
            continue  # a shot between the parts means two flicks, not a lift
        dl_a, dl_b = math.hypot(a["sx"], a["sy"]), math.hypot(b["sx"], b["sy"])
        if dl_a and dl_b and (a["sx"] * b["sx"] + a["sy"] * b["sy"]) / (dl_a * dl_b) >= 0.8:
            licznik += 1
    return licznik


def wykryj_drzenie(opisy):
    """Tremor: very short (up to 16 ms) and small (under 1 degree) crosshair movements, isolated from
    other movements. This is how a shaking hand looks while holding an angle. Returns the amplitudes in degrees.
    """
    amplitudy = []
    for i, o in enumerate(opisy):
        if o["kubelki"] > 4 or o["droga"] >= 1.0:
            continue
        przed = o["start"] - opisy[i - 1]["koniec"] if i > 0 else 1.0
        po = opisy[i + 1]["start"] - o["koniec"] if i + 1 < len(opisy) else 1.0
        if przed >= 0.10 and po >= 0.10:
            amplitudy.append(math.hypot(o["sx"], o["sy"]))
    return amplitudy


def znajdz_flicki(kubelki, klikniecia, sens, puszczenia=None, zabojstwa=None, dpi=None, m_yaw=M_YAW,
                  m_pitch=None):
    """Processes a whole session. Returns (flicks, number of shots during a movement, extra data)."""
    deg_na_count = (sens * (m_yaw or M_YAW), sens * (m_pitch or m_yaw or M_YAW))
    klikniecia = sorted(klikniecia)
    ma_zabojstwa = zabojstwa is not None  # older sessions have no kill data
    zabojstwa = sorted(zabojstwa or [])
    serie = Serie(klikniecia, puszczenia)
    flicki, w_ruchu, w_serii = [], 0, 0
    ruchy = podziel_na_ruchy(kubelki)
    for ruch in ruchy:
        flick, strzal_w_ruchu, seria = analizuj_ruch(ruch, klikniecia, deg_na_count, serie, zabojstwa)
        if flick:
            flicki.append(flick)
        w_ruchu += strzal_w_ruchu
        w_serii += seria
    opisy = [opis_ruchu(r, deg_na_count) for r in ruchy]
    deg_na_cm = deg_na_count[0] * dpi / 2.54 if dpi else None
    dodatkowe = {"podniesienia": wykryj_podniesienia(opisy, klikniecia, deg_na_cm), "drzenie": wykryj_drzenie(opisy),
                 "w_serii": w_serii, "zabojstwa": len(zabojstwa), "ma_zabojstwa": ma_zabojstwa}
    return flicki, w_ruchu, dodatkowe


def polacz_dodatkowe(lista):
    """Sums the extra data of several sessions."""
    wynik = {"podniesienia": 0, "drzenie": [], "w_serii": 0, "zabojstwa": 0}
    for d in lista:
        wynik["podniesienia"] += d["podniesienia"]
        wynik["drzenie"] += d["drzenie"]
        wynik["w_serii"] += d["w_serii"]
        wynik["zabojstwa"] += d["zabojstwa"]
    return wynik


# Score and recommendation
def ocena_celowania(r_med, rozrzut, korekty, tempo):
    """Score from 0 to 100 for comparing sensitivities (higher is better). Components:
    accuracy (how close to 95%), flick spread, number of corrections and speed (bits per second, as in Fitts's law).
    """
    s_cel = max(0.0, 1 - abs(r_med - CEL_R) / 0.25)
    s_rozrzut = max(0.0, 1 - rozrzut / 0.5)
    s_korekty = max(0.0, 1 - korekty / 3)
    s_tempo = min(1.0, tempo / 16)  # was 10 bit/s, but all testers scored 10 to 14, so it did not tell anyone apart
    return round(100 * (0.35 * s_cel + 0.25 * s_rozrzut + 0.20 * s_korekty + 0.20 * s_tempo))


def minut_do_celu(liczba, minuty, cel=MIN_FLICKOW_ZALECENIA):
    """Minutes of play still needed (at this flick rate) to reach `cel` flicks, or None without a rate."""
    if liczba >= cel or not liczba or not minuty:
        return None if liczba < cel else 0
    return max(1, math.ceil((cel - liczba) * minuty / liczba))


def ocena_flickow(flicki):
    """Aim score from a list of flicks (same components as in podsumuj)."""
    r = [f.r for f in flicki]
    wagi = [f.waga for f in flicki]
    r_med = kwantyl_wazony(r, wagi, 0.5)
    rozrzut = kwantyl_wazony(r, wagi, 0.75) - kwantyl_wazony(r, wagi, 0.25)
    korekty = statistics.mean(f.liczba_korekt for f in flicki)
    return ocena_celowania(r_med, rozrzut, korekty, statistics.median(tempo_flicka(f) for f in flicki))


def niepewnosc_oceny(flicki, losowan=200, seed=0):
    """Half of the 90% score interval (bootstrap over flicks): the score is ocena +/- this number."""
    los = random.Random(seed)  # fixed seed, so the same data gives the same report
    n = len(flicki)
    oceny = sorted(ocena_flickow([flicki[los.randrange(n)] for _ in range(n)]) for _ in range(losowan))
    return round((oceny[int(0.95 * (losowan - 1))] - oceny[int(0.05 * (losowan - 1))]) / 2)


def tempo_flicka(f):
    """Speed as in Fitts's law: difficulty of the movement (log2 of distance over target width) per second.
    The target width is assumed to be 1 degree (roughly a head at medium range).
    """
    return math.log2(f.rozmiar_deg / 1.0 + 1) / max(f.czas_do_strzalu_s, 0.05)


def _sygnal(klucz, kierunek, wartosc, odchylenie, prog):
    """A signal of strength 1, or 2 when the deviation is at least SILNY_RAZY times the threshold."""
    return {"klucz": klucz, "kierunek": kierunek, "sila": 2 if odchylenie >= SILNY_RAZY * prog else 1,
            "wartosc": wartosc}


def sygnaly_kierunku(wynik, dodatkowe, minuty):
    """Signals that the sensitivity is too low (+1) or too high (-1). Strength 1 is weak, 2 is strong.

    Two signals point up and two point down, each with the same threshold rule and minimum amount of data.
    """
    sygnaly = []
    podn = dodatkowe.get("podniesienia", 0)
    if minuty >= MIN_MINUT_PODNIESIEN and podn >= MIN_PODNIESIEN:
        na_10 = podn / minuty * 10
        if na_10 >= PODNIESIENIA_NA_10_MIN:
            # informational only (direction 0), it produced false 'increase' advice on tester data
            sygnaly.append(_sygnal("podniesienia", 0, na_10, na_10, PODNIESIENIA_NA_10_MIN))
    drzenie = dodatkowe.get("drzenie", [])
    if len(drzenie) >= MIN_ZDARZEN_DRZENIA:
        d = statistics.median(drzenie)
        if d >= DRZENIE_DEG:
            sygnaly.append(_sygnal("drzenie", -1, d, d, DRZENIE_DEG))
    grupy = wynik.get("grupy", {})
    male, srednie, duze = grupy.get("male"), grupy.get("srednie"), grupy.get("duze")
    if srednie and srednie[1] >= MIN_FLICKOW_GRUPY:
        if male and male[1] >= MIN_FLICKOW_GRUPY:
            odch = male[0] - CEL_R
            if odch >= ODCHYLENIE_GRUPY and male[0] - srednie[0] >= ROZNICA_GRUP:
                sygnaly.append(_sygnal("male_za_daleko", -1, male[0], odch, ODCHYLENIE_GRUPY))
        if duze and duze[1] >= MIN_FLICKOW_GRUPY:
            odch = CEL_R - duze[0]
            if odch >= ODCHYLENIE_GRUPY and srednie[0] - duze[0] >= ROZNICA_GRUP:
                sygnaly.append(_sygnal("duze_za_krotko", +1, duze[0], odch, ODCHYLENIE_GRUPY))
    return sygnaly


def podsumuj(flicki, w_ruchu, sens, dodatkowe=None, minuty=0.0):
    """Computes the statistics, the aim score and the recommended sensitivity."""
    dodatkowe = dodatkowe or {}
    wynik = {"liczba": len(flicki), "w_ruchu": w_ruchu, "w_serii": dodatkowe.get("w_serii", 0),
             "zabojstwa": dodatkowe.get("zabojstwa", 0), "podniesienia": dodatkowe.get("podniesienia", 0), "minuty": minuty}
    if len(flicki) < 10:
        return wynik

    r = [f.r for f in flicki]
    wagi = [f.waga for f in flicki]
    r_med = kwantyl_wazony(r, wagi, 0.5)
    rozrzut = kwantyl_wazony(r, wagi, 0.75) - kwantyl_wazony(r, wagi, 0.25)
    niepewnosc = 1.58 * rozrzut / math.sqrt(len(flicki)) if len(flicki) >= 4 else float("inf")
    trafione = [f for f in flicki if f.trafienie]
    czasy = [f.czas_do_strzalu_s for f in flicki]
    tempo = statistics.median(tempo_flicka(f) for f in flicki)
    wynik.update(
        r_mediana=r_med,
        niepewnosc=niepewnosc,
        rozrzut=rozrzut,
        przestrzal=sum(x > 1.02 for x in r) / len(r),
        w_punkt=sum(0.90 <= x <= 1.02 for x in r) / len(r),
        niedociagniecie=sum(x < 0.90 for x in r) / len(r),
        rozmiar=statistics.median(f.rozmiar_deg for f in flicki),
        korekty=statistics.mean(f.liczba_korekt for f in flicki),
        czas_korekty=statistics.median(f.czas_korekty_s for f in flicki),
        czas_do_strzalu=statistics.median(czasy),
        tempo=tempo,
        boczny=statistics.median(f.blad_boczny for f in flicki),
        pion=statistics.median(f.korekta_pion_deg for f in flicki),
        procent_w_ruchu=w_ruchu / (w_ruchu + len(flicki)),
        trafione=len(trafione),
        sledzenie=sum(f.sledzenie for f in flicki),
        r_trafione=statistics.median(f.r for f in trafione) if len(trafione) >= 15 else None,
    )
    drzenie = dodatkowe.get("drzenie", [])
    wynik["drzenie"] = statistics.median(drzenie) if len(drzenie) >= MIN_ZDARZEN_DRZENIA else None
    wynik["podniesienia_na_10"] = wynik["podniesienia"] / minuty * 10 if minuty > 0 else None

    # Accuracy by flick size
    grupy = {"male": (3, 15), "srednie": (15, 45), "duze": (45, 999)}
    wynik["grupy"] = {}
    for nazwa, (od, do) in grupy.items():
        fg = [f for f in flicki if od <= f.rozmiar_deg < do]
        if len(fg) >= 15:
            # every group also has its own score and direction, so small and large flicks are judged separately
            wynik["grupy"][nazwa] = (kwantyl_wazony([f.r for f in fg], [f.waga for f in fg], 0.5), len(fg),
                                     ocena_flickow(fg), kierunek_sesji(fg))

    wynik["ocena"] = ocena_celowania(r_med, rozrzut, wynik["korekty"], tempo)
    wynik["ocena_pm"] = niepewnosc_oceny(flicki)
    wynik["sygnaly"] = sygnaly_kierunku(wynik, dodatkowe, minuty)
    netto = sum(s["kierunek"] * s["sila"] for s in wynik["sygnaly"])

    # Recommendation: r_med = 1.10 means the hand movement gives 10% too much rotation, so lower the sensitivity
    mnoznik = min(1 + MAX_ZMIANA, max(1 - MAX_ZMIANA, CEL_R / r_med))
    pewne = abs(r_med - CEL_R) > niepewnosc and abs(mnoznik - 1) >= 0.03
    zrodlo = None
    wynik["bez_zmiany"] = None
    kierunki = {s["kierunek"] for s in wynik["sygnaly"] if s["kierunek"]}
    if len(flicki) < MIN_FLICKOW_ZALECENIA:      # not enough data for any recommendation
        mnoznik = 1.0
        wynik["bez_zmiany"] = "za_malo"
    elif pewne:
        zrodlo = "flicki"
        kierunek_r = 1 if mnoznik > 1 else -1
        if netto * kierunek_r <= -2:           # clear signals in the opposite direction, so be more careful
            mnoznik = 1 + (mnoznik - 1) / 2
            zrodlo = "flicki_oslabione"
        elif netto * kierunek_r == -1:         # one weak opposite signal: the change stays, with a note
            zrodlo = "flicki_sprzeczne"
        elif netto * kierunek_r >= 1:
            zrodlo = "flicki_i_sygnaly"
    elif abs(netto) >= 2 and len(kierunki) == 1:  # flicks without a clear direction, signals that agree and are strong
        mnoznik = 1 + KROK_Z_SYGNALOW * (1 if netto > 0 else -1)
        zrodlo = "sygnaly"
    else:
        mnoznik = 1.0
    wynik["zrodlo"] = zrodlo
    wynik["nowa_sens"] = round(sens * mnoznik, 2) if zrodlo else sens
    wynik["zmiana"] = (wynik["nowa_sens"] / sens) - 1
    return wynik


def zastosuj_krzywa(wynik, sens, punkty):
    """Corrects the recommendation using scores from other tested sensitivities (the "score vs sensitivity" curve).

    punkty is a list of dicts {sens (converted to the current DPI), ocena, pm, flicki, dni, r_mediana}
    without the current sensitivity.
    - Another sensitivity has a clearly higher score (by MARGINES_OCENY and the +/- intervals do not
      overlap) and its sessions span at least MIN_DNI_KRZYWEJ days: that one is recommended.
    - Otherwise the recommendation from flicks stays, but it never moves toward a sensitivity that
      scored worse than the current one.
    """
    if "ocena" not in wynik or wynik.get("bez_zmiany") == "za_malo":
        return wynik
    pewne = [p for p in punkty if p["flicki"] >= MIN_FLICKOW_KRZYWEJ]
    if not pewne:
        return wynik
    obecna, pm = wynik["ocena"], wynik.get("ocena_pm", 0)
    lepsze = [p for p in pewne if p["dni"] >= MIN_DNI_KRZYWEJ
              and p["ocena"] >= obecna + MARGINES_OCENY and p["ocena"] - p["pm"] > obecna + pm]
    if lepsze:
        najlepszy = max(lepsze, key=lambda p: p["ocena"])
        nowa = round(najlepszy["sens"], 3)
        if nowa != sens:
            wynik.update(nowa_sens=nowa, zmiana=nowa / sens - 1, zrodlo="krzywa", bez_zmiany=None,
                         krzywa=(najlepszy["sens"], najlepszy["ocena"]))
        return wynik
    if wynik["nowa_sens"] != sens:
        kierunek = 1 if wynik["nowa_sens"] > sens else -1
        gorsze = [p for p in pewne if (p["sens"] - sens) * kierunek > 0 and p["ocena"] < obecna]
        if gorsze:
            najblizsza = min(gorsze, key=lambda p: abs(p["sens"] - sens))
            _zostan(wynik, sens, "krzywa", krzywa=(najblizsza["sens"], najblizsza["ocena"]), krzywa_kierunek=kierunek)
    return wynik


def _zostan(wynik, sens, powod, **dane):
    wynik.update(nowa_sens=sens, zmiana=0.0, zrodlo=None, bez_zmiany=powod, **dane)


def kierunek_sesji(flicki):
    """Direction of the recommendation from one session: +1 increase, -1 decrease, 0 no reliable direction."""
    if len(flicki) < 30:
        return 0
    r = [f.r for f in flicki]
    wagi = [f.waga for f in flicki]
    r_med = kwantyl_wazony(r, wagi, 0.5)
    rozrzut = kwantyl_wazony(r, wagi, 0.75) - kwantyl_wazony(r, wagi, 0.25)
    niepewnosc = 1.58 * rozrzut / math.sqrt(len(flicki))
    if abs(r_med - CEL_R) <= niepewnosc or abs(CEL_R / r_med - 1) < 0.03:
        return 0
    return 1 if r_med < CEL_R else -1


def zastosuj_zgodnosc(wynik, sens, kierunki_sesji):
    """Changes only when most of the recent sessions (at most 3) point the same way as the recommendation.

    With a single session there is nothing to compare, so the recommendation stays (it still needs
    MIN_FLICKOW_ZALECENIA). A recommendation from the score curve does not depend on flick direction and is left alone.
    """
    ostatnie = kierunki_sesji[-3:]
    if wynik.get("nowa_sens", sens) == sens or wynik.get("zrodlo") == "krzywa" or len(ostatnie) < 2:
        return wynik
    kierunek = 1 if wynik["nowa_sens"] > sens else -1
    if sum(1 for k in ostatnie if k == kierunek) * 2 <= len(ostatnie):
        _zostan(wynik, sens, "niezgodne", kierunki_sesji=ostatnie)
    return wynik


def zastosuj_zapadke(wynik, sens, poprzedni):
    """Ratchet lock: if the previous sensitivity change (for example upward) improved neither the median
    nor the score (beyond the uncertainty), another step in the same direction is not recommended.

    poprzedni is the curve point of the previous setting (dict as in zastosuj_krzywa) or None.
    """
    if not poprzedni or "r_mediana" not in wynik or wynik.get("nowa_sens", sens) == sens:
        return wynik
    ostatnia_zmiana = 1 if sens > poprzedni["sens"] else -1
    kierunek = 1 if wynik["nowa_sens"] > sens else -1
    if kierunek != ostatnia_zmiana:
        return wynik
    lepsza_mediana = abs(wynik["r_mediana"] - CEL_R) + wynik["niepewnosc"] < abs(poprzedni["r_mediana"] - CEL_R)
    lepsza_ocena = wynik["ocena"] - wynik.get("ocena_pm", 0) > poprzedni["ocena"] + poprzedni["pm"]
    if not (lepsza_mediana or lepsza_ocena):
        _zostan(wynik, sens, "zapadka", poprzednia_sens=poprzedni["sens"], zapadka_kierunek=kierunek)
    return wynik
