# SensFit

English | [Polski](README.pl.md)

SensFit is a Windows program that uses your real mouse movement in CS2 to suggest whether to change your sensitivity. Version 0.9.6 (test).

**The code is published for inspection only** (see [LICENSE](LICENSE)), so anyone can check what the program does with data. It cannot be run from this repository.

## What the program does
- Receives a copy of mouse input from Windows (Raw Input) and the game state from Valve's official Game State Integration. It does not touch the CS2 process or its memory.
- Analyses aiming movements on your computer and stores sessions in `%APPDATA%\SensFit`.
- Does not send mouse movement, sessions or results anywhere. There is no telemetry.
- An optional start/stop hotkey (F10 by default) uses Windows `RegisterHotKey` and does not read any other keys (`aplikacja/skrot.py`).

## Internet connections
Only two modules connect to the internet, both over HTTPS:
- `aplikacja/dostep.py` handles the Discord login and renewal of the access ticket (the access server is described below).
- `aplikacja/aktualizacja.py` downloads a small `wersja.json` from `aktualizacje.sensfit.pl` on start (it sends only the program name and version number). A new installer is downloaded only after "Download and install" is clicked, only from that address, and it is verified with a SHA-256 sum and an Ed25519 signature.

Besides that, the program opens links in the browser (the Discord invite, training maps from the Steam Workshop) only when they are clicked.

## Login and data
Access is limited to testers who hold a role on a Discord server. The Discord login asks only for the `identify` and `guilds.members.read` scopes. The access server (`serwer/src/index.js`, a Cloudflare Worker) stores the Discord ID and name, the Discord tokens and a hash of the computer identifier (limit of 2 computers). It stores nothing about aiming.

## Where to look
| File | Purpose |
| --- | --- |
| `aplikacja/dostep.py` | login and access ticket |
| `aplikacja/aktualizacja.py` | update check and installation |
| `aplikacja/ed25519.py` | signature verification (ticket, update) |
| `aplikacja/mysz_windows.py` | mouse input reading |
| `aplikacja/gsi.py` | receiving game state from CS2 (local only, 127.0.0.1) |
| `aplikacja/analiza.py` | flick detection and recommendation |
| `aplikacja/narzedzia/` | author tools (version signing, comparing recommendations) |
| `serwer/src/index.js` | access server |

Names in the code are mostly Polish. Addresses, keys and IDs were replaced with placeholder values.

## Contact
Questions about security and privacy: the SensFit Discord server (https://discord.gg/g56qwVZAsh).
