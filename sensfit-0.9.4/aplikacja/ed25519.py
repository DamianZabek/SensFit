import hashlib

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _odzyskaj_x(y, znak):
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P)
    if x2 == 0:
        return None if znak else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    if (x & 1) != znak:
        x = P - x
    return x


_GY = 4 * pow(5, P - 2, P) % P
_GX = _odzyskaj_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)
ZERO = (0, 1, 1, 0)


def _dodaj(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % P
    B = (a[1] + a[0]) * (b[1] + b[0]) % P
    C = 2 * a[3] * b[3] * D % P
    Dd = 2 * a[2] * b[2] % P
    E, F, Gg, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % P, Gg * H % P, F * Gg % P, E * H % P)


def _razy(s, pkt):
    wynik = ZERO
    while s > 0:
        if s & 1:
            wynik = _dodaj(wynik, pkt)
        pkt = _dodaj(pkt, pkt)
        s >>= 1
    return wynik


def _rowne(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _zakoduj(pkt):
    zinv = pow(pkt[2], P - 2, P)
    x, y = pkt[0] * zinv % P, pkt[1] * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _odkoduj(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    znak = y >> 255
    y &= (1 << 255) - 1
    x = _odzyskaj_x(y, znak)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def _h(m):
    return int.from_bytes(hashlib.sha512(m).digest(), "little")


def klucz_publiczny(ziarno):
    """32-bajtowe ziarno (klucz prywatny) -> 32-bajtowy klucz publiczny. Używa tylko klucze.py."""
    h = hashlib.sha512(ziarno).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return _zakoduj(_razy(a, G))


def podpisz(ziarno, wiadomosc):
    """Podpis Ed25519 – tylko do testów; prawdziwe bilety podpisuje serwer."""
    h = hashlib.sha512(ziarno).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    pub = _zakoduj(_razy(a, G))
    r = _h(h[32:] + wiadomosc) % L
    R = _zakoduj(_razy(r, G))
    s = (r + _h(R + pub + wiadomosc) * a) % L
    return R + int.to_bytes(s, 32, "little")


def sprawdz(publiczny, wiadomosc, podpis):
    """True, gdy podpis pasuje do wiadomości i klucza publicznego."""
    if len(publiczny) != 32 or len(podpis) != 64:
        return False
    A = _odkoduj(publiczny)
    R = _odkoduj(podpis[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(podpis[32:], "little")
    if s >= L:
        return False
    k = _h(podpis[:32] + publiczny + wiadomosc) % L
    return _rowne(_razy(s, G), _dodaj(R, _razy(k, A)))
