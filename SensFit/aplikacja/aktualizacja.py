"""Checks for a new SensFit version and installs it.

1. On start the program downloads wersja.json from the update server (https://aktualizacje.sensfit.pl).
2. If a newer version is listed there, the window shows a banner and an "Update" button with the list of changes.
3. Only after "Download and install" is clicked, the installer is downloaded from the same server,
   its SHA-256 sum is compared with the one in wersja.json and, after confirmation, it is started
   while SensFit closes.

Nothing is downloaded or installed without the user's consent. The installer may only come from
aktualizacje.sensfit.pl, and a file with a different SHA-256 sum is deleted immediately.
The network functions block, so they have to be called from a separate thread.
"""
import base64
import hashlib
import json
import os
import re
import ssl
import tempfile
import urllib.error
import urllib.request

import dostep
import ed25519
import wersja
import jezyk
from jezyk import t

DISCORD = "https://discord.gg/g56qwVZAsh"  # manual download for when updating inside the program is not possible
ADRES_MANIFESTU = "https://aktualizacje.sensfit.pl/wersja.json"
DOZWOLONY_POCZATEK = "https://aktualizacje.sensfit.pl/pliki/"
MAKS_ROZMIAR = 300 * 1024 * 1024  # the installer is a few dozen MB, this is only a safety limit
# Public key for the wersja.json signature. It is created by narzedzia/podpisz_wersje.py on the
# publisher's machine. The private key never reaches the program or the server. build.bat refuses
# to build while the value is still WSTAW_KLUCZ.
KLUCZ_WERSJI = "WSTAW_KLUCZ"


class BladAktualizacji(Exception):
    pass


def numer(tekst):
    """Turns '0.9.5' into (0, 9, 5). Parts that are not numbers (for example ' (test)') are ignored."""
    czesci = re.findall(r"\d+", str(tekst or "").split(" ")[0])
    return tuple(int(c) for c in czesci) or (0,)


def _otworz(adres, timeout):
    req = urllib.request.Request(adres, headers={"user-agent": f"SensFit/{wersja.NUMER}",
                                                 "cache-control": "no-cache"})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        # Same as in dostep.py: when Windows has expired root certificates, the certifi list is used
        if not isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            raise
        kontekst = dostep._kontekst_certifi()
        if kontekst is None:
            raise
        return urllib.request.urlopen(req, timeout=timeout, context=kontekst)


