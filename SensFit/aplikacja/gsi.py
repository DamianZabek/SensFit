"""Game State Integration (GSI), an official Valve feature.

CS2 itself sends the game state (menu or match, alive or dead, current weapon) to the local
address http://127.0.0.1:3000. This way mouse movement is only recorded while the player is
actually aiming, and not while clicking through menus or the buy menu.

Kill moments (an increase of round_kills) are stored too, so the analysis knows which flicks
really hit. Time is measured with the same clock as the mouse movement.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jezyk import t

PORT = 3000
# Weapons for which movement says nothing about sensitivity (sniper rifles use a different scoped sensitivity)
POMIJANE_BRONIE = {"Knife", "Grenade", "C4", "SniperRifle", "Taser"}


class StanGry:
    def __init__(self):
        self.ostatnia_wiadomosc = float("-inf")
        self.aktywny = False
        self.powod = t("brak danych z CS2 - czy plik GSI jest zainstalowany?",
                       "no data from CS2 - is the GSI file installed?")
        self.zabojstwa = []        # kill times (time.perf_counter, same clock as in mysz_windows.py)
        self._zabojstwa_w_rundzie = None

    def aktualizuj(self, dane):
        self.ostatnia_wiadomosc = time.monotonic()
        gracz = dane.get("player", {})
        ja = dane.get("provider", {}).get("steamid")

        if gracz.get("steamid") == ja:
            self.licz_zabojstwa(gracz.get("state", {}).get("round_kills"))

        if gracz.get("steamid") != ja:
            self.ustaw(False, t("nie żyjesz / obserwujesz innego gracza", "dead / spectating another player"))
        elif gracz.get("activity") != "playing":
            self.ustaw(False, t("jesteś w: ", "you are in: ") + str(gracz.get('activity', '?')))
        elif gracz.get("state", {}).get("health", 0) <= 0:
            self.ustaw(False, t("nie żyjesz", "dead"))
        else:
            bron = aktywna_bron(gracz)
            if bron in POMIJANE_BRONIE:
                self.ustaw(False, t(f"broń pomijana ({bron})", f"weapon ignored ({bron})"))
            else:
                self.ustaw(True, t(f"grasz ({bron or 'broń ?'})", f"playing ({bron or 'weapon ?'})"))

    def licz_zabojstwa(self, w_rundzie):
        """round_kills grows with every kill and resets in a new round."""
        if w_rundzie is None:
            return
        teraz = time.perf_counter()
        if self._zabojstwa_w_rundzie is not None and w_rundzie > self._zabojstwa_w_rundzie:
            self.zabojstwa += [teraz] * (w_rundzie - self._zabojstwa_w_rundzie)
        self._zabojstwa_w_rundzie = w_rundzie

    def ustaw(self, aktywny, powod):
        self.aktywny = aktywny
        self.powod = powod

    def czy_nagrywac(self):
        # If CS2 is silent for more than 30 s (game closed), recording stops
        return self.aktywny and time.monotonic() - self.ostatnia_wiadomosc < 30


def aktywna_bron(gracz):
    for bron in gracz.get("weapons", {}).values():
        if bron.get("state") == "active":
            return bron.get("type")
    return None


def uruchom_serwer(stan):
    """Starts a small HTTP server that receives data from CS2."""

    class Odbiornik(BaseHTTPRequestHandler):
        def do_POST(self):
            dlugosc = int(self.headers.get("Content-Length", 0))
            try:
                stan.aktualizuj(json.loads(self.rfile.read(dlugosc)))
            except ValueError:
                pass
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):  # no console spam
            pass

    serwer = ThreadingHTTPServer(("127.0.0.1", PORT), Odbiornik)
    threading.Thread(target=serwer.serve_forever, daemon=True).start()
    return serwer
