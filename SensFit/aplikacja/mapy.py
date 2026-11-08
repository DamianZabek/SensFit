"""Recommended training maps from the Steam workshop, matched to the advice in the report.

The list is maintained by hand. Every map has advice keys (raport.porady_z_kluczami and
rozdzielczosc.porady) that it fits. The "Training maps" tab shows next to each map which
findings from the report it practises.
"""
from jezyk import t

ADRES = "https://steamcommunity.com/sharedfiles/filedetails/?id={}"


def lista():
    """List of dicts: id, nazwa, opis, klucze (the advice the map fits)."""
    return [
        {"id": "3070244462", "nazwa": "Aim Botz",
         "opis": t("Boty dookoła, opcjonalnie ruchome i z nieskończoną amunicją. Dobra na mikrokorekty i duże flicki.",
                   "Bots all around you, optionally moving and with unlimited ammo. Good for micro-corrections "
                   "and large flicks."),
         "klucze": {"mikrokorekty", "duze_za_daleko", "duze_za_krotko", "przestrzal", "niedociagniecie",
                    "male_za_daleko", "boczny", "drzenie"}},
        {"id": "3070715607", "nazwa": "Yprac Hub",
         "opis": t("Dodatek do treningu celowania, prefire, granatów i skrótów. Ćwiczy m.in. wysokość celownika.",
                   "Add-on for aim, prefire, utility and shortcut practice. Trains crosshair height, among other things."),
         "klucze": {"pion", "rozmiar"}},
        {"id": "3100869952", "nazwa": "Recoil Master",
         "opis": t("Nauka wzorów odrzutu broni, także strzelanie w ruchu.",
                   "Learn weapon spray patterns, including shooting on the move."),
         "klucze": {"w_ruchu"}},
        {"id": "3198285208", "nazwa": "Aim_Headshot",
         "opis": t("Mapa do ćwiczenia strzałów w głowę, także przeciwko botom.",
                   "A map for headshot practice, also against bots."),
         "klucze": {"czas_korekty"}},
    ]


def adres(mapa):
    return ADRES.format(mapa["id"])


def dopasuj(klucze_porad):
    """Maps with the list of advice titles they fit: a list of (map, [titles]).

    klucze_porad is a list of (key, title) from the current report.
    """
    wynik = []
    for mapa in lista():
        tytuly = [tytul for klucz, tytul in klucze_porad if klucz in mapa["klucze"]]
        wynik.append((mapa, tytuly))
    return wynik


def czy_jest_mapa(klucz):
    return any(klucz in m["klucze"] for m in lista())
