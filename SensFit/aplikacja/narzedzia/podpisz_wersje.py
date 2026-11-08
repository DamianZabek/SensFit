"""Signs wersja.json. Run it ONLY on the publisher's own computer.

  py -3.12 narzedzia\\podpisz_wersje.py nowy-klucz
      Once: creates the private key in %USERPROFILE%\\.sensfit\\klucz_wersji.json and prints the public key.
      The public key goes into aktualizacja.py (KLUCZ_WERSJI = "..."), then the program is built.

  py -3.12 narzedzia\\podpisz_wersje.py podpisz wersja.json [SensFit_X_instalator.exe]
      For every release: writes the SHA-256 sum of the installer (when a file is given) and adds the "podpis" field.
      After signing, wersja.json must not be changed, because every change invalidates the signature.

The private key must not be sent to anyone, uploaded to a server, a repository or a chat.
Keep a backup (for example on a USB stick): without it new versions will not install from the program.
"""
import base64
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import aktualizacja  # noqa: E402
import ed25519  # noqa: E402

PLIK_KLUCZA = os.path.join(os.path.expanduser("~"), ".sensfit", "klucz_wersji.json")


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def nowy_klucz():
    if os.path.exists(PLIK_KLUCZA):
        sys.exit(f"Klucz już istnieje: {PLIK_KLUCZA}\nNie nadpisuję - stary klucz jest wbudowany w wydane wersje.")
    ziarno = os.urandom(32)
    os.makedirs(os.path.dirname(PLIK_KLUCZA), exist_ok=True)
    with open(PLIK_KLUCZA, "w", encoding="utf-8") as f:
        json.dump({"ziarno": b64(ziarno)}, f)
    print(f"Klucz prywatny zapisany: {PLIK_KLUCZA}  (zrób kopię, nikomu nie pokazuj)")
    print("Klucz publiczny - wklej do aktualizacja.py jako KLUCZ_WERSJI:")
    print(b64(ed25519.klucz_publiczny(ziarno)))


def podpisz(plik_json, instalator=None):
    with open(PLIK_KLUCZA, encoding="utf-8") as f:
        z = json.load(f)["ziarno"]
    ziarno = base64.urlsafe_b64decode(z + "=" * (-len(z) % 4))
    with open(plik_json, encoding="utf-8-sig") as f:
        dane = json.load(f)
    if instalator:
        with open(instalator, "rb") as f:
            dane["sha256"] = hashlib.sha256(f.read()).hexdigest()
    dane["podpis"] = b64(ed25519.podpisz(ziarno, aktualizacja.tresc_do_podpisu(dane)))
    publiczny = b64(ed25519.klucz_publiczny(ziarno))
    if not aktualizacja.podpis_poprawny(dane, publiczny):
        sys.exit("Podpis się nie sprawdza - nic nie zapisano.")
    if aktualizacja.KLUCZ_WERSJI != publiczny:
        print("UWAGA: KLUCZ_WERSJI w aktualizacja.py jest inny niż Twój klucz - program odrzuci ten podpis.")
    with open(plik_json, "w", encoding="utf-8") as f:
        json.dump(dane, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Podpisano {plik_json} (wersja {dane.get('wersja')}, sha256 {dane.get('sha256')})")


if __name__ == "__main__":
    if sys.argv[1:2] == ["nowy-klucz"]:
        nowy_klucz()
    elif sys.argv[1:2] == ["podpisz"] and len(sys.argv) in (3, 4):
        podpisz(*sys.argv[2:])
    else:
        print(__doc__)
