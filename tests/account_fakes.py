"""계정 테스트 도우미 — 시험 키(비밀 키는 여기에만)·JWT(EdDSA) 토큰 만들기·가짜 서버(계정 관리 명세 5절).

앱에는 서버의 실제 공개 키가 들어 있다. 테스트는 `test_key` 픽스처로 account.PUBLIC_KEY_HEX를 시험 키 짝으로 바꿔 끼운다.
가짜 서버는 discord_bot/addon_server 규격(커밋 4a4c5de)대로 답한다.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse

import pytest

from mabinogi_addon import account, ed25519

TEST_SECRET = hashlib.sha256(b"mabinogi-addon account TEST key - not for release").digest()
OTHER_SECRET = hashlib.sha256(b"someone else").digest()
TEST_PUBLIC_HEX = ed25519.public_key(TEST_SECRET).hex()


@pytest.fixture(autouse=True)
def test_key(monkeypatch):
    """앱 내장 공개 키 대신 시험 키 짝으로 확인(테스트 파일에서 import하면 자동 적용)."""
    monkeypatch.setattr(account, "PUBLIC_KEY_HEX", TEST_PUBLIC_HEX)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def make_token(sub="111222333", name="테스터", tier="user", *, secret=TEST_SECRET, now=None, ttl=30 * 86400,
               alg="EdDSA", iss="starline-bot", aud="mabinogi-addon", **extra) -> str:
    """서버와 같은 JWT(header {alg: EdDSA, typ: JWT, kid: k1}, 서명 대상 'header.payload')."""
    now = int(time.time() if now is None else now)
    head = _b64(json.dumps({"alg": alg, "typ": "JWT", "kid": "k1"}).encode())
    body = _b64(json.dumps({"iss": iss, "aud": aud, "sub": sub, "name": name, "tier": tier, "iat": now,
                            "exp": now + ttl, **extra}, ensure_ascii=False).encode("utf-8"))
    return f"{head}.{body}." + _b64(ed25519.sign(secret, f"{head}.{body}".encode("ascii")))


class _Resp(io.BytesIO):
    def __init__(self, data: bytes, status=200):
        super().__init__(data)
        self.status, self.headers = status, {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeServer:
    """account.Client(opener=…)에 넣는 가짜 서버. 요청을 모두 기록한다(비로그인 통신 0회 확인)."""

    def __init__(self, *, down=False, reject=False, token_factory=None):
        self.calls: list[tuple[str, str, dict]] = []
        self.down, self.reject = down, reject
        self.rev, self.blob, self.info = 0, None, None
        self.token_factory = token_factory or (lambda: make_token())

    def opener(self, req, timeout):
        method = req.get_method()
        parsed = urllib.parse.urlparse(req.full_url)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        headers = {k.lower(): v for k, v in req.header_items()}
        path = parsed.path.lstrip("/")
        self.calls.append((method, "/" + path, headers))
        self.last_query = query
        if self.down:
            raise urllib.error.URLError("서버 꺼짐")
        if self.reject or "authorization" not in headers:
            raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, io.BytesIO(b"{}"))
        path = "/" + path
        if path == "/me":
            return _Resp(json.dumps({"id": "111222333", "name": "테스터", "tier": "user", "status": "active",
                                     "token": self.token_factory(), "expiresAt": "2026-12-11T00:00:00Z"}).encode())
        if path == "/auth/logout":
            return _Resp(b"", status=204)
        if path == "/settings" and method == "GET":
            if self.info is None:
                return _Resp(json.dumps({"exists": False, "rev": 0}).encode())
            return _Resp(json.dumps({"exists": True, **self.info}).encode())
        if path == "/settings/blob":
            if self.blob is None:
                raise urllib.error.HTTPError(req.full_url, 404, "none", {}, io.BytesIO(b"{}"))
            return _Resp(self.blob)
        if path == "/settings" and method == "PUT":
            if "if-match" not in headers:
                raise urllib.error.HTTPError(req.full_url, 428, "need if-match", {}, io.BytesIO(b"{}"))
            if int(headers["if-match"]) != self.rev:
                raise urllib.error.HTTPError(req.full_url, 409, "conflict", {},
                                             io.BytesIO(json.dumps({"detail": "rev mismatch", "rev": self.rev}).encode()))
            if len(req.data) > 2 * 1024 * 1024:
                raise urllib.error.HTTPError(req.full_url, 413, "too large", {}, io.BytesIO(b"{}"))
            if any(k in req.data.decode("latin-1") for k in ("nexonApiKey", "inquiryWebhookUrl", "configWebhookUrl")):
                raise urllib.error.HTTPError(req.full_url, 422, "secret", {}, io.BytesIO(b"{}"))
            self.rev += 1
            self.blob = bytes(req.data)
            self.info = {"rev": self.rev, "updated": "2026-11-11T01:02:03Z", "device": query.get("device", ""),
                         "resolution": query.get("resolution", ""), "size": len(req.data)}
            return _Resp(json.dumps({"rev": self.rev, "updated": self.info["updated"], "size": len(req.data)}).encode())
        raise urllib.error.HTTPError(req.full_url, 404, "no route", {}, io.BytesIO(b"{}"))
