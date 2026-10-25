import rozdzielczosc
from konfiguracja import cm_na_360, edpi

MIN_FLICKOW = 150  # poniżej tej liczby zalecenie jest mało wiarygodne
NAZWY_GRUP = {"male": "małe (3–15°)", "srednie": "średnie (15–45°)", "duze": "duże (>45°)"}
SZEROKOSC_GLOWY_DEG = 0.5  # głowa z dalszego dystansu, do porównania z drżeniem

ZRODLA = {
    "flicki": "Zalecenie wynika z tego, gdzie kończy się ruch główny we flickach.",
    "flicki_i_sygnaly": "Zalecenie wynika z flicków, a inne sygnały (sekcja Sygnały) wskazują ten sam kierunek.",
    "flicki_oslabione": "Flicki wskazują zmianę, ale inne sygnały mówią przeciwnie – dlatego zalecana zmiana "
                        "jest o połowę mniejsza.",
    "flicki_sprzeczne": "Zalecenie wynika z flicków, ale jeden słaby sygnał (sekcja Sygnały) wskazuje przeciwny "
                        "kierunek – po zmianie sprawdź, czy się nie nasila.",
    "sygnaly": "Flicki nie dają wyraźnego kierunku, ale inne sygnały tak – dlatego tylko mały krok (5%).",
}


def opis_sygnalu(s):
    k, v = s["klucz"], s["wartosc"]
    if k == "podniesienia":
        return f"podnosisz mysz w trakcie obrotu ok. {v:.1f} razy na 10 min → czułość raczej za niska"
    if k == "drzenie":
        return f"celownik drży o ok. {v:.2f}°, gdy trzymasz kąt → czułość raczej za wysoka"
    if k == "male_za_daleko":
        return f"małe flicki kończą się za celem ({v:.0%}) → czułość raczej za wysoka"
    if k == "duze_za_krotko":
        return f"duże flicki są za krótkie ({v:.0%}) → czułość raczej za niska"
    return k


def linie_oceny(w, info):
    """Ocena celowania i informacje o jakości danych (lista linii)."""
    linie = [f"Ocena celowania: {w['ocena']}/100  (do porównywania czułości – wyższa = lepiej)",
             f"czas od początku flicka do strzału {w['czas_do_strzalu'] * 1000:.0f} ms · tempo {w['tempo']:.1f} bit/s · "
             f"rozrzut {w['rozrzut']:.2f} · korekty {w['korekty']:.1f}"]
    if info.get("z_zabojstwami"):
        tekst = f"potwierdzone zabójstwem: {w['trafione']} flicków (liczone 3×)"
        if w.get("r_trafione") is not None:
            tekst += f", ich mediana {w['r_trafione']:.0%}"
        linie.append(tekst)
    else:
        linie.append("brak danych o zabójstwach – sesje sprzed wersji 0.9.3 albo GSI nie działało")
    pominiete = []
    if w.get("w_serii"):
        pominiete.append(f"ruch w trakcie serii (odrzut): {w['w_serii']}×")
    if w.get("sledzenie"):
        pominiete.append(f"flicki ze śledzeniem ruchomego celu: {w['sledzenie']} (liczone w połowie)")
    if pominiete:
        linie.append("odsiane: " + " · ".join(pominiete))
    return linie


def linie_porownania(info, sens, ocena):
    """Oceny z innych czułości (to samo DPI i rozdzielczość)."""
    porownanie = info.get("porownanie") or []
    if not porownanie:
        return []
    wszystkie = sorted(porownanie + [(sens, ocena, None)])
    linie = []
    for s, o, n in wszystkie:
        znacznik = "  ← teraz" if s == sens else f"  ({n} flicków)"
        linie.append(f"sens {s}: {o}/100{znacznik}")
    najlepsza = max(wszystkie, key=lambda x: x[1])
    if najlepsza[0] != sens:
        linie.append(f"Najwyższa ocena do tej pory: sens {najlepsza[0]} ({najlepsza[1]}/100).")
    return linie


