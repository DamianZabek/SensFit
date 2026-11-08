"""Creates the key pair for signing SensFit access tickets. Run ONCE: py -3.12 klucze.py

- KLUCZ_PUBLICZNY goes into dostep.py (it is built into the program and may be public).
- KLUCZ_PRYWATNY is set as the server secret: npx wrangler secret put KLUCZ_PRYWATNY
  It must never be shown or stored in the program folder. Whoever has it can issue tickets.

This file is not part of the tester build (build.bat compiles only sensfit_gui.py and what it imports).
"""
import base64
import json
import os

import ed25519


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


ziarno = os.urandom(32)
publiczny = ed25519.klucz_publiczny(ziarno)
print("KLUCZ_PUBLICZNY (do dostep.py):")
print(b64(publiczny))
print()
print("KLUCZ_PRYWATNY (sekret serwera, skopiuj całą linię):")
print(json.dumps({"kty": "OKP", "crv": "Ed25519", "d": b64(ziarno), "x": b64(publiczny)}, separators=(",", ":")))
