"""계정(서버 토큰) — 서명 확인·제작자 흉내 차단·7일 유예·로그아웃·비로그인 통신 0회(계정 관리 명세 3.2·5절)."""
import json
import time

import pytest

from account_fakes import test_key, OTHER_SECRET, TEST_SECRET, FakeServer, make_token
from mabinogi_addon import account, config, ed25519, feature_access


def test_ed25519_rfc8032_vectors():
    vectors = [("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
                "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
                "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
               ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
                "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
                "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a")]
    for sk, pk, msg, sig in vectors:
        sk, pk, msg, sig = map(bytes.fromhex, (sk, pk, msg, sig))
        assert ed25519.public_key(sk) == pk and ed25519.sign(sk, msg) == sig
        assert ed25519.verify(pk, msg, sig) and not ed25519.verify(pk, msg + b"!", sig)
    import base64
    assert account.PUBLIC_KEY_IS_TEST is False  # 앱 내장 = 서버가 준 실제 공개 키(11-11)
    assert account.PUBLIC_KEY_HEX == ed25519.public_key(TEST_SECRET).hex()  # 테스트 중엔 test_key가 바꿔 끼움
    import inspect
    source = inspect.getsource(account)
    real = base64.b64decode("wpSDRfPaiTpyr1+SXsJq8ZNKc7evZYmFHGujnapR18Y=").hex()  # 서버가 준 공개 키(11-11)
    assert f'PUBLIC_KEY_HEX = "{real}"' in source and real != ed25519.public_key(TEST_SECRET).hex()


def test_token_signature_expiry_and_shape():
    good = make_token(tier="user")
    assert account.verify_token(good)["tier"] == "user"
    head, body, sig = good.split(".")
    import base64
    raw = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    raw["tier"] = "creator"  # 제작자로 고쳐 보기
    tampered = head + "." + base64.urlsafe_b64encode(json.dumps(raw).encode()).decode().rstrip("=") + "." + sig
    assert account.verify_token(tampered) is None  # 본문을 고치면 서명이 안 맞음
    assert account.verify_token(make_token(iss="someone")) is None and account.verify_token(make_token(aud="other")) is None
    assert account.verify_token(make_token(alg="none")) is None
    assert account.verify_token(make_token(secret=OTHER_SECRET)) is None  # 다른 키
    assert account.verify_token(make_token(ttl=-1)) is None  # 만료
    assert account.verify_token(make_token(tier="admin")) is None  # 모르는 등급
    for junk in (None, "", "abc", "a.b", "a.b.c", 123, "x" * 5000):
        assert account.verify_token(junk) is None


def _write(raw):
    config._write_local_config(raw)


def test_config_creator_id_without_signed_token_is_not_login():
    """config.json에 제작자 ID를 적어도(예전 discordUser) 로그인도 제작자도 아님."""
    _write({"discordUser": {"id": feature_access.CREATOR_DISCORD_ID, "name": "흉내"},
            "discordAccount": {"token": "garbage", "checked": time.time()}})
    assert config.load_discord_user() is None and not feature_access.is_creator() and not feature_access.is_logged_in()
    # 제작자 ID로 서명된 user 등급 토큰 → 로그인은 되지만 제작자 아님(등급이 판정)
    config.save_account_token(make_token(sub=feature_access.CREATOR_DISCORD_ID, tier="user"))
    assert feature_access.is_logged_in() and not feature_access.is_creator() and feature_access.tier() == "user"
    config.save_account_token(make_token(tier="creator"))
    assert feature_access.is_creator()
    assert "discordUser" not in config._read_local_config()  # 로그인하면 예전 기록 지움


@pytest.mark.parametrize("days,logged", [(6.9, True), (7.1, False)])
def test_seven_day_grace_after_last_server_check(days, logged):
    now = time.time()
    config.save_account_token(make_token(now=now - days * 86400), now=now - days * 86400)
    assert feature_access.is_logged_in() is logged


def test_refresh_server_down_keeps_login_and_rejected_logs_out(qtbot_app=None):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.account_controller import AccountController
    QApplication.instance() or QApplication([])
    config.save_account_token(make_token(), now=time.time() - 3 * 86400)
    down = FakeServer(down=True)
    c = AccountController(client_factory=lambda t: account.Client(t, opener=down.opener), executor=_Inline())
    assert c._job_refresh() is None and feature_access.is_logged_in()  # 서버 꺼짐 → 유예 안 로그인 유지
    newer = make_token(name="새 이름")
    ok = FakeServer(token_factory=lambda: newer)
    c._client = lambda t: account.Client(t, opener=ok.opener)
    assert c._job_refresh() == "refreshed" and config.load_account_token() == newer
    assert time.time() - config._read_local_config()["discordAccount"]["checked"] < 5  # 확인 시각 새로
    fake_key = FakeServer(token_factory=lambda: make_token(secret=OTHER_SECRET))
    c._client = lambda t: account.Client(t, opener=fake_key.opener)
    assert c._job_refresh() is None and config.load_account_token() == newer  # 다른 키로 서명된 새 토큰은 버림
    c._client = lambda t: account.Client(t, opener=FakeServer(reject=True).opener)
    assert c._job_refresh() == "logged_out" and not feature_access.is_logged_in()
    c.shutdown(flush=False)


def test_logout_clears_token_and_tells_server_once():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.account_controller import AccountController
    QApplication.instance() or QApplication([])
    config.save_account_token(make_token())
    server = FakeServer()
    c = AccountController(client_factory=lambda t: account.Client(t, opener=server.opener), executor=_Inline())
    c.logout()
    assert not feature_access.is_logged_in() and "discordAccount" not in config._read_local_config()
    assert [(m, p) for m, p, _ in server.calls] == [("POST", "/auth/logout")]
    assert server.calls[0][2]["authorization"].startswith("Bearer ")
    c.shutdown(flush=False)


class _Inline:
    inline = True

    def submit(self, fn, *a):
        from concurrent.futures import Future
        f = Future()
        try:
            f.set_result(fn(*a))
        except Exception as exc:  # noqa: BLE001
            f.set_exception(exc)
        return f

    def shutdown(self, wait=False):
        pass