def porady(w):
    """Zwraca listę (tytuł, co się dzieje, jak to poprawić)."""
    lista = []
    if "r_mediana" not in w:
        return lista
    zrodlo = w.get("zrodlo") or ""

    if w["zmiana"] < 0 and zrodlo.startswith("flicki"):
        lista.append(("Przestrzeliwujesz cele",
                      f"Ruch główny kończy się średnio za celem ({w['przestrzal']:.0%} flicków to przestrzał).",
                      "Zmniejsz czułość zgodnie z zaleceniem. Graj na niej co najmniej 3–4 dni, "
                      "zanim ocenisz – pierwsze dni zawsze są dziwne."))
    elif w["zmiana"] > 0 and zrodlo.startswith("flicki"):
        lista.append(("Nie dociągasz do celu",
                      f"Często zatrzymujesz się przed celem ({w['niedociagniecie']:.0%} flicków) i dociągasz drugim ruchem.",
                      "Zwiększ czułość zgodnie z zaleceniem. Sprawdź też, czy mysz nie dojeżdża "
                      "do krawędzi podkładki – to też daje niedociągnięcia."))

    klucze_sygnalow = {s["klucz"]: s for s in w.get("sygnaly", [])}
    if "podniesienia" in klucze_sygnalow:
        n = klucze_sygnalow["podniesienia"]["wartosc"]
        lista.append(("Podnosisz mysz w trakcie obrotu",
                      f"Ok. {n:.1f} razy na 10 min szybki obrót urywa się w połowie i po chwili idzie dalej – "
                      "przy tej czułości brakuje Ci miejsca na podkładce.",
                      "To znak, że czułość jest raczej za niska (albo podkładka za mała). Sprawdź, czy obrót "
                      "o 180° mieści się na podkładce bez podnoszenia myszy."))
    if "drzenie" in klucze_sygnalow:
        d = klucze_sygnalow["drzenie"]["wartosc"]
        lista.append(("Celownik drży, gdy trzymasz kąt",
                      f"Drobne poruszenia celownika mają ok. {d:.2f}° – to ok. {d / SZEROKOSC_GLOWY_DEG:.0%} "
                      "szerokości głowy przeciwnika z dalszego dystansu.",
                      "Niższa czułość zmniejszy drżenie. Pomaga też oparcie przedramienia o biurko "
                      "i luźniejszy chwyt."))
    if "male_za_daleko" in klucze_sygnalow:
        lista.append(("Małe poprawki lecą za daleko",
                      "Przy małych flickach (3–15°) przestrzeliwujesz wyraźniej niż przy średnich – typowe "
                      "przy za wysokiej czułości.",
                      "Małe poprawki rób spokojnie, palcami i nadgarstkiem. Jeśli to się utrzymuje, "
                      "obniż czułość."))

    grupy = w.get("grupy", {})
    male, duze = grupy.get("male"), grupy.get("duze")
    if male and duze and duze[0] - male[0] > 0.10:
        lista.append(("Duże flicki lecą za daleko",
                      "Małe ruchy masz dokładne, ale przy dużych przestrzeliwujesz.",
                      "Duże obroty rób przedramieniem, nie samym nadgarstkiem, i zwalniaj "
                      "przed celem. Na mapie aim_botz ćwicz flicki między odległymi botami."))
    elif male and duze and male[0] - duze[0] > 0.10:
        lista.append(("Duże flicki są za krótkie",
                      "Małe ruchy są OK, ale duże kończysz przed celem.",
                      "Często to brak miejsca na podkładce albo za mocno dociśnięta ręka. "
                      "Ustaw podkładkę tak, żeby przy 180° mysz nie dojeżdżała do krawędzi."))

    if w["korekty"] > 1.3:
        lista.append(("Za dużo mikrokorekt",
                      f"Po ruchu głównym poprawiasz średnio {w['korekty']:.1f} razy przed strzałem.",
                      "Na aim_botz ćwicz wolniej: jeden ruch, jeden strzał, bez poprawiania. "
                      "Najpierw celność, prędkość przyjdzie sama. Rozluźnij chwyt."))

    if w["pion"] > 1.5:
        lista.append(("Poprawiasz celownik w pionie",
                      f"Przed strzałem korygujesz średnio {w['pion']:.1f}° w górę/dół.",
                      "To kwestia ustawienia celownika (crosshair placement): trzymaj go cały "
                      "czas na wysokości głowy. Ćwicz na mapach prefire/yprac, chodząc po mapie "
                      "i pilnując wysokości celownika przy rogach."))

    if w["rozmiar"] > 25:
        lista.append(("Flicki są bardzo duże",
                      f"Typowy flick to {w['rozmiar']:.0f}° – przeciwnik zwykle wychodzi daleko od celownika.",
                      "Ustawiaj celownik tam, gdzie spodziewasz się przeciwnika (pre-aim rogów). "
                      "Im mniejszy flick, tym łatwiej trafić niezależnie od czułości."))

    if w["boczny"] > 0.15:
        lista.append(("Ruch idzie obok celu",
                      "Kierunek ruchu głównego często mija cel bokiem.",
                      "Patrz na cel, a nie na celownik. Ćwicz flicki po przekątnej "
                      "(np. na aim_botz) – tam najczęściej ucieka kierunek."))

    if w["procent_w_ruchu"] > 0.25:
        lista.append(("Strzelasz w trakcie ruchu",
                      f"{w['procent_w_ruchu']:.0%} strzałów pada, zanim celownik się zatrzymał.",
                      "Przy karabinach strzał w ruchu rzadko trafia. Najpierw zatrzymaj celownik "
                      "na celu, dopiero potem klik. Pomaga też counter-strafe przed strzałem."))

    if w["czas_korekty"] > 0.25:
        lista.append(("Długo zwlekasz ze strzałem",
                      f"Od końca ruchu do strzału mija ok. {w['czas_korekty'] * 1000:.0f} ms.",
                      "Ćwicz rytm 'ruch–strzał' na botach w trybie headshot-only. "
                      "Jeśli dużo poprawiasz, zacznij od porady o mikrokorektach."))
    return lista


