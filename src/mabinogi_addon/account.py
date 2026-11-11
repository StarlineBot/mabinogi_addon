"""디스코드 계정(서버 경유 로그인) — 토큰 확인·보관·유예, 서버 API(계정 관리 명세 3.2·3.4).

코드 → 런타임 동작:
- 로그인하면 서버(`SERVER_URL`)가 디스코드 인증을 대신하고 **서명한 앱 토큰**을 준다. 앱은 내장 **공개 키**로 서명만 확인한다
  (비밀 키는 서버에만) → config.json을 고쳐 로그인하거나 제작자 등급을 흉내 낼 수 없다.
- 토큰은 config `discordAccount {token, checked}`에 둔다. `checked`는 서버가 마지막으로 확인해 준 시각(로그인·/me).
- 로그인 상태 = 서명 맞음 + 토큰 만료 전 + 마지막 확인 뒤 7일 이내(서버가 꺼져 있어도 7일은 유지, 넘으면 비로그인).
- 서명 확인은 같은 토큰이면 한 번만(결과 캐시) — `config.load_discord_user`가 여러 곳에서 자주 불린다.
- 비로그인이면 서버와 통신하지 않는다(이 모듈의 네트워크 함수는 토큰이 있을 때만 불린다).

토큰 형식(서버 discord_bot/addon_server, 커밋 4a4c5de): **JWT, alg=EdDSA(Ed25519)**, header kid="k1".
클레임 iss="starline-bot", aud="mabinogi-addon", sub=디스코드 ID, name, tier("user"|"creator"), iat, exp(발급+30일).
앱 확인: 서명(`header.payload`의 ASCII 바이트) + alg + iss + aud + exp(+ sub 숫자·tier 값). tier는 서버가 /me마다 다시 정한다.
"""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request

from . import ed25519

_log = logging.getLogger("mabinogi_addon.account")

SERVER_URL = "https://starline-bot.duckdns.org"
PORT = 53123  # 로그인 콜백(localhost) — 예전 로그인과 같은 포트
GRACE_SECONDS = 7 * 24 * 3600  # 서버 확인 없이 로그인을 유지하는 기간
REFRESH_SECONDS = 24 * 3600  # 켜진 동안 /me로 새 토큰 받는 간격
TIERS = ("user", "creator")
CONFIG_KEY = "discordAccount"

ISSUER = "starline-bot"
AUDIENCE = "mabinogi-addon"
# 서버 서명용 공개 키(32바이트 hex) — 서버가 준 raw(base64) wpSDRfPaiTpyr1+SXsJq8ZNKc7evZYmFHGujnapR18Y= (공개해도 안전, 11-11).
# 테스트는 시험 키(tests/account_fakes.py)로 이 값을 바꿔 끼운다. 시험 키로 되돌리면 preflight가 배포를 막는다(PUBLIC_KEY_IS_TEST).
PUBLIC_KEY_HEX = "c2948345f3da893a72af5f925ec26af1934a73b7af6589851c6ba39daa51d7c6"
PUBLIC_KEY_IS_TEST = False


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


_VERIFIED: dict[tuple[str, str], dict | None] = {}  # (공개 키, 토큰) → 본문 또는 None(서명 틀림)


def verify_token(token, *, public_key_hex: str | None = None, now: float | None = None) -> dict | None:
    """서명·형식·만료가 맞으면 본문 dict, 아니면 None. 위조·다른 키·만료·등급 이상은 모두 None."""
    if not isinstance(token, str) or token.count(".") != 2 or len(token) > 4096:
        return None
    key_hex = public_key_hex or PUBLIC_KEY_HEX
    cache_key = (key_hex, token)
    if cache_key in _VERIFIED:
        payload = _VERIFIED[cache_key]
    else:
        payload = None
        try:
            head, body, sig = token.split(".")
            header = json.loads(_b64decode(head).decode("utf-8"))
            if isinstance(header, dict) and header.get("alg") == "EdDSA" and ed25519.verify(
                    bytes.fromhex(key_hex), f"{head}.{body}".encode("ascii"), _b64decode(sig)):
                data = json.loads(_b64decode(body).decode("utf-8"))
                aud = data.get("aud") if isinstance(data, dict) else None
                if (isinstance(data, dict) and data.get("iss") == ISSUER
                        and (aud == AUDIENCE or (isinstance(aud, list) and AUDIENCE in aud))
                        and isinstance(data.get("sub"), str) and data["sub"].isdecimal() and data.get("tier") in TIERS
                        and isinstance(data.get("exp"), (int, float)) and isinstance(data.get("iat"), (int, float))):
                    payload = data
        except Exception:  # noqa: BLE001 — 형식 오류 = 확인 실패
            payload = None
        if len(_VERIFIED) > 64:
            _VERIFIED.clear()
        _VERIFIED[cache_key] = payload
    if payload is None:
        return None
    now = time.time() if now is None else now
    if now >= payload["exp"]:
        return None
    return payload


