"""서버 경유 디스코드 로그인(계정 관리 명세 3.2) — 앱이 state·토큰 서명을 확인한다."""
import threading
import urllib.parse
import urllib.request

import pytest

from account_fakes import test_key, OTHER_SECRET, make_token
from mabinogi_addon import account, discord_auth


def _browser(token_for):
    """가짜 브라우저: 서버 시작 주소를 받아(state·port) 서버가 하듯 localhost 콜백으로 토큰을 보낸다."""
    def open_browser(url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert url.startswith(account.SERVER_URL + "/auth/start?") and q["port"] == [str(discord_auth.PORT)]
        token, state = token_for(q["state"][0])

        def go():
            cb = f"http://127.0.0.1:{discord_auth.PORT}/callback?" + urllib.parse.urlencode({"token": token, "state": state})
            urllib.request.urlopen(cb, timeout=5).read()
        threading.Thread(target=go, daemon=True).start()
        return True
    return open_browser


def test_login_returns_verified_token():
    token = make_token()
    assert discord_auth.login(open_browser=_browser(lambda st: (token, st)), timeout=10.0) == token


@pytest.mark.parametrize("case", ["state", "forged", "other_key", "expired"])
def test_login_rejects_bad_callback(case):
    token = {"state": make_token(), "forged": make_token()[:-4] + "AAAA", "other_key": make_token(secret=OTHER_SECRET),
             "expired": make_token(ttl=-10)}[case]
    result = discord_auth.login(open_browser=_browser(lambda st: (token, "WRONG" if case == "state" else st)), timeout=10.0)
    assert result is None


@pytest.mark.parametrize("error,text", [("access_denied", "취소"), ("login_failed", "다시 시도"), ("blocked", "로그인할 수 없어요")])
def test_login_error_from_server_is_reported(error, text):
    """서버 콜백 ?error=access_denied|login_failed|blocked&state=… → 로그인 안 함 + 화면 문구."""
    def open_browser(url):
        st = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]

        def go():
            cb = f"http://127.0.0.1:{discord_auth.PORT}/callback?" + urllib.parse.urlencode({"error": error, "state": st})
            urllib.request.urlopen(cb, timeout=5).read()
        threading.Thread(target=go, daemon=True).start()
    assert discord_auth.login(open_browser=open_browser, timeout=10.0) is None
    assert discord_auth.last_error[0] == error and text in discord_auth.ERROR_TEXT[error]
