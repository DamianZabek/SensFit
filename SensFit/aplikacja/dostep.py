"""Access to SensFit for testers with a role on the Discord server.

How it works:
1. The tester clicks "Log in with Discord". The browser opens the Discord login and Discord sends
   a code to http://127.0.0.1:53682/callback, where this module is waiting for it.
2. The code goes to the access server (a Cloudflare Worker). It checks the role on the Discord
   server and returns a signed ticket (Ed25519), valid for a few days and bound to this computer.
3. On every start the program renews the ticket. Without internet it keeps working while the ticket is valid.

The ticket is checked with the public key set below, so it cannot be forged or moved to another
computer. The network functions block, so they have to be called from a separate thread.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import ed25519
from jezyk import t
import konfiguracja as kfg

# Fill in before building (see WDROZENIE.md)
ADRES_SERWERA = "https://TWOJA-NAZWA.workers.dev"
KLUCZ_PUBLICZNY = "WPISZ-KLUCZ-PUBLICZNY"
# End of the values to fill in

PORT_LOGOWANIA = 53682  # has to match the redirect address in the Discord Developer Portal
PLIK_BILETU = os.path.join(kfg.FOLDER, "bilet.txt")
CZAS_NA_LOGOWANIE_S = 300

STRONA_OK = """<!doctype html><meta charset="utf-8"><title>SensFit</title>
<body style="background:#1a1f26;color:#e7eaee;font-family:Segoe UI,sans-serif;text-align:center;padding-top:80px">
<h2 style="color:#e9a23b">SensFit</h2><p>{tekst}</p><p style="color:#8e99a8">{zamknij}</p></body>"""


# The server answers in Polish. For known error codes the English text is defined here.
KOMUNIKATY_EN = {
    "port": "Wrong port.",
    "kod": "Missing login code.",
    "redirect": "Wrong redirect address.",
    "bilet": "Please log in again.",
    "discord_token": "Discord login failed. Please try again.",
    "brak_serwera": "You are not on the SensFit Discord server.",
    "brak_roli": "You do not have the tester role on the SensFit Discord server.",
    "hw": "Wrong computer code.",
    "limit_komputerow": "This Discord account is already used on the maximum number of computers. "
                        "Ask the SensFit author to free a slot.",
    "serwer": "Server error. Please try again in a moment.",
    "nie_ma": "Not found.",
}


class BladDostepu(Exception):
    """The server refused (no role, computer limit, login required)."""

    def __init__(self, kod, komunikat, komunikat_en=None):
        super().__init__(t(komunikat, komunikat_en or KOMUNIKATY_EN.get(kod) or komunikat))
        self.kod = kod


class BrakPolaczenia(Exception):
    """The access server could not be reached (no internet, outage)."""


def skonfigurowany():
    return "TWOJA-NAZWA" not in ADRES_SERWERA and not KLUCZ_PUBLICZNY.startswith("WPISZ")


# Computer code
def kod_komputera():
    """Stable identifier of this Windows installation (a hash, nothing can be read back from it)."""
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


# Ticket
def _b64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def odczytaj_bilet(bilet, hw=None, teraz=None):
    """Returns the ticket data (uid, name, exp and so on) when the signature, computer and date match, otherwise None."""
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
    if not (dane.get("iat", 0) - 600 <= teraz < dane.get("exp", 0)):  # 10 minutes of tolerance for clock differences
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


# Access server
def _dziennik(tekst):
    """Appends a network error to %APPDATA%\\SensFit\\dostep.log (helps diagnose problems on tester machines)."""
    try:
        os.makedirs(kfg.FOLDER, exist_ok=True)
        with open(os.path.join(kfg.FOLDER, "dostep.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {tekst}\n")
    except OSError:
        pass


def _kontekst_certifi():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception as e:  # certifi missing in the compiled build and similar
        _dziennik(f"certifi niedostępne: {e!r}")
        return None


def _zapytanie(sciezka, dane, timeout=15):
    req = urllib.request.Request(ADRES_SERWERA.rstrip("/") + sciezka, data=json.dumps(dane).encode(),
                                 headers={"content-type": "application/json",
                                          "user-agent": "SensFit"}, method="POST")
    try:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.URLError as e:
            # On some computers Windows has expired or missing root certificates
            # ("certificate has expired"). In that case the certificate is checked against the certifi list.
            # Certificate verification stays on, only the list of trusted authorities changes.
            if not isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
                raise
            _dziennik(f"{sciezka}: certyfikat odrzucony przez Windows, próbuję listy certifi")
            kontekst = _kontekst_certifi()
            if kontekst is None:
                raise
            with urllib.request.urlopen(req, timeout=timeout, context=kontekst) as r:
                return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            _dziennik(f"{sciezka}: HTTP {e.code}")
            raise BrakPolaczenia(t(f"Serwer dostępu ma chwilowy problem (HTTP {e.code}).",
                                   f"The access server has a temporary problem (HTTP {e.code}).")) from e
        try:
            odp = json.loads(e.read())
        except ValueError:
            odp = {}
        raise BladDostepu(odp.get("blad", "nieznany"), odp.get("komunikat") or f"Odmowa dostępu ({e.code}).",
                          None if odp.get("blad") in KOMUNIKATY_EN else f"Access denied ({e.code}).") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        powod = getattr(e, "reason", None) or e
        _dziennik(f"{sciezka}: {type(e).__name__}: {powod!r}")
        raise BrakPolaczenia(t("Brak połączenia z serwerem dostępu", "No connection to the access server")
                             + f" ({type(powod).__name__}: {str(powod)[:140]}).") from e


def _przyjmij(bilet, hw):
    if not odczytaj_bilet(bilet, hw):
        raise BladDostepu("bilet", "Serwer zwrócił nieprawidłowy bilet. Zaktualizuj SensFit.",
                          "The server returned an invalid ticket. Update SensFit.")
    zapisz_bilet(bilet)
    return bilet


def odnow(bilet):
    """New ticket without logging in. BladDostepu means a login is needed or the role is missing."""
    hw = kod_komputera()
    return _przyjmij(_zapytanie("/odnow", {"bilet": bilet, "hw": hw}, timeout=8)["bilet"], hw)


def zaloguj(przerwij=None):
    """Login through the browser. `przerwij` is a function returning True when the user cancelled."""
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
                tekst = t("Nieprawidłowe logowanie. Spróbuj jeszcze raz z poziomu SensFit.",
                          "Invalid login. Try again from SensFit.")
            elif "code" in q:
                wynik["kod"] = q["code"][0]
                tekst = t("Zalogowano. Wróć do SensFit.", "Logged in. Go back to SensFit.")
            else:
                wynik["anulowano"] = True
                tekst = t("Logowanie anulowane.", "Login cancelled.")
            tresc = STRONA_OK.format(tekst=tekst, zamknij=t("Możesz zamknąć tę kartę.", "You can close this tab.")).encode()
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
                                  "i spróbuj ponownie.",
                          f"Port {PORT_LOGOWANIA} is busy. Close other SensFit windows and try again.") from e
    serwer.timeout = 0.5
    adres_zwrotny = f"http://127.0.0.1:{PORT_LOGOWANIA}/callback"
    try:
        webbrowser.open(f"{ADRES_SERWERA.rstrip('/')}/login?port={PORT_LOGOWANIA}&state={stan}")
        koniec = time.monotonic() + CZAS_NA_LOGOWANIE_S
        while not wynik:
            if (przerwij and przerwij()) or time.monotonic() > koniec:
                raise BladDostepu("anulowano", "Logowanie przerwane.", "Login stopped.")
            serwer.handle_request()
    finally:
        serwer.server_close()
    if "kod" not in wynik:
        raise BladDostepu("anulowano", "Logowanie anulowane w Discordzie.", "Login cancelled in Discord.")
    hw = kod_komputera()
    odp = _zapytanie("/bilet", {"code": wynik["kod"], "redirect_uri": adres_zwrotny, "hw": hw})
    return _przyjmij(odp["bilet"], hw)


def sprawdz_przy_starcie():
    """Result on program start: ("ok", data) or ("logowanie", message).

    First tries to renew the ticket. Without internet a valid ticket stored on disk is enough.
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
    return "logowanie", t("Brak internetu, a bilet wygasł. Połącz się z internetem i zaloguj.",
                         "No internet and your ticket has expired. Connect to the internet and log in.")
