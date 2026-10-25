import bisect
import math
import statistics
from dataclasses import dataclass

KUBELEK_S = 0.004        # musi być takie jak w mysz_windows.py
M_YAW = 0.022
PRZERWA_S = 0.040        # cisza dłuższa niż 40 ms = koniec ruchu
MIN_FLICK_DEG = 3.0      # mniejsze ruchy to mikrokorekty, nie flicki
MIN_SZCZYT_DEG_S = 100.0 # flick musi być w miarę szybki
OKNO_STRZALU_S = 0.40    # strzał do 400 ms po ruchu głównym = celowałeś w coś
OKNO_TRAFIENIA_S = 0.90  # zabójstwo do 0,9 s po strzale = trafiłeś (GSI ma ok. 0,1-0,2 s opóźnienia)
CEL_R = 0.95             # naturalne lekkie niedociągnięcie
MAX_ZMIANA = 0.15        # nie zmieniamy czułości o więcej niż 15% naraz
KROK_Z_SYGNALOW = 0.05   # gdy r nie daje pewności, ale sygnały są wyraźne - mały krok 5%
WAGA_TRAFIENIA = 3.0
WAGA_SLEDZENIA = 0.5

# Progi sygnałów (heurystyki - do dostrojenia na danych testerów)
PODNIESIENIA_NA_10_MIN = 2      # tyle podniesień myszy w trakcie obrotu na 10 min = czułość raczej za niska
DRZENIE_DEG = 0.20              # drżenie większe niż ok. 40% szerokości głowy z daleka = raczej za wysoka
MIN_ZDARZEN_DRZENIA = 50


@dataclass
class Flick:
    rozmiar_deg: float      # odległość od startu do miejsca strzału
    r: float                # ruch główny / odległość (patrz opis wyżej)
    blad_boczny: float      # o ile ruch główny poszedł obok (ułamek odległości)
    korekta_pion_deg: float # ile poprawiałeś w pionie
    czas_korekty_s: float   # od końca ruchu głównego do strzału
    liczba_korekt: int
    czas_do_strzalu_s: float = 0.0  # od początku ruchu do strzału
    trafienie: bool = False         # po strzale padło zabójstwo (GSI)
    sledzenie: bool = False         # przed strzałem płynnie podążałeś za ruchomym celem

    @property
    def waga(self):
        if self.trafienie:
            return WAGA_TRAFIENIA
        return WAGA_SLEDZENIA if self.sledzenie else 1.0


# ---------------------------------------------------------------- pomocnicze
def podziel_na_ruchy(kubelki):
    """Dzieli listę kubełków na osobne ruchy rozdzielone chwilą bezruchu."""
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
    """Prędkość w °/s w każdym kubełku, wygładzona średnią z 3 sąsiadów."""
    v = [math.hypot(x, y) / KUBELEK_S for x, y in zip(dx, dy)]
    return [sum(v[max(0, i - 1):i + 2]) / len(v[max(0, i - 1):i + 2]) for i in range(len(v))]


def na_gesto(ruch, deg_na_count):
    """Ruch jako równe kroki co 4 ms (zera tam, gdzie mysz stała), w stopniach."""
    t0 = ruch[0][0]
    n = round((ruch[-1][0] - t0) / KUBELEK_S) + 1
    dx, dy = [0.0] * n, [0.0] * n
    for t, x, y in ruch:
        i = round((t - t0) / KUBELEK_S)
        dx[i] += x * deg_na_count
        dy[i] += y * deg_na_count
    return dx, dy


def kwantyl_wazony(wartosci, wagi, q):
    """Kwantyl z wagami (q=0.5 to mediana ważona)."""
    pary = sorted(zip(wartosci, wagi))
    suma = sum(w for _, w in pary)
    prog, narastajaco = q * suma, 0.0
    for wartosc, waga in pary:
        narastajaco += waga
        if narastajaco >= prog:
            return wartosc
    return pary[-1][0]


