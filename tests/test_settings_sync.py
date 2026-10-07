"""설정 백업 디스코드 전송 테스트(네트워크 없이)."""

import pytest

from mabinogi_addon.settings_sync import send_config_backup


class _Resp:
    def __init__(self, status=204):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b""


def test_sends_config_as_attachment_with_mention():
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["ctype"] = req.headers.get("Content-type")
        sent["data"] = req.data
        return _Resp(204)

    send_config_backup(
        "https://x", "12345", '{"a": 1}', username="Star", urlopen=fake_urlopen
    )
    assert sent["ctype"].startswith("multipart/form-data; boundary=")
    assert b'name="files[0]"' in sent["data"]
    assert b"config.json" in sent["data"]
    assert b"<@12345>" in sent["data"]  # 봇이 DM 보낼 대상 멘션
    assert b'{"a": 1}' in sent["data"]


def test_requires_login_and_webhook():
    with pytest.raises(ValueError):
        send_config_backup("", "123", "{}", urlopen=lambda *a, **k: _Resp())
    with pytest.raises(ValueError):
        send_config_backup("https://x", "", "{}", urlopen=lambda *a, **k: _Resp())
