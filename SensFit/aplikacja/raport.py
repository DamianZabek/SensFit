"""Turns the analysis results into a readable report with advice: what to improve and how.

The opis_* and linie_* functions are shared by the program window and the ostatni_raport.txt file.
Texts come in Polish or English (jezyk.t) and every piece of advice has a key that the
"Training maps" tab uses to pick maps.
"""
import analiza
import konfiguracja
import rozdzielczosc
import wersja
from jezyk import t
from konfiguracja import cm_na_360, edpi

MIN_FLICKOW = 150  # below this number the recommendation is not very reliable
SZEROKOSC_GLOWY_DEG = 0.5  # head seen from a longer distance, for comparison with the tremor


def nazwy_grup():
    return {"male": t("małe (3–15°)", "small (3–15°)"),
            "srednie": t("średnie (15–45°)", "medium (15–45°)"),
            "duze": t("duże (>45°)", "large (>45°)")}


def linia_grupy(klucz, g):
    """One group of flicks on its own: median, score and what it indicates."""
    r, n, ocena, kierunek = g
    co = {1: t("wskazują zwiększenie", "point to raising"), -1: t("wskazują zmniejszenie", "point to lowering"),
          0: t("bez wyraźnego kierunku", "no clear direction")}[kierunek]
    return f"{nazwy_grup().get(klucz, klucz)}: {r:.0%} · " + t("ocena", "score") + f" {ocena} · {co} (n={n})"


def zrodla():
    return {
        "flicki": t("Zalecenie wynika z tego, gdzie kończy się ruch główny we flickach.",
                    "The recommendation comes from where the main movement of your flicks ends."),
        "flicki_i_sygnaly": t("Zalecenie wynika z flicków, a inne sygnały (sekcja Sygnały) wskazują ten sam kierunek.",
                              "The recommendation comes from your flicks, and other signals (Signals section) "
                              "point the same way."),
        "flicki_oslabione": t("Flicki wskazują zmianę, ale inne sygnały mówią przeciwnie - dlatego zalecana zmiana "
                              "jest o połowę mniejsza.",
                              "Your flicks point to a change, but other signals say the opposite, so the "
                              "recommended change is halved."),
        "flicki_sprzeczne": t("Zalecenie wynika z flicków, ale jeden słaby sygnał (sekcja Sygnały) wskazuje przeciwny "
                              "kierunek - po zmianie sprawdź, czy się nie nasila.",
                              "The recommendation comes from your flicks, but one weak signal (Signals section) "
                              "points the other way. After the change, check that it does not get worse."),
        "sygnaly": t("Flicki nie dają wyraźnego kierunku, ale inne sygnały zgodnie tak - dlatego tylko mały krok (5%).",
                     "Your flicks show no clear direction, but other signals agree on one, so this is only a small "
                     "step (5%)."),
        "krzywa": t("Ta czułość ma wyraźnie wyższą ocenę celowania spośród tych, na których już grałeś "
                    "(wykres „Ocena a czułość”).",
                    "This sensitivity has a clearly higher aim score among the ones you have already played "
                    "(“Score vs sensitivity” chart)."),
    }


