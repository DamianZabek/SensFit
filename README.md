# SensFit

SensFit to program na Windows, który na podstawie Twojego prawdziwego ruchu myszy w CS2 podpowiada, czy zmienić czułość. Wersja 0.9.4 (test).

**Kod jest udostępniony tylko do wglądu** (patrz [LICENSE](LICENSE)), żeby każdy mógł sprawdzić, co program robi z danymi. Nie da się go uruchomić z tego repozytorium.

## Co program robi
- Odbiera kopię ruchu myszy z Windows (Raw Input) i stan gry z oficjalnej funkcji Valve (Game State Integration). Nie dotyka procesu CS2 ani jego pamięci.
- Analizuje ruchy celowania na Twoim komputerze i zapisuje sesje w `%APPDATA%\SensFit`.
- Nie wysyła ruchu myszy, sesji ani wyników. Nie ma telemetrii.

## Logowanie i dane
Dostęp mają testerzy z rolą na serwerze Discord. Logowanie przez Discord prosi tylko o `identify` i `guilds.members.read`. Serwer dostępu (`serwer/src/index.js`, Cloudflare Worker) przechowuje ID i nazwę Discord, tokeny Discord oraz skrót identyfikatora komputera. Nic o celowaniu.

## Gdzie szukać czego
| Plik | Co robi |
| --- | --- |
| `aplikacja/dostep.py` | logowanie i bilet dostępu, jedyny plik łączący się z internetem |
| `aplikacja/ed25519.py` | sprawdzanie podpisu biletu |
| `aplikacja/mysz_windows.py` | odczyt ruchu myszy |
| `aplikacja/gsi.py` | odbiór stanu gry z CS2 (tylko lokalnie, 127.0.0.1) |
| `aplikacja/analiza.py` | wykrywanie flicków i wyliczanie zalecenia |
| `serwer/src/index.js` | serwer dostępu |

Adresy, klucze i ID zostały zastąpione wartościami zastępczymi.

## Kontakt
Pytania o bezpieczeństwo i prywatność: serwer Discord SensFit (https://discord.gg/g56qwVZAsh).