class Serie:
    """Kiedy lewy przycisk był wciśnięty (od kliknięcia do puszczenia)."""

    def __init__(self, klikniecia, puszczenia):
        self.wcisniecia = sorted(klikniecia)
        puszczenia = sorted(puszczenia or [])
        self.dostepne = bool(puszczenia)  # starsze sesje nie mają puszczeń - wtedy nie filtrujemy
        self.konce = []
        for t in self.wcisniecia:
            j = bisect.bisect_right(puszczenia, t)
            self.konce.append(puszczenia[j] if j < len(puszczenia) else t + 0.15)

    def w_trakcie_serii(self, t):
        """Czy w chwili t trwała seria (przycisk wciśnięty dłużej niż ułamek sekundy)."""
        if not self.dostepne:
            return False
        i = bisect.bisect_right(self.wcisniecia, t) - 1
        return i >= 0 and self.wcisniecia[i] + 0.03 < t < self.konce[i]


# ---------------------------------------------------------------- jeden ruch -> flick
def analizuj_ruch(ruch, klikniecia, deg_na_count, serie=None, zabojstwa=None):
    """Zwraca (Flick lub None, czy_strzal_w_ruchu, czy_pominiety_bo_seria)."""
    t0 = ruch[0][0]
    if serie and serie.w_trakcie_serii(t0):
        return None, False, True          # kontrola odrzutu w trakcie serii, nie flick
    dx, dy = na_gesto(ruch, deg_na_count)
    n = len(dx)

    v = predkosci(dx, dy)
    szczyt = max(range(n), key=lambda i: v[i])
    vmax = v[szczyt]
    if vmax < MIN_SZCZYT_DEG_S:
        return None, False, False

    # Koniec ruchu głównego: prawie się zatrzymałeś ALBO zwolniłeś i znów przyspieszasz (korekta)
    koniec = n - 1
    for i in range(szczyt + 1, n):
        if v[i] < 0.08 * vmax or (v[i] < 0.5 * vmax and i + 1 < n and v[i + 1] > v[i]):
            koniec = i
            break
    t_koniec = t0 + (koniec + 1) * KUBELEK_S

    # Pierwszy strzał w pobliżu końca ruchu głównego
    j = bisect.bisect_left(klikniecia, t0)
    if j >= len(klikniecia) or klikniecia[j] > t_koniec + OKNO_STRZALU_S:
        return None, False, False           # nie strzelałeś - to nie był flick na cel
    t_strzalu = klikniecia[j]
    if t_strzalu < t_koniec - 0.02:
        return None, True, False            # strzał zanim celownik się zatrzymał

    px, py = sum(dx[:koniec + 1]), sum(dy[:koniec + 1])        # ruch główny
    do_strzalu = min(n, int((t_strzalu - t0) / KUBELEK_S))
    kx, ky = sum(dx[koniec + 1:do_strzalu]), sum(dy[koniec + 1:do_strzalu])  # korekty
    cx, cy = px + kx, py + ky                                  # cel = miejsce strzału
    odl = math.hypot(cx, cy)
    if odl < MIN_FLICK_DEG or math.hypot(px, py) < MIN_FLICK_DEG:
        return None, False, False

    r = (px * cx + py * cy) / odl ** 2          # rzut ruchu głównego na kierunek do celu
    if not 0.4 <= r <= 1.8:
        return None, False, False               # to raczej nie był jeden flick do jednego celu
    boczny = abs(px * cy - py * cx) / odl ** 2

    korekty = sum(1 for i in range(koniec + 1, min(do_strzalu, n - 1))
                  if v[i] > v[i - 1] and v[i] >= v[i + 1] and v[i] > max(30, 0.05 * vmax))

    # Śledzenie: po ruchu głównym płynnie, w jednym kierunku, przez >= 150 ms - cel się ruszał
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


# ---------------------------------------------------------------- sygnały z całej sesji
def opis_ruchu(ruch, deg_na_count):
    """Krótki opis ruchu potrzebny do wykrywania podniesień i drżenia."""
    dx, dy = na_gesto(ruch, deg_na_count)
    v = predkosci(dx, dy)
    vmax = max(v)
    koncowka = v[-3:]
    return {
        "start": ruch[0][0], "koniec": ruch[-1][0] + KUBELEK_S,
        "sx": sum(dx), "sy": sum(dy), "droga": sum(math.hypot(a, b) for a, b in zip(dx, dy)),
        "vmax": vmax, "kubelki": len(dx),
        # Urwany koniec: ruch kończy się przy dużej prędkości, bez hamowania - typowe przy podniesieniu myszy
        "urwany": vmax > 0 and sum(koncowka) / len(koncowka) > 0.3 * vmax,
    }


