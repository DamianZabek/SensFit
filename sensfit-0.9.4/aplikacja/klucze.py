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
