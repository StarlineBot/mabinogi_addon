"""문의 전송(Discord 웹훅) 단위 테스트. 네트워크 없이 가짜 urlopen 주입."""

import json

import pytest

from mabinogi_addon.inquiry import send_inquiry


class _Resp:
    def __init__(self, status=204):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b""


def test_send_inquiry_posts_embed():
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["url"] = req.full_url
        sent["method"] = req.get_method()
        sent["body"] = json.loads(req.data.decode("utf-8"))
        sent["ctype"] = req.headers.get("Content-type")
        return _Resp(204)

    send_inquiry(
        "https://discord.test/webhook",
        "제목입니다",
        "내용입니다",
        urlopen=fake_urlopen,
    )
    assert sent["url"] == "https://discord.test/webhook"
    assert sent["method"] == "POST"
    assert sent["ctype"] == "application/json"
    embed = sent["body"]["embeds"][0]
    assert embed["title"] == "제목입니다"
    assert embed["description"] == "내용입니다"


def test_send_inquiry_requires_fields():
    with pytest.raises(ValueError):
        send_inquiry("https://x", "", "내용", urlopen=lambda *a, **k: _Resp())
    with pytest.raises(ValueError):
        send_inquiry("https://x", "제목", "   ", urlopen=lambda *a, **k: _Resp())


def test_send_inquiry_requires_webhook():
    with pytest.raises(ValueError):
        send_inquiry("", "제목", "내용", urlopen=lambda *a, **k: _Resp())


def test_send_inquiry_raises_on_bad_status():
    with pytest.raises(RuntimeError):
        send_inquiry(
            "https://x", "제목", "내용", urlopen=lambda *a, **k: _Resp(500)
        )