def wykryj_podniesienia(opisy):
    """Podniesienie myszy w trakcie obrotu: szybki ruch urywa się bez hamowania,
    po krótkiej przerwie (do 0,35 s) ruch idzie dalej w tę samą stronę."""
    licznik = 0
    for a, b in zip(opisy, opisy[1:]):
        przerwa = b["start"] - a["koniec"]
        if not (0.03 <= przerwa <= 0.35):
            continue
        if not (a["urwany"] and a["vmax"] >= 150 and a["droga"] >= 15 and b["droga"] >= 5):
            continue
        dl_a, dl_b = math.hypot(a["sx"], a["sy"]), math.hypot(b["sx"], b["sy"])
        if dl_a and dl_b and (a["sx"] * b["sx"] + a["sy"] * b["sy"]) / (dl_a * dl_b) >= 0.8:
            licznik += 1
    return licznik


def wykryj_drzenie(opisy):
    """Drżenie: bardzo krótkie (do 16 ms) i małe (< 1°) poruszenia celownika, odizolowane od
    innych ruchów - tak wygląda drganie ręki, gdy trzymasz kąt. Zwraca listę amplitud w stopniach."""
    amplitudy = []
    for i, o in enumerate(opisy):
        if o["kubelki"] > 4 or o["droga"] >= 1.0:
            continue
        przed = o["start"] - opisy[i - 1]["koniec"] if i > 0 else 1.0
        po = opisy[i + 1]["start"] - o["koniec"] if i + 1 < len(opisy) else 1.0
        if przed >= 0.10 and po >= 0.10:
            amplitudy.append(math.hypot(o["sx"], o["sy"]))
    return amplitudy


def znajdz_flicki(kubelki, klikniecia, sens, puszczenia=None, zabojstwa=None):
    """Przetwarza całą sesję. Zwraca (flicki, liczba strzałów w ruchu, dodatkowe dane)."""
    deg_na_count = sens * M_YAW
    klikniecia = sorted(klikniecia)
    ma_zabojstwa = zabojstwa is not None  # starsze sesje nie mają danych o zabójstwach
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
    dodatkowe = {"podniesienia": wykryj_podniesienia(opisy), "drzenie": wykryj_drzenie(opisy),
                 "w_serii": w_serii, "zabojstwa": len(zabojstwa), "ma_zabojstwa": ma_zabojstwa}
    return flicki, w_ruchu, dodatkowe


def polacz_dodatkowe(lista):
    """Sumuje dodatkowe dane z kilku sesji."""
    wynik = {"podniesienia": 0, "drzenie": [], "w_serii": 0, "zabojstwa": 0}
    for d in lista:
        wynik["podniesienia"] += d["podniesienia"]
        wynik["drzenie"] += d["drzenie"]
        wynik["w_serii"] += d["w_serii"]
        wynik["zabojstwa"] += d["zabojstwa"]
    return wynik


# ---------------------------------------------------------------- ocena i zalecenie
def ocena_celowania(r_med, rozrzut, korekty, tempo):
    """Ocena 0-100 do porównywania czułości ze sobą (wyższa = lepiej). Składniki:
    celność (jak blisko 95%), rozrzut flicków, liczba korekt i tempo (bity/s jak w prawie Fittsa)."""
    s_cel = max(0.0, 1 - abs(r_med - CEL_R) / 0.25)
    s_rozrzut = max(0.0, 1 - rozrzut / 0.5)
    s_korekty = max(0.0, 1 - korekty / 3)
    s_tempo = min(1.0, tempo / 10)
    return round(100 * (0.35 * s_cel + 0.25 * s_rozrzut + 0.20 * s_korekty + 0.20 * s_tempo))


def tempo_flicka(f):
    """Tempo jak w prawie Fittsa: trudność ruchu (log2 odległości/szerokości celu) na sekundę.
    Szerokość celu przyjmujemy 1° (mniej więcej głowa na średnim dystansie)."""
    return math.log2(f.rozmiar_deg / 1.0 + 1) / max(f.czas_do_strzalu_s, 0.05)


