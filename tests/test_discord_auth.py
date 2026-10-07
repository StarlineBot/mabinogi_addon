"""Discord 로그인 테스트. 순수 함수 + 로컬 서버 end-to-end(루프백)."""

import json
import threading
import urllib.parse
import urllib.request

from mabinogi_addon import discord_auth


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


def test_authorize_url_has_implicit_params():
    url = discord_auth.authorize_url("st8")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["client_id"] == [discord_auth.CLIENT_ID]
    assert q["redirect_uri"] == [discord_auth.REDIRECT_URI]
    assert q["response_type"] == ["token"]  # implicit(=secret 불필요)
    assert q["scope"] == ["identify"]
    assert q["state"] == ["st8"]


def test_fetch_user_prefers_global_name():
    def fake_urlopen(req, timeout=None):
        assert req.headers["Authorization"] == "Bearer TKN"
        return _Resp({"id": "123", "username": "legacy", "global_name": "하프별"})

    uid, name = discord_auth.fetch_user("TKN", urlopen=fake_urlopen)
    assert uid == "123"
    assert name == "하프별"


def test_fetch_user_falls_back_to_username():
    def fake_urlopen(req, timeout=None):
        return _Resp({"id": "9", "username": "starline", "global_name": None})

    uid, name = discord_auth.fetch_user("TKN", urlopen=fake_urlopen)
    assert (uid, name) == ("9", "starline")


def test_login_end_to_end_returns_user(monkeypatch):
    """실제 로컬 서버를 띄워 콜백→조회→서버종료까지. 종료 교착이면 여기서 멈춰 실패."""
    monkeypatch.setattr(discord_auth, "fetch_user", lambda tok, **k: ("42", "Star"))

    def fake_open(url):
        # authorize_url의 state를 그대로 실어 /token 콜백을 흉내(프래그먼트→질의문자열).
        st = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        target = (
            f"http://127.0.0.1:{discord_auth.PORT}"
            f"/token?access_token=TKN&state={st}"
        )

        def hit():
            opener = urllib.request.build_opener(  # 로컬은 프록시 우회
                urllib.request.ProxyHandler({})
            )
            opener.open(target, timeout=5).read()

        threading.Thread(target=hit, daemon=True).start()

    result = discord_auth.login(open_browser=fake_open, timeout=10.0)
    assert result == ("42", "Star")