def powod_bez_zmiany(w):
    """Why there is no recommendation to change (text), or an empty string."""
    if w.get("bez_zmiany") == "za_malo":
        ile = analiza.minut_do_celu(w["liczba"], w.get("minuty"))
        if ile:
            return t(f"Za mało danych na zalecenie - potrzeba co najmniej {analiza.MIN_FLICKOW_ZALECENIA} flicków "
                     f"(teraz {w['liczba']}). Nagraj jeszcze ok. {ile} min na tej czułości.",
                     f"Not enough data for a recommendation - at least {analiza.MIN_FLICKOW_ZALECENIA} flicks are "
                     f"needed (now {w['liczba']}). Record about {ile} more min on this sensitivity.")
        return t(f"Za mało danych na zalecenie - potrzeba co najmniej {analiza.MIN_FLICKOW_ZALECENIA} flicków "
                 f"(teraz {w['liczba']}). Nagraj jeszcze jedną sesję.",
                 f"Not enough data for a recommendation - at least {analiza.MIN_FLICKOW_ZALECENIA} flicks are "
                 f"needed (now {w['liczba']}). Record another session.")
    if w.get("bez_zmiany") == "krzywa":
        s, o = w["krzywa"]
        if w.get("krzywa_kierunek", 1) > 0:
            return t(f"Flicki wskazywały zwiększenie, ale wyższa czułość ({s:g}) miała niższą ocenę ({o}/100) - "
                     "zostań przy obecnej.",
                     f"Your flicks pointed to raising it, but a higher sensitivity ({s:g}) scored lower ({o}/100) - "
                     "stay on the current one.")
        return t(f"Flicki wskazywały zmniejszenie, ale niższa czułość ({s:g}) miała niższą ocenę ({o}/100) - "
                 "zostań przy obecnej.",
                 f"Your flicks pointed to lowering it, but a lower sensitivity ({s:g}) scored lower ({o}/100) - "
                 "stay on the current one.")
    if w.get("bez_zmiany") == "niezgodne":
        return t("Zostań przy obecnej - wyniki z ostatnich sesji wskazują różne kierunki. Nagraj kolejną sesję.",
                 "Stay on the current one - your latest sessions point in different directions. Record another "
                 "session.")
    if w.get("bez_zmiany") == "zapadka":
        p = w["poprzednia_sens"]
        if w.get("zapadka_kierunek", 1) > 0:
            return t(f"Ostatnie podniesienie czułości nie poprawiło wyników - zostań albo wróć do {p:g}.",
                     f"Your last sensitivity increase did not improve your results - stay or go back to {p:g}.")
        return t(f"Ostatnie obniżenie czułości nie poprawiło wyników - zostań albo wróć do {p:g}.",
                 f"Your last sensitivity decrease did not improve your results - stay or go back to {p:g}.")
    return ""


def opis_sygnalu(s):
    k, v = s["klucz"], s["wartosc"]
    if k == "podniesienia":
        return t(f"podnosisz mysz w trakcie dużego obrotu ok. {v:.1f} razy na 10 min (tylko informacja)",
                 f"you lift the mouse during a large turn about {v:.1f} times per 10 min (information only)")
    if k == "drzenie":
        return t(f"celownik drży o ok. {v:.2f}°, gdy trzymasz kąt → czułość raczej za wysoka",
                 f"your crosshair shakes by about {v:.2f}° when holding an angle → sensitivity probably too high")
    if k == "male_za_daleko":
        return t(f"małe flicki kończą się za celem ({v:.0%}) → czułość raczej za wysoka",
                 f"small flicks end past the target ({v:.0%}) → sensitivity probably too high")
    if k == "duze_za_krotko":
        return t(f"duże flicki są za krótkie ({v:.0%}) → czułość raczej za niska",
                 f"large flicks fall short ({v:.0%}) → sensitivity probably too low")
    return k


def sygnaly_sprzeczne(w, sens):
    """Whether the direction signals say something different than the recommendation (or the recommendation is "stay" while they point somewhere)."""
    kierunek = 0 if w.get("nowa_sens", sens) == sens else (1 if w["nowa_sens"] > sens else -1)
    return any(s["kierunek"] and s["kierunek"] != kierunek for s in w.get("sygnaly", []))


def linie_sygnalow(w, sens):
    """Signals for the report. When they contradict the recommendation, one sentence replaces several conflicting messages."""
    if sygnaly_sprzeczne(w, sens):
        info = [opis_sygnalu(s) for s in w["sygnaly"] if not s["kierunek"]]
        return [t("Sygnały i flicki wskazują różne kierunki, więc zalecenie opiera się na flickach i ocenie.",
                  "Signals and flicks point in different directions, so the recommendation relies on flicks "
                  "and the score.")] + info
    return [opis_sygnalu(s) for s in w["sygnaly"]]


