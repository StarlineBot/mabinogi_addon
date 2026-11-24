"""scripts/gen_tts.py — 파일 몇 개만 만들기(--only, 사용자 11-24 '이안 투아림 2차만 같은 목소리로')."""
from __future__ import annotations

import base64
import json

import pytest

from scripts import gen_tts


def test_ian_pack_has_tuarim_second_line_and_it_is_urgent():
    ian = next(p for p in gen_tts.PACKS if p["name"] == "차분한 남성")
    assert ian["lines"][gen_tts.F_TUARIM2] == "투아림, 지금 발동합니다. 준비하십시오."
    assert gen_tts.F_TUARIM2 in gen_tts.URGENT_FILES
    assert not {"화난 여성", "조용한 여성", "장난스러운 남성"} & {p["name"] for p in gen_tts.PACKS}  # 사용자 녹음 팩은 대상 아님


def test_only_generates_named_files_and_leaves_others(tmp_path, monkeypatch):
    pack_dir = tmp_path / "차분한 남성"
    pack_dir.mkdir()
    (pack_dir / gen_tts.F_VIVACE).write_bytes(b"old")
    sent = []

    class Reply:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"audioContent": base64.b64encode(b"new").decode()}).encode()

    def fake_urlopen(req, timeout):
        sent.append(json.loads(req.data))
        return Reply(req.data)

    monkeypatch.setattr(gen_tts, "SOUNDS_DIR", tmp_path)
    monkeypatch.setattr(gen_tts.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test")
    gen_tts.main(["--backend", "google", "--pack", "차분한 남성", "--only", gen_tts.F_TUARIM2])
    assert sorted(p.name for p in pack_dir.iterdir()) == sorted([gen_tts.F_VIVACE, gen_tts.F_TUARIM2])
    assert (pack_dir / gen_tts.F_VIVACE).read_bytes() == b"old" and (pack_dir / gen_tts.F_TUARIM2).read_bytes() == b"new"
    assert len(sent) == 1 and sent[0]["input"]["text"] == "투아림, 지금 발동합니다. 준비하십시오."
    assert sent[0]["voice"]["name"] == "ko-KR-Chirp3-HD-Algieba"
    assert sent[0]["audioConfig"]["speakingRate"] == round(0.97 * gen_tts.URGENT_GOOGLE_RATE_MULT, 3)


def test_only_with_unknown_file_stops(tmp_path, monkeypatch):
    sounds = tmp_path / "sounds"
    sounds.mkdir()
    monkeypatch.setattr(gen_tts, "SOUNDS_DIR", sounds)
    with pytest.raises(SystemExit):
        gen_tts.main(["--pack", "차분한 남성", "--only", "없는 파일.mp3"])
    assert not any(sounds.iterdir())