def tresc_do_podpisu(dane):
    """Bytes that get signed: the whole wersja.json without the podpis field, in a fixed form."""
    bez = {k: v for k, v in dane.items() if k != "podpis"}
    return json.dumps(bez, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def podpis_poprawny(dane, klucz=None):
    """True if the podpis field matches the content and the publisher key."""
    klucz = klucz or KLUCZ_WERSJI
    try:
        publiczny = base64.urlsafe_b64decode(klucz + "=" * (-len(klucz) % 4))
        podpis = base64.urlsafe_b64decode(str(dane.get("podpis") or "") + "=" * (-len(str(dane.get("podpis") or "")) % 4))
    except (ValueError, TypeError):
        return False
    return ed25519.sprawdz(publiczny, tresc_do_podpisu(dane), podpis)


def sprawdz(timeout=8):
    """Returns a dict describing the newer version, or None when the installed one is the latest.

    Raises BladAktualizacji when wersja.json cannot be downloaded or read.
    Keys: wersja, zmiany (list of points in the current language), url, sha256,
    gotowa (download is possible: valid address and sum), reczna (the installed version
    is too old to update from inside the program).
    """
    try:
        with _otworz(ADRES_MANIFESTU, timeout) as r:
            dane = json.loads(r.read(64 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as e:
        dostep._dziennik(f"aktualizacja: HTTP {e.code}")
        raise BladAktualizacji(t(f"Serwer aktualizacji odpowiedział błędem (HTTP {e.code}).",
                                 f"The update server returned an error (HTTP {e.code}).")) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        dostep._dziennik(f"aktualizacja: {type(e).__name__}: {e!r}")
        raise BladAktualizacji(t("Brak połączenia z serwerem aktualizacji.",
                                 "No connection to the update server.")) from e
    if not isinstance(dane, dict) or not dane.get("wersja"):
        raise BladAktualizacji(t("Plik wersja.json jest nieprawidłowy.", "The wersja.json file is invalid."))

    if numer(dane["wersja"]) <= numer(wersja.NUMER):
        return None
    # Nothing is installed without a valid signature, so even a hijacked server cannot swap the installer
    podpisany = KLUCZ_WERSJI == "WSTAW_KLUCZ" or podpis_poprawny(dane)  # WSTAW_KLUCZ means the program runs from source
    if not podpisany:
        dostep._dziennik("aktualizacja: zly podpis wersja.json")
    url = str(dane.get("instalator_url") or "")
    sha = str(dane.get("sha256") or "").strip().lower()
    zmiany = dane.get("zmiany_" + jezyk.JEZYK) or dane.get("zmiany_en") or dane.get("zmiany_pl")
    if not isinstance(zmiany, list) or not zmiany:
        zmiany = [z.strip(" -•*") for z in str(dane.get("opis") or "").splitlines() if z.strip(" -•*")]
    return {
        "wersja": str(dane["wersja"]),
        "zmiany": [str(z) for z in zmiany][:20],
        "url": url,
        "sha256": sha,
        "gotowa": podpisany and url.startswith(DOZWOLONY_POCZATEK) and url.endswith(".exe")
                  and bool(re.fullmatch(r"[0-9a-f]{64}", sha)),
        "reczna": numer(wersja.NUMER) < numer(dane.get("min_wersja") or "0"),
        # The "Download manually" target: a direct link to the installer, or Discord when there is no address
        "strona": url if podpisany and url.startswith(DOZWOLONY_POCZATEK) else DISCORD,
    }


def pobierz(info, postep=None, przerwij=None, timeout=20):
    """Downloads the installer to a temporary folder and checks its SHA-256. Returns the file path.

    postep(downloaded_bytes, size_or_None) is called for every chunk; przerwij() returning True stops the download.
    """
    if not info.get("gotowa"):
        raise BladAktualizacji(t("Ta wersja nie ma jeszcze kompletnych danych do pobrania (adres lub suma SHA-256).",
                                 "This version does not have complete download data yet (address or SHA-256)."))
    folder = os.path.join(tempfile.gettempdir(), "SensFit_aktualizacja")
    os.makedirs(folder, exist_ok=True)
    plik = os.path.join(folder, os.path.basename(info["url"]))
    skrot = hashlib.sha256()
    pobrane = 0
    try:
        with _otworz(info["url"], timeout) as r, open(plik, "wb") as f:
            rozmiar = int(r.headers.get("Content-Length") or 0) or None
            while True:
                if przerwij and przerwij():
                    raise BladAktualizacji(t("Pobieranie przerwane.", "Download cancelled."))
                kawalek = r.read(256 * 1024)
                if not kawalek:
                    break
                pobrane += len(kawalek)
                if pobrane > MAKS_ROZMIAR:
                    raise BladAktualizacji(t("Plik jest za duży.", "The file is too large."))
                skrot.update(kawalek)
                f.write(kawalek)
                if postep:
                    postep(pobrane, rozmiar)
    except BladAktualizacji:
        _usun(plik)
        raise
    except (urllib.error.URLError, OSError) as e:
        _usun(plik)
        dostep._dziennik(f"aktualizacja pobieranie: {type(e).__name__}: {e!r}")
        kod = f" (HTTP {e.code})" if isinstance(e, urllib.error.HTTPError) else ""
        raise BladAktualizacji(t("Nie udało się pobrać instalatora", "Could not download the installer") + kod + ".") from e
    if skrot.hexdigest() != info["sha256"]:
        _usun(plik)
        raise BladAktualizacji(t("Suma SHA-256 pobranego pliku nie zgadza się z wersja.json. Plik usunięto - "
                                 "nie instaluj go. Napisz na Discordzie SensFit.",
                                 "The SHA-256 hash of the downloaded file does not match wersja.json. The file was "
                                 "deleted - do not install it. Let us know on the SensFit Discord."))
    return plik


def uruchom_instalator(plik):
    """Starts the installer (Windows asks for administrator rights). The program is expected to close afterwards."""
    try:
        os.startfile(plik)  # ShellExecute shows the UAC prompt when the installer needs it
    except AttributeError as e:  # not on Windows
        raise BladAktualizacji(t("Instalator działa tylko w Windows.", "The installer only runs on Windows.")) from e
    except OSError as e:
        raise BladAktualizacji(t(f"Nie udało się uruchomić instalatora: {e}", f"Could not run the installer: {e}")) from e


def _usun(plik):
    try:
        os.remove(plik)
    except OSError:
        pass