def linie_oceny(w, info):
    """Aim score and information about data quality (list of lines)."""
    pm = w.get("ocena_pm", 0)
    linie = [t(f"Ocena celowania: {w['ocena']} ± {pm}/100  (do porównywania czułości - wyższa = lepiej)",
               f"Aim score: {w['ocena']} ± {pm}/100  (for comparing sensitivities - higher is better)"),
             t(f"czas od początku flicka do strzału {w['czas_do_strzalu'] * 1000:.0f} ms · tempo {w['tempo']:.1f} bit/s · "
               f"rozrzut {w['rozrzut']:.2f} · korekty {w['korekty']:.1f}",
               f"time from flick start to shot {w['czas_do_strzalu'] * 1000:.0f} ms · pace {w['tempo']:.1f} bit/s · "
               f"spread {w['rozrzut']:.2f} · corrections {w['korekty']:.1f}")]
    if info.get("z_zabojstwami"):
        tekst = t(f"potwierdzone zabójstwem: {w['trafione']} flicków (liczone 3×)",
                  f"confirmed by a kill: {w['trafione']} flicks (counted 3×)")
        if w.get("r_trafione") is not None:
            tekst += t(f", ich mediana {w['r_trafione']:.0%}", f", their median {w['r_trafione']:.0%}")
        linie.append(tekst)
    else:
        linie.append(t("brak danych o zabójstwach - sesje sprzed wersji 0.9.3 albo GSI nie działało",
                       "no kill data - sessions older than 0.9.3 or GSI was not working"))
    pominiete = []
    if w.get("w_serii"):
        pominiete.append(t(f"ruch w trakcie serii (odrzut): {w['w_serii']}×",
                           f"movement during a spray (recoil): {w['w_serii']}×"))
    if w.get("sledzenie"):
        pominiete.append(t(f"flicki ze śledzeniem ruchomego celu: {w['sledzenie']} (liczone w połowie)",
                           f"flicks tracking a moving target: {w['sledzenie']} (counted at half weight)"))
    if pominiete:
        linie.append(t("odsiane: ", "filtered out: ") + " · ".join(pominiete))
    return linie


def linie_porownania(info, sens, ocena, pm=0):
    """Scores of other sensitivities (same DPI and resolution)."""
    porownanie = info.get("porownanie") or []
    if not porownanie:
        return []
    wszystkie = sorted(porownanie + [{"sens": sens, "ocena": ocena, "pm": pm, "teraz": True}], key=lambda p: p["sens"])
    linie = []
    for p in wszystkie:
        if p.get("teraz"):
            znacznik = t("  ← teraz", "  ← now")
        else:
            znacznik = t(f"  ({p['flicki']} flicków, dni: {p['dni']})", f"  ({p['flicki']} flicks, days: {p['dni']})")
        linie.append(f"sens {p['sens']:g}: {p['ocena']} ± {p['pm']}/100{znacznik}")
    najlepsza = max(wszystkie, key=lambda p: p["ocena"])
    if not najlepsza.get("teraz"):
        linie.append(t(f"Najwyższa ocena do tej pory: sens {najlepsza['sens']:g} ({najlepsza['ocena']}/100). "
                       "Zalecana jest dopiero, gdy przedziały ± się nie nakładają i grałeś na niej co najmniej 2 dni.",
                       f"Highest score so far: sens {najlepsza['sens']:g} ({najlepsza['ocena']}/100). "
                       "It is recommended only when the ± ranges do not overlap and you played it on 2+ days."))
    return linie


