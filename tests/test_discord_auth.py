"""Discord 로그인 순수 함수 테스트(네트워크 없이). 로컬 서버 흐름은 제외."""

import json
import urllib.parse

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
