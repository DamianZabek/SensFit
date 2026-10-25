import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 3000
# Bronie, przy których ruch nie mówi nic o czułości (snajperki mają inną czułość w lunecie)
POMIJANE_BRONIE = {"Knife", "Grenade", "C4", "SniperRifle", "Taser"}


class StanGry:
    def __init__(self):
        self.ostatnia_wiadomosc = float("-inf")
        self.aktywny = False
        self.powod = "brak danych z CS2 - czy plik GSI jest zainstalowany?"
        self.zabojstwa = []        # czasy zabójstw (time.perf_counter, jak w mysz_windows.py)
        self._zabojstwa_w_rundzie = None

    def aktualizuj(self, dane):
        self.ostatnia_wiadomosc = time.monotonic()
        gracz = dane.get("player", {})
        ja = dane.get("provider", {}).get("steamid")

        if gracz.get("steamid") == ja:
            self.licz_zabojstwa(gracz.get("state", {}).get("round_kills"))

        if gracz.get("steamid") != ja:
            self.ustaw(False, "nie żyjesz / obserwujesz innego gracza")
        elif gracz.get("activity") != "playing":
            self.ustaw(False, f"jesteś w: {gracz.get('activity', '?')}")
        elif gracz.get("state", {}).get("health", 0) <= 0:
            self.ustaw(False, "nie żyjesz")
        else:
            bron = aktywna_bron(gracz)
            if bron in POMIJANE_BRONIE:
                self.ustaw(False, f"broń pomijana ({bron})")
            else:
                self.ustaw(True, f"grasz ({bron or 'broń ?'})")

    def licz_zabojstwa(self, w_rundzie):
        """round_kills rośnie przy każdym zabójstwie i zeruje się w nowej rundzie."""
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
        # Jeśli CS2 milczy > 30 s (gra zamknięta), przestajemy nagrywać
        return self.aktywny and time.monotonic() - self.ostatnia_wiadomosc < 30


def aktywna_bron(gracz):
    for bron in gracz.get("weapons", {}).values():
        if bron.get("state") == "active":
            return bron.get("type")
    return None


def uruchom_serwer(stan):
    """Startuje mały serwer HTTP, który odbiera dane z CS2."""

    class Odbiornik(BaseHTTPRequestHandler):
        def do_POST(self):
            dlugosc = int(self.headers.get("Content-Length", 0))
            try:
                stan.aktualizuj(json.loads(self.rfile.read(dlugosc)))
            except ValueError:
                pass
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):  # bez spamu w konsoli
            pass

    serwer = ThreadingHTTPServer(("127.0.0.1", PORT), Odbiornik)
    threading.Thread(target=serwer.serve_forever, daemon=True).start()
    return serwer
