import base64
import hashlib
import http.server
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import ed25519
import konfiguracja as kfg

# --- uzupełnij przed zbudowaniem (patrz WDROZENIE.md) -------------------------------
ADRES_SERWERA = "adres"
KLUCZ_PUBLICZNY = "klucz"
# --------------------------------------------------------------------------------------

PORT_LOGOWANIA = 53682  # musi się zgadzać z adresem przekierowania w Discord Developer Portal
PLIK_BILETU = os.path.join(kfg.FOLDER, "bilet.txt")
CZAS_NA_LOGOWANIE_S = 300

STRONA_OK = """<!doctype html><meta charset="utf-8"><title>SensFit</title>
<body style="background:#1a1f26;color:#e7eaee;font-family:Segoe UI,sans-serif;text-align:center;padding-top:80px">
<h2 style="color:#e9a23b">SensFit</h2><p>{tekst}</p><p style="color:#8e99a8">Możesz zamknąć tę kartę.</p></body>"""


class BladDostepu(Exception):
    """Serwer odmówił (brak roli, limit komputerów, trzeba się zalogować…)."""

    def __init__(self, kod, komunikat):
        super().__init__(komunikat)
        self.kod = kod


class BrakPolaczenia(Exception):
    """Nie udało się połączyć z serwerem dostępu (brak internetu, awaria)."""


def skonfigurowany():
    return "TWOJA-NAZWA" not in ADRES_SERWERA and not KLUCZ_PUBLICZNY.startswith("WPISZ")


# ---------------------------------------------------------------- kod komputera
def kod_komputera():
    """Stały identyfikator tego Windowsa (skrót, nie da się z niego nic odczytać)."""
    zrodlo = None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as klucz:
            zrodlo = winreg.QueryValueEx(klucz, "MachineGuid")[0]
    except (ImportError, OSError):
        pass
    if not zrodlo:
        import uuid
        zrodlo = f"mac-{uuid.getnode():012x}"
    return hashlib.sha256(f"sensfit:{zrodlo}".encode()).hexdigest()[:32]


# ---------------------------------------------------------------- bilet
def _b64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def odczytaj_bilet(bilet, hw=None, teraz=None):
    """Zwraca dane biletu (uid, nazwa, exp…), gdy podpis, komputer i data się zgadzają, inaczej None."""
    try:
        tresc, podpis = bilet.strip().split(".")
        if not ed25519.sprawdz(_b64(KLUCZ_PUBLICZNY), tresc.encode("ascii"), _b64(podpis)):
            return None
        dane = json.loads(_b64(tresc))
    except (ValueError, AttributeError, TypeError):
        return None
    teraz = time.time() if teraz is None else teraz
    if dane.get("v") != 1 or dane.get("hw") != (hw or kod_komputera()):
        return None
    if not (dane.get("iat", 0) - 600 <= teraz < dane.get("exp", 0)):  # 10 min zapasu na różnicę zegarów
        return None
    return dane


def wczytaj_bilet():
    try:
        with open(PLIK_BILETU, encoding="ascii") as f:
            return f.read().strip() or None
    except OSError:
        return None


def zapisz_bilet(bilet):
    os.makedirs(kfg.FOLDER, exist_ok=True)
    with open(PLIK_BILETU, "w", encoding="ascii") as f:
        f.write(bilet)


def usun_bilet():
    try:
        os.remove(PLIK_BILETU)
    except OSError:
        pass


# ---------------------------------------------------------------- serwer dostępu
def _zapytanie(sciezka, dane, timeout=15):
    req = urllib.request.Request(ADRES_SERWERA.rstrip("/") + sciezka, data=json.dumps(dane).encode(),
                                 headers={"content-type": "application/json",
                                          "user-agent": "SensFit"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            raise BrakPolaczenia("Serwer dostępu ma chwilowy problem.") from e
        try:
            odp = json.loads(e.read())
        except ValueError:
            odp = {}
        raise BladDostepu(odp.get("blad", "nieznany"), odp.get("komunikat") or f"Odmowa dostępu ({e.code}).") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise BrakPolaczenia("Brak połączenia z serwerem dostępu.") from e


def _przyjmij(bilet, hw):
    if not odczytaj_bilet(bilet, hw):
        raise BladDostepu("bilet", "Serwer zwrócił nieprawidłowy bilet. Zaktualizuj SensFit.")
    zapisz_bilet(bilet)
    return bilet


def odnow(bilet):
    """Nowy bilet bez logowania. BladDostepu = trzeba się zalogować / brak roli."""
    hw = kod_komputera()
    return _przyjmij(_zapytanie("/odnow", {"bilet": bilet, "hw": hw}, timeout=8)["bilet"], hw)


def zaloguj(przerwij=None):
    """Logowanie przez przeglądarkę. `przerwij` – funkcja zwracająca True, gdy użytkownik anulował."""
    stan = secrets.token_urlsafe(16)
    wynik = {}

    class Odbior(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            q = urllib.parse.parse_qs(url.query)
            if q.get("state", [""])[0] != stan:
                tekst = "Nieprawidłowe logowanie. Spróbuj jeszcze raz z poziomu SensFit."
            elif "code" in q:
                wynik["kod"] = q["code"][0]
                tekst = "Zalogowano. Wróć do SensFit."
            else:
                wynik["anulowano"] = True
                tekst = "Logowanie anulowane."
            tresc = STRONA_OK.format(tekst=tekst).encode()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(tresc)))
            self.end_headers()
            self.wfile.write(tresc)

        def log_message(self, *a):
            pass

    try:
        serwer = http.server.HTTPServer(("127.0.0.1", PORT_LOGOWANIA), Odbior)
    except OSError as e:
        raise BladDostepu("port", f"Port {PORT_LOGOWANIA} jest zajęty. Zamknij inne okna SensFit "
                                  "i spróbuj ponownie.") from e
    serwer.timeout = 0.5
    adres_zwrotny = f"http://127.0.0.1:{PORT_LOGOWANIA}/callback"
    try:
        webbrowser.open(f"{ADRES_SERWERA.rstrip('/')}/login?port={PORT_LOGOWANIA}&state={stan}")
        koniec = time.monotonic() + CZAS_NA_LOGOWANIE_S
        while not wynik:
            if (przerwij and przerwij()) or time.monotonic() > koniec:
                raise BladDostepu("anulowano", "Logowanie przerwane.")
            serwer.handle_request()
    finally:
        serwer.server_close()
    if "kod" not in wynik:
        raise BladDostepu("anulowano", "Logowanie anulowane w Discordzie.")
    hw = kod_komputera()
    odp = _zapytanie("/bilet", {"code": wynik["kod"], "redirect_uri": adres_zwrotny, "hw": hw})
    return _przyjmij(odp["bilet"], hw)


def sprawdz_przy_starcie():
    """Wynik przy starcie programu: ("ok", dane) | ("logowanie", komunikat).

    Najpierw próbuje odnowić bilet. Bez internetu wystarczy ważny bilet zapisany na dysku.
    """
    bilet = wczytaj_bilet()
    if not bilet:
        return "logowanie", ""
    try:
        bilet = odnow(bilet)
    except BladDostepu as e:
        usun_bilet()
        return "logowanie", "" if e.kod == "bilet" else str(e)
    except BrakPolaczenia:
        pass
    dane = odczytaj_bilet(bilet)
    if dane:
        return "ok", dane
    return "logowanie", "Brak internetu, a bilet wygasł. Połącz się z internetem i zaloguj."