def formatuj(w, sens, dpi, sesje, minuty, ocena_obrazu=None, info=None):
    info = info or {}
    linie = ["", "=" * 60, "  SensFit – raport czułości CS2", "=" * 60,
             f"Ustawienia: sens {sens} | DPI {dpi} | eDPI {edpi(sens, dpi):.0f} | "
             f"{cm_na_360(sens, dpi):.1f} cm/360°",
             f"Dane: {sesje} sesji, ok. {minuty:.0f} min gry, "
             f"{w['liczba']} flicków zakończonych strzałem", ""]
    if ocena_obrazu:
        linie += ["Obraz:"] + [f"  {l}" for l in rozdzielczosc.opis(ocena_obrazu)] + [""]

    if "r_mediana" not in w:
        linie.append("Za mało danych. Zagraj dłużej (najlepiej 20–30 min deathmatchu) i nagraj ponownie.")
        return "\n".join(linie)

    linie += ["Gdzie kończy się Twój ruch główny (95% = idealnie, 100% = dokładnie na celu):",
              f"  mediana: {w['r_mediana']:.0%}  (niepewność ±{w['niepewnosc']:.0%})",
              f"  przestrzał: {w['przestrzal']:.0%} | w punkt: {w['w_punkt']:.0%} | "
              f"niedociągnięcie: {w['niedociagniecie']:.0%}"]
    for klucz, (r, n) in w.get("grupy", {}).items():
        linie.append(f"  {NAZWY_GRUP.get(klucz, klucz)}: {r:.0%} (n={n})")
    linie += [""] + [f"  {l}" for l in linie_oceny(w, info)]
    porownanie = linie_porownania(info, sens, w["ocena"])
    if porownanie:
        linie += ["", "Ocena na różnych czułościach (to samo DPI i rozdzielczość):"] + [f"  {l}" for l in porownanie]
    if w.get("sygnaly"):
        linie += ["", "Sygnały:"] + [f"  - {opis_sygnalu(s)}" for s in w["sygnaly"]]
    linie.append("")

    if w["nowa_sens"] != sens:
        nowa = w["nowa_sens"]
        linie.append(f">>> ZALECENIE: zmień czułość z {sens} na {nowa} ({w['zmiana']:+.0%})")
        linie.append(f"    eDPI {edpi(nowa, dpi):.0f}, {cm_na_360(nowa, dpi):.1f} cm/360°")
        linie.append(f"    W konsoli CS2 wpisz: sensitivity {nowa}")
        linie.append(f"    {ZRODLA.get(w.get('zrodlo'), '')}")
    else:
        linie.append(">>> Czułość wygląda dobrze – brak wyraźnego sygnału, żeby ją zmieniać.")
    if w["liczba"] < MIN_FLICKOW:
        linie.append(f"    Uwaga: tylko {w['liczba']} flicków (zalecane {MIN_FLICKOW}+) – "
                     "traktuj zalecenie ostrożnie.")

    lista = porady(w) + rozdzielczosc.porady(ocena_obrazu, sens)
    if lista:
        linie += ["", "Co poprawić:"]
        for i, (tytul, co, jak) in enumerate(lista, 1):
            linie += [f"{i}. {tytul}", f"   Co: {co}", f"   Jak: {jak}"]
    linie += ["", "Po zmianie czułości zagraj kilka dni i nagraj nową sesję – "
                  "program sprawdzi, czy jest lepiej.", ""]
    return "\n".join(linie)
