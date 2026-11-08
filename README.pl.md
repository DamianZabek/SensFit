# SensFit

[English](README.md) | Polski

SensFit to program na Windows, który na podstawie Twojego prawdziwego ruchu myszy w CS2 podpowiada, czy zmienić czułość. Wersja 0.9.6 (test).

**Kod jest udostępniony tylko do wglądu** (patrz [LICENSE](LICENSE)), żeby każdy mógł sprawdzić, co program robi z danymi. Nie da się go uruchomić z tego repozytorium.

## Co program robi
- Odbiera kopię ruchu myszy z Windows (Raw Input) i stan gry z oficjalnej funkcji Valve (Game State Integration). Nie dotyka procesu CS2 ani jego pamięci.
- Analizuje ruchy celowania na Twoim komputerze i zapisuje sesje w `%APPDATA%\SensFit`.
- Nie wysyła ruchu myszy, sesji ani wyników. Nie ma telemetrii.
- Opcjonalny skrót klawiszowy start/stop (domyślnie F10) działa przez `RegisterHotKey` z Windows i nie czyta innych klawiszy (`aplikacja/skrot.py`).

## Połączenia z internetem
Tylko dwa moduły, oba tylko przez HTTPS:
- `aplikacja/dostep.py` – logowanie przez Discord i odnawianie biletu dostępu (serwer dostępu, patrz niżej).
- `aplikacja/aktualizacja.py` – przy starcie pobiera mały plik `wersja.json` z `aktualizacje.sensfit.pl` (wysyła tylko nazwę i numer wersji programu). Nowy instalator pobiera się dopiero po kliknięciu „Pobierz i zainstaluj”, tylko z tego adresu, i jest sprawdzany sumą SHA-256 oraz podpisem Ed25519.

Poza tym program otwiera w przeglądarce linki (zaproszenie na Discord, mapy treningowe ze Steam Workshop) tylko po kliknięciu.

## Logowanie i dane
Dostęp mają testerzy z rolą na serwerze Discord. Logowanie przez Discord prosi tylko o `identify` i `guilds.members.read`. Serwer dostępu (`serwer/src/index.js`, Cloudflare Worker) przechowuje ID i nazwę Discord, tokeny Discord oraz skrót identyfikatora komputera (limit 2 komputerów). Nic o celowaniu.

## Gdzie szukać czego
| Plik | Co robi |
| --- | --- |
| `aplikacja/dostep.py` | logowanie i bilet dostępu |
| `aplikacja/aktualizacja.py` | sprawdzanie i instalacja aktualizacji |
| `aplikacja/ed25519.py` | sprawdzanie podpisów (bilet, aktualizacja) |
| `aplikacja/mysz_windows.py` | odczyt ruchu myszy |
| `aplikacja/gsi.py` | odbiór stanu gry z CS2 (tylko lokalnie, 127.0.0.1) |
| `aplikacja/analiza.py` | wykrywanie flicków i wyliczanie zalecenia |
| `aplikacja/narzedzia/` | narzędzia autora (podpisywanie wersji, porównywanie zaleceń) |
| `serwer/src/index.js` | serwer dostępu |

Adresy, klucze i ID zostały zastąpione wartościami zastępczymi.

## Kontakt
Pytania o bezpieczeństwo i prywatność: serwer Discord SensFit (https://discord.gg/g56qwVZAsh).