def sygnaly_kierunku(wynik, dodatkowe, minuty):
    """Sygnały, że czułość jest za niska (+1) albo za wysoka (-1). Siła 1 = słaby, 2 = wyraźny."""
    sygnaly = []
    podn = dodatkowe.get("podniesienia", 0)
    if minuty > 0:
        na_10 = podn / minuty * 10
        if na_10 >= PODNIESIENIA_NA_10_MIN:
            sygnaly.append({"klucz": "podniesienia", "kierunek": +1, "sila": 2 if na_10 >= 5 else 1,
                            "wartosc": na_10})
    drzenie = dodatkowe.get("drzenie", [])
    if len(drzenie) >= MIN_ZDARZEN_DRZENIA:
        d = statistics.median(drzenie)
        if d >= DRZENIE_DEG:
            sygnaly.append({"klucz": "drzenie", "kierunek": -1, "sila": 2 if d >= 0.35 else 1, "wartosc": d})
    grupy = wynik.get("grupy", {})
    male, srednie, duze = grupy.get("male"), grupy.get("srednie"), grupy.get("duze")
    if male and srednie and male[0] > 1.05 and male[0] - srednie[0] > 0.04:
        sygnaly.append({"klucz": "male_za_daleko", "kierunek": -1, "sila": 1, "wartosc": male[0]})
    if duze and srednie and duze[0] < 0.88 and srednie[0] - duze[0] > 0.04:
        sygnaly.append({"klucz": "duze_za_krotko", "kierunek": +1, "sila": 1, "wartosc": duze[0]})
    return sygnaly


def podsumuj(flicki, w_ruchu, sens, dodatkowe=None, minuty=0.0):
    """Liczy statystyki, ocenę celowania i zalecaną czułość."""
    dodatkowe = dodatkowe or {}
    wynik = {"liczba": len(flicki), "w_ruchu": w_ruchu, "w_serii": dodatkowe.get("w_serii", 0),
             "zabojstwa": dodatkowe.get("zabojstwa", 0), "podniesienia": dodatkowe.get("podniesienia", 0)}
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

    # Celność w zależności od wielkości flicka
    grupy = {"male": (3, 15), "srednie": (15, 45), "duze": (45, 999)}
    wynik["grupy"] = {}
    for nazwa, (od, do) in grupy.items():
        rg = [(f.r, f.waga) for f in flicki if od <= f.rozmiar_deg < do]
        if len(rg) >= 15:
            wynik["grupy"][nazwa] = (kwantyl_wazony([x for x, _ in rg], [w for _, w in rg], 0.5), len(rg))

    wynik["ocena"] = ocena_celowania(r_med, rozrzut, wynik["korekty"], tempo)
    wynik["sygnaly"] = sygnaly_kierunku(wynik, dodatkowe, minuty)
    netto = sum(s["kierunek"] * s["sila"] for s in wynik["sygnaly"])

    # Zalecenie: r_med = 1.10 -> ruch ręki daje 10% za dużo obrotu -> zmniejsz czułość
    mnoznik = min(1 + MAX_ZMIANA, max(1 - MAX_ZMIANA, CEL_R / r_med))
    pewne = abs(r_med - CEL_R) > niepewnosc and abs(mnoznik - 1) >= 0.03
    zrodlo = None
    if pewne:
        zrodlo = "flicki"
        kierunek_r = 1 if mnoznik > 1 else -1
        if netto * kierunek_r <= -2:           # wyraźne sygnały w przeciwną stronę - ostrożniej
            mnoznik = 1 + (mnoznik - 1) / 2
            zrodlo = "flicki_oslabione"
        elif netto * kierunek_r == -1:         # jeden słaby sygnał przeciwny - zmiana zostaje, ale z uwagą
            zrodlo = "flicki_sprzeczne"
        elif netto * kierunek_r >= 1:
            zrodlo = "flicki_i_sygnaly"
    elif abs(netto) >= 2:                      # flicki bez wyraźnego kierunku, ale sygnały tak
        mnoznik = 1 + KROK_Z_SYGNALOW * (1 if netto > 0 else -1)
        zrodlo = "sygnaly"
    else:
        mnoznik = 1.0
    wynik["zrodlo"] = zrodlo
    wynik["nowa_sens"] = round(sens * mnoznik, 2) if zrodlo else sens
    wynik["zmiana"] = (wynik["nowa_sens"] / sens) - 1
    return wynik
