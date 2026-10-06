import io
import json

from mabinogi_addon.party.client import fetch_horn_bugle


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_parses_history_and_sends_key():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["key"] = req.get_header("X-nxopen-api-key")
        return _FakeResp({"horn_bugle_world_history": [{"message": "x"}]})

    out = fetch_horn_bugle("MYKEY", urlopen=fake_urlopen)
    assert out == [{"message": "x"}]
    assert captured["key"] == "MYKEY"
    assert "horn-bugle-world/history" in captured["url"]
    assert "server_name=" in captured["url"]


def test_fetch_empty_when_missing_key_in_payload():
    def fake_urlopen(req, timeout=None):
        return _FakeResp({})

    assert fetch_horn_bugle("K", urlopen=fake_urlopen) == []
