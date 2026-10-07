"""문의 전송(Discord 웹훅) 단위 테스트. 네트워크 없이 가짜 urlopen 주입."""

import json
import urllib.error

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


def _http_error(code=400):
    return urllib.error.HTTPError("http://x", code, "bad", {}, None)


def test_creates_forum_post_with_thread_name():
    """포럼 채널 웹훅: thread_name(제목)으로 포스트 생성."""
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["url"] = req.full_url
        sent["method"] = req.get_method()
        sent["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp(204)

    send_inquiry(
        "https://discord.test/webhook",
        "제목입니다",
        "내용입니다",
        urlopen=fake_urlopen,
    )
    assert sent["method"] == "POST"
    assert sent["body"]["thread_name"] == "제목입니다"
    assert sent["body"]["content"] == "내용입니다"


def test_category_prefixes_title():
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp(204)

    send_inquiry(
        "https://x", "안 뜸", "내용", category="버그 신고", urlopen=fake_urlopen
    )
    assert sent["body"]["thread_name"] == "[버그 신고] 안 뜸"


def test_user_id_adds_mention():
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp(204)

    send_inquiry(
        "https://x", "제목", "내용", user_id="123456789", urlopen=fake_urlopen
    )
    assert "<@123456789>" in sent["body"]["content"]


def test_attaches_log_as_multipart():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["ctype"] = req.headers.get("Content-type")
        captured["data"] = req.data
        return _Resp(200)

    send_inquiry(
        "https://x",
        "크래시",
        "죽어요",
        category="버그 신고",
        log_text="ERROR 어쩌고 저쩌고 스택트레이스",
        urlopen=fake_urlopen,
    )
    assert captured["ctype"].startswith("multipart/form-data; boundary=")
    body = captured["data"]
    assert b'name="payload_json"' in body
    assert b'name="files[0]"' in body
    assert b"\xeb\xac\xb8\xec\x9d\x98\xeb\xa1\x9c\xea\xb7\xb8.txt" in body  # 문의로그.txt
    assert "스택트레이스".encode() in body


def test_falls_back_to_plain_message_on_400():
    """일반 텍스트 채널 웹훅: thread_name 거부(400) → 제목을 본문에 붙여 재전송."""
    calls = []

    def fake_urlopen(req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        calls.append(payload)
        if "thread_name" in payload:
            raise _http_error(400)
        return _Resp(204)

    send_inquiry("https://x", "제목", "내용", urlopen=fake_urlopen)
    assert len(calls) == 2  # 1차(thread_name) 실패 → 2차(폴백)
    assert "thread_name" not in calls[1]
    assert calls[1]["content"].startswith("**제목**")
    assert "내용" in calls[1]["content"]


def test_non_400_error_is_not_swallowed():
    def fake_urlopen(req, timeout=None):
        raise _http_error(401)

    with pytest.raises(urllib.error.HTTPError):
        send_inquiry("https://x", "제목", "내용", urlopen=fake_urlopen)


def test_requires_fields():
    with pytest.raises(ValueError):
        send_inquiry("https://x", "", "내용", urlopen=lambda *a, **k: _Resp())
    with pytest.raises(ValueError):
        send_inquiry("https://x", "제목", "   ", urlopen=lambda *a, **k: _Resp())


def test_requires_webhook():
    with pytest.raises(ValueError):
        send_inquiry("", "제목", "내용", urlopen=lambda *a, **k: _Resp())


def test_raises_on_bad_status():
    with pytest.raises(RuntimeError):
        send_inquiry(
            "https://x", "제목", "내용", urlopen=lambda *a, **k: _Resp(500)
        )
