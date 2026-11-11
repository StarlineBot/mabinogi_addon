"""Ed25519 서명 확인(RFC 8032) — 순수 파이썬, 외부 라이브러리 없음.

앱은 서버가 서명한 로그인 토큰을 **공개 키로 확인만** 한다(계정 관리 명세 3.2). 확인은 로그인·시작·하루 1번뿐이라
속도(수 ms~수십 ms)는 문제가 되지 않고, 의존성(암호 라이브러리·exe 빌드 변경)을 늘리지 않으려 직접 구현했다.
`sign`·`public_key`는 테스트의 가짜 서버용이다(앱 실행 경로는 `verify`만 쓴다). RFC 8032 7.1 시험 값으로 확인한다.
"""
from __future__ import annotations

import hashlib

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _sha512_int(data: bytes) -> int:
    return int.from_bytes(_sha512(data), "little")


# 확장 좌표 (X, Y, Z, T), x = X/Z, y = Y/Z, x*y = T/Z
def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, p):
    q = (0, 1, 1, 0)  # 항등원
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _equal(p, q) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _I % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(p) -> bytes:
    zinv = pow(p[2], _P - 2, _P)
    x, y = p[0] * zinv % _P, p[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _secret_expand(secret: bytes):
    if len(secret) != 32:
        raise ValueError("비밀 키는 32바이트")
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(secret: bytes) -> bytes:
    a, _ = _secret_expand(secret)
    return _compress(_mul(a, _G))


def sign(secret: bytes, message: bytes) -> bytes:
    a, prefix = _secret_expand(secret)
    pub = _compress(_mul(a, _G))
    r = _sha512_int(prefix + message) % _L
    rs = _compress(_mul(r, _G))
    h = _sha512_int(rs + pub + message) % _L
    s = (r + h * a) % _L
    return rs + int.to_bytes(s, 32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """서명이 맞으면 True. 형식이 틀리거나(길이·점 아님·s ≥ L) 서명이 다르면 False(예외 없음)."""
    try:
        if len(public) != 32 or len(signature) != 64:
            return False
        a = _decompress(public)
        r = _decompress(signature[:32])
        if a is None or r is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= _L:
            return False
        h = _sha512_int(signature[:32] + public + message) % _L
        return _equal(_mul(s, _G), _add(r, _mul(h, a)))
    except Exception:  # noqa: BLE001 — 틀린 입력은 '확인 실패'
        return False