def porady_z_kluczami(w):
    """List of (key, title, what is happening, how to improve it). The key is used to pick training maps."""
    lista = []
    if "r_mediana" not in w:
        return lista
    zrodlo = w.get("zrodlo") or ""

    if w["zmiana"] < 0 and zrodlo.startswith("flicki"):
        lista.append(("przestrzal", t("Przestrzeliwujesz cele", "You overshoot targets"),
                      t(f"Ruch główny kończy się średnio za celem ({w['przestrzal']:.0%} flicków to przestrzał).",
                        f"Your main movement usually ends past the target ({w['przestrzal']:.0%} of flicks overshoot)."),
                      t("Zmniejsz czułość zgodnie z zaleceniem. Graj na niej co najmniej 3–4 dni, "
                        "zanim ocenisz - pierwsze dni zawsze są dziwne.",
                        "Lower your sensitivity as recommended. Play on it for at least 3–4 days before "
                        "you judge it - the first days always feel strange.")))
    elif w["zmiana"] > 0 and zrodlo.startswith("flicki"):
        lista.append(("niedociagniecie", t("Nie dociągasz do celu", "You fall short of targets"),
                      t(f"Często zatrzymujesz się przed celem ({w['niedociagniecie']:.0%} flicków) i dociągasz drugim ruchem.",
                        f"You often stop before the target ({w['niedociagniecie']:.0%} of flicks) and finish with a second move."),
                      t("Zwiększ czułość zgodnie z zaleceniem. Sprawdź też, czy mysz nie dojeżdża "
                        "do krawędzi podkładki - to też daje niedociągnięcia.",
                        "Raise your sensitivity as recommended. Also check that the mouse does not reach "
                        "the edge of the mousepad - that causes short flicks too.")))

    klucze_sygnalow = {s["klucz"]: s for s in w.get("sygnaly", [])}
    if "drzenie" in klucze_sygnalow:
        d = klucze_sygnalow["drzenie"]["wartosc"]
        lista.append(("drzenie", t("Celownik drży, gdy trzymasz kąt", "Your crosshair shakes when holding an angle"),
                      t(f"Drobne poruszenia celownika mają ok. {d:.2f}° - to ok. {d / SZEROKOSC_GLOWY_DEG:.0%} "
                        "szerokości głowy przeciwnika z dalszego dystansu.",
                        f"Small crosshair movements are about {d:.2f}° - about {d / SZEROKOSC_GLOWY_DEG:.0%} "
                        "of an enemy head's width at long range."),
                      t("Niższa czułość zmniejszy drżenie. Pomaga też oparcie przedramienia o biurko "
                        "i luźniejszy chwyt.",
                        "A lower sensitivity reduces shaking. Resting your forearm on the desk and a looser "
                        "grip also help.")))
    if "male_za_daleko" in klucze_sygnalow:
        lista.append(("male_za_daleko", t("Małe poprawki lecą za daleko", "Small corrections go too far"),
                      t("Przy małych flickach (3–15°) przestrzeliwujesz wyraźniej niż przy średnich - typowe "
                        "przy za wysokiej czułości.",
                        "On small flicks (3–15°) you overshoot more than on medium ones - typical of a "
                        "sensitivity that is too high."),
                      t("Małe poprawki rób spokojnie, palcami i nadgarstkiem. Jeśli to się utrzymuje, "
                        "obniż czułość.",
                        "Make small corrections calmly, with your fingers and wrist. If it continues, "
                        "lower your sensitivity.")))

    grupy = w.get("grupy", {})
    male, duze = grupy.get("male"), grupy.get("duze")
    if male and duze and duze[0] - male[0] > 0.10 and duze[0] > 1.05:  # at 95 to 105% this is not an overshoot
        lista.append(("duze_za_daleko", t("Duże flicki lecą za daleko", "Large flicks go too far"),
                      t("Małe ruchy masz dokładne, ale przy dużych przestrzeliwujesz.",
                        "Your small movements are accurate, but you overshoot the large ones."),
                      t("Duże obroty rób przedramieniem, nie samym nadgarstkiem, i zwalniaj "
                        "przed celem. Na mapie aim_botz ćwicz flicki między odległymi botami.",
                        "Make large turns with your forearm, not just your wrist, and slow down before "
                        "the target. On aim_botz, practise flicks between distant bots.")))
    elif male and duze and male[0] - duze[0] > 0.10 and duze[0] < 0.85:
        lista.append(("duze_za_krotko", t("Duże flicki są za krótkie", "Large flicks fall short"),
                      t("Małe ruchy są OK, ale duże kończysz przed celem.",
                        "Small movements are fine, but you stop large ones before the target."),
                      t("Często to brak miejsca na podkładce albo za mocno dociśnięta ręka. "
                        "Ustaw podkładkę tak, żeby przy 180° mysz nie dojeżdżała do krawędzi.",
                        "This is often a lack of mousepad space or pressing your hand down too hard. "
                        "Place the pad so the mouse does not reach the edge on a 180° turn.")))

    if w["korekty"] >= 4:  # used to be 1.3, which made it show up in every report
        lista.append(("mikrokorekty", t("Za dużo mikrokorekt", "Too many micro-corrections"),
                      t(f"Po ruchu głównym poprawiasz średnio {w['korekty']:.1f} razy przed strzałem.",
                        f"After the main movement you correct {w['korekty']:.1f} times on average before shooting."),
                      t("Na aim_botz ćwicz wolniej: jeden ruch, jeden strzał, bez poprawiania. "
                        "Najpierw celność, prędkość przyjdzie sama. Rozluźnij chwyt.",
                        "On aim_botz, practise slower: one move, one shot, no corrections. Accuracy first, "
                        "speed will follow. Loosen your grip.")))

    if w["pion"] > 1.5:
        lista.append(("pion", t("Poprawiasz celownik w pionie", "You correct your crosshair vertically"),
                      t(f"Przed strzałem korygujesz średnio {w['pion']:.1f}° w górę/dół.",
                        f"Before shooting you correct {w['pion']:.1f}° up/down on average."),
                      t("To kwestia ustawienia celownika (crosshair placement): trzymaj go cały "
                        "czas na wysokości głowy. Ćwicz na mapach prefire/yprac, chodząc po mapie "
                        "i pilnując wysokości celownika przy rogach.",
                        "This is about crosshair placement: keep it at head height all the time. "
                        "Practise on prefire/Yprac maps, walking the map and keeping your crosshair "
                        "at the right height around corners.")))

    if w["rozmiar"] > 25:
        lista.append(("rozmiar", t("Flicki są bardzo duże", "Your flicks are very large"),
                      t(f"Typowy flick to {w['rozmiar']:.0f}° - przeciwnik zwykle wychodzi daleko od celownika.",
                        f"A typical flick is {w['rozmiar']:.0f}° - enemies usually appear far from your crosshair."),
                      t("Ustawiaj celownik tam, gdzie spodziewasz się przeciwnika (pre-aim rogów). "
                        "Im mniejszy flick, tym łatwiej trafić niezależnie od czułości.",
                        "Place your crosshair where you expect the enemy (pre-aim corners). The smaller "
                        "the flick, the easier the hit, whatever your sensitivity.")))

    if w["boczny"] > 0.15:
        lista.append(("boczny", t("Ruch idzie obok celu", "Your movement passes beside the target"),
                      t("Kierunek ruchu głównego często mija cel bokiem.",
                        "The direction of your main movement often misses the target sideways."),
                      t("Patrz na cel, a nie na celownik. Ćwicz flicki po przekątnej "
                        "(np. na aim_botz) - tam najczęściej ucieka kierunek.",
                        "Look at the target, not the crosshair. Practise diagonal flicks "
                        "(e.g. on aim_botz) - that is where the direction slips most often.")))

    if w["procent_w_ruchu"] >= 0.5:  # used to be 25%
        lista.append(("w_ruchu", t("Strzelasz w trakcie ruchu", "You shoot while moving the crosshair"),
                      t(f"{w['procent_w_ruchu']:.0%} strzałów pada, zanim celownik się zatrzymał.",
                        f"{w['procent_w_ruchu']:.0%} of your shots are fired before the crosshair stops."),
                      t("Przy karabinach strzał w ruchu rzadko trafia. Najpierw zatrzymaj celownik "
                        "na celu, dopiero potem klik. Pomaga też counter-strafe przed strzałem.",
                        "With rifles, shots on the move rarely hit. Stop the crosshair on the target "
                        "first, then click. Counter-strafing before the shot helps too.")))

    if w["czas_korekty"] > 0.25:
        lista.append(("czas_korekty", t("Długo zwlekasz ze strzałem", "You wait too long to shoot"),
                      t(f"Od końca ruchu do strzału mija ok. {w['czas_korekty'] * 1000:.0f} ms.",
                        f"About {w['czas_korekty'] * 1000:.0f} ms pass between the end of the movement and the shot."),
                      t("Ćwicz rytm 'ruch–strzał' na botach w trybie headshot-only. "
                        "Jeśli dużo poprawiasz, zacznij od porady o mikrokorektach.",
                        "Practise a 'move–shoot' rhythm on bots in headshot-only mode. "
                        "If you correct a lot, start with the micro-corrections tip.")))
    return lista