def user_from_config(raw: dict, *, now: float | None = None) -> dict | None:
    """config 원본에서 로그인 사용자 {id, name, tier} 또는 None(토큰 없음·서명 틀림·만료·7일 확인 없음)."""
    sec = raw.get(CONFIG_KEY) if isinstance(raw, dict) else None
    if not isinstance(sec, dict):
        return None
    now = time.time() if now is None else now
    payload = verify_token(sec.get("token"), now=now)
    checked = sec.get("checked")
    if payload is None or not isinstance(checked, (int, float)) or now - checked > GRACE_SECONDS or checked > now + 300:
        return None
    return {"id": payload["sub"], "name": str(payload.get("name") or payload["sub"]), "tier": payload["tier"]}


def token_from_config(raw: dict) -> str | None:
    sec = raw.get(CONFIG_KEY) if isinstance(raw, dict) else None
    token = sec.get("token") if isinstance(sec, dict) else None
    return token if isinstance(token, str) else None


def store(raw: dict, token: str, *, now: float | None = None) -> dict:
    """확인한 토큰을 config 원본에 넣는다(예전 discordUser는 지움 — 서명 없는 로그인 기록)."""
    raw = dict(raw)
    raw.pop("discordUser", None)
    raw[CONFIG_KEY] = {"token": token, "checked": time.time() if now is None else now}
    return raw


def forget(raw: dict) -> dict:
    raw = dict(raw)
    raw.pop("discordUser", None)
    raw.pop(CONFIG_KEY, None)
    return raw


# ---- 서버 API -------------------------------------------------------------------------------------
class ServerError(Exception):
    """서버에 닿지 못함·5xx — 유예 기간 동안 로그인 유지."""


class AuthError(Exception):
    """서버가 토큰을 거절(401·403) — 비로그인으로."""


class Conflict(Exception):
    """설정 rev 충돌(409) — 서버 쪽 정보(info)를 들고 있다."""

    def __init__(self, info: dict | None):
        super().__init__("conflict")
        self.info = info or {}


class NotFound(Exception):
    """서버에 저장된 설정 없음(404)."""


def _ssl_context():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


class Client:
    """서버 API(최소). 화면 스레드에서 부르지 않는다(작업 스레드 — 화면 16ms 규칙)."""

    def __init__(self, token: str | None, *, base: str = SERVER_URL, opener=None, timeout: float = 10.0):
        self.token, self.base, self.timeout = token, base.rstrip("/"), timeout
        self._open = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout,
                                                                             context=_ssl_context()))

    def _request(self, method: str, path: str, *, body: bytes | None = None, headers: dict | None = None):
        req = urllib.request.Request(self.base + path, data=body, method=method)
        req.add_header("User-Agent", "mabinogi-addon")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with self._open(req, self.timeout) as resp:
                return resp.status if hasattr(resp, "status") else 200, dict(resp.headers or {}), resp.read()
        except urllib.error.HTTPError as exc:
            data = exc.read() if hasattr(exc, "read") else b""
            if exc.code in (401, 403):
                raise AuthError(exc.code) from None
            if exc.code == 404:
                raise NotFound() from None
            if exc.code == 409:
                raise Conflict(_json(data)) from None
            raise ServerError(f"HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ServerError(repr(exc)) from None

    def me(self) -> str:
        """토큰 확인 + 새 토큰(서명 확인 전 문자열)."""
        _status, _h, data = self._request("GET", "/me")
        token = _json(data).get("token")
        if not isinstance(token, str):
            raise ServerError("토큰 없는 응답")
        return token

    def logout(self) -> None:
        self._request("POST", "/auth/logout", body=b"")

    def settings_info(self) -> dict:
        """{exists, rev, updated(UTC ISO), device, resolution, size} — 서버에 없으면(exists=false) NotFound."""
        _status, _h, data = self._request("GET", "/settings")
        info = _json(data)
        if info.get("exists") is False or not isinstance(info.get("rev"), int):
            raise NotFound()
        return info

    def settings_blob(self) -> bytes:
        _status, _h, data = self._request("GET", "/settings/blob")
        return data

    def put_settings(self, blob: bytes, *, rev: int, device: str, resolution: str) -> dict:
        """올리기 `PUT /settings?device=&resolution=`(If-Match rev, 처음은 0) → {rev, updated, size}.
        rev가 다르면 Conflict({detail, rev: 서버 rev})."""
        import urllib.parse
        query = urllib.parse.urlencode({"device": str(device)[:64], "resolution": str(resolution)})
        _status, _h, data = self._request("PUT", "/settings?" + query, body=blob, headers={
            "If-Match": str(int(rev)), "Content-Type": "application/zip"})
        info = _json(data)
        if not isinstance(info.get("rev"), int):
            raise ServerError("rev 없는 응답")
        return info


def _json(data: bytes) -> dict:
    try:
        value = json.loads((data or b"{}").decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return value if isinstance(value, dict) else {}


def start_url(state: str, *, port: int = PORT, base: str = SERVER_URL) -> str:
    import urllib.parse
    return f"{base.rstrip('/')}/auth/start?" + urllib.parse.urlencode({"state": state, "port": port})