def porady(w):
    """Returns a list of (title, what is happening, how to improve it)."""
    return [p[1:] for p in porady_z_kluczami(w)]


def formatuj(w, sens, dpi, sesje, minuty, ocena_obrazu=None, info=None):
    """Text report (ostatni_raport.txt and export). No user name and no folder paths."""
    info = info or {}
    linie = ["", "=" * 60, t("  SensFit - raport czułości CS2", "  SensFit - CS2 sensitivity report")
             + f"  (v{wersja.NUMER})", "=" * 60,
             t("Ustawienia: ", "Settings: ") + f"sens {sens} | DPI {dpi} | eDPI {edpi(sens, dpi):.0f} | "
             f"{cm_na_360(sens, dpi):.1f} cm/360°",
             "  " + konfiguracja.opis_cs2(),
             t(f"Dane: {sesje} sesji, ok. {minuty:.0f} min gry, {w['liczba']} flicków zakończonych strzałem",
               f"Data: {sesje} sessions, about {minuty:.0f} min played, {w['liczba']} flicks ending in a shot"), ""]
    if ocena_obrazu:
        linie += [t("Obraz:", "Picture:")] + [f"  {l}" for l in rozdzielczosc.opis(ocena_obrazu)] + [""]

    if "r_mediana" not in w:
        linie.append(t("Za mało danych. Zagraj dłużej (najlepiej 20–30 min deathmatchu) i nagraj ponownie.",
                       "Not enough data. Play longer (ideally 20–30 min of deathmatch) and record again."))
        return "\n".join(linie)

    linie += [t("Gdzie kończy się Twój ruch główny (95% = idealnie, 100% = dokładnie na celu):",
                "Where your main movement ends (95% = ideal, 100% = exactly on target):"),
              t(f"  mediana: {w['r_mediana']:.0%}  (niepewność ±{w['niepewnosc']:.0%})",
                f"  median: {w['r_mediana']:.0%}  (uncertainty ±{w['niepewnosc']:.0%})"),
              t(f"  przestrzał: {w['przestrzal']:.0%} | w punkt: {w['w_punkt']:.0%} | "
                f"niedociągnięcie: {w['niedociagniecie']:.0%}",
                f"  overshoot: {w['przestrzal']:.0%} | on target: {w['w_punkt']:.0%} | "
                f"undershoot: {w['niedociagniecie']:.0%}")]
    for klucz, g in w.get("grupy", {}).items():
        linie.append(f"  {linia_grupy(klucz, g)}")
    linie += [""] + [f"  {l}" for l in linie_oceny(w, info)]
    porownanie = linie_porownania(info, sens, w["ocena"], w.get("ocena_pm", 0))
    if porownanie:
        linie += ["", t("Ocena na różnych czułościach (to samo DPI i rozdzielczość):",
                        "Score at different sensitivities (same DPI and resolution):")] + [f"  {l}" for l in porownanie]
    if w.get("sygnaly"):
        linie += ["", t("Sygnały:", "Signals:")] + [f"  - {l}" for l in linie_sygnalow(w, sens)]
    linie.append("")

    if w["nowa_sens"] != sens:
        nowa = w["nowa_sens"]
        linie.append(t(f">>> ZALECENIE: zmień czułość z {sens} na {nowa} ({w['zmiana']:+.0%})",
                       f">>> RECOMMENDATION: change sensitivity from {sens} to {nowa} ({w['zmiana']:+.0%})"))
        linie.append(f"    eDPI {edpi(nowa, dpi):.0f}, {cm_na_360(nowa, dpi):.1f} cm/360°")
        linie.append(t(f"    W konsoli CS2 wpisz: sensitivity {nowa}", f"    In the CS2 console type: sensitivity {nowa}"))
        linie.append(f"    {zrodla().get(w.get('zrodlo'), '')}")
    elif w.get("bez_zmiany"):
        linie.append(">>> " + powod_bez_zmiany(w))
    else:
        linie.append(t(">>> Czułość wygląda dobrze - brak wyraźnego sygnału, żeby ją zmieniać.",
                       ">>> Your sensitivity looks fine - no clear signal to change it."))
    if w["liczba"] < MIN_FLICKOW and w.get("bez_zmiany") != "za_malo":
        linie.append(t(f"    Uwaga: tylko {w['liczba']} flicków (zalecane {MIN_FLICKOW}+) - traktuj zalecenie ostrożnie.",
                       f"    Note: only {w['liczba']} flicks ({MIN_FLICKOW}+ recommended) - treat the recommendation with care."))

    lista = porady(w) + rozdzielczosc.porady(ocena_obrazu, sens)
    if lista:
        linie += ["", t("Co poprawić:", "What to improve:")]
        for i, (tytul, co, jak) in enumerate(lista, 1):
            linie += [f"{i}. {tytul}", t(f"   Co: {co}", f"   What: {co}"), t(f"   Jak: {jak}", f"   How: {jak}")]
    linie += ["", t("Po zmianie czułości zagraj kilka dni i nagraj nową sesję - program sprawdzi, czy jest lepiej.",
                    "After changing your sensitivity, play for a few days and record a new session - "
                    "the app will check whether it is better."), ""]
    return "\n".join(linie)
