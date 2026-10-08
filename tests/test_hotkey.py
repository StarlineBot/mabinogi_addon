"""전역 단축키 조합 파싱 + 설정 저장 회귀.

parse_spec은 'Ctrl+Alt+P' 같은 조합을 (modifiers, vk)로 바꾼다. 모디파이어 없는
단독 키와 윈도우키(게임이 선점)는 거부한다. 등록 자체는 Windows 전용이라 여기선
파싱 규칙만 검증한다(맥/리눅스 CI에서도 돈다).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mabinogi_addon import config
from mabinogi_addon.system.hotkey import parse_spec

_MOD_ALT = 0x0001
_MOD_CTRL = 0x0002
_MOD_SHIFT = 0x0004
_NOREPEAT = 0x4000


def test_valid_combo():
    mods, vk = parse_spec("Ctrl+Alt+P")
    assert mods == (_MOD_CTRL | _MOD_ALT | _NOREPEAT)
    assert vk == ord("P")


def test_function_key():
    mods, vk = parse_spec("Alt+F9")
    assert mods == (_MOD_ALT | _NOREPEAT)
    assert vk == 0x78  # VK_F9


def test_digit_and_shift():
    mods, vk = parse_spec("Shift+Ctrl+9")
    assert mods == (_MOD_SHIFT | _MOD_CTRL | _NOREPEAT)
    assert vk == ord("9")


def test_rejects_windows_key():
    assert parse_spec("Meta+P") is None
    assert parse_spec("Ctrl+Meta+X") is None


def test_rejects_bare_key():
    # 모디파이어 없는 단독 키는 오발 위험 → 거부
    assert parse_spec("P") is None
    assert parse_spec("F9") is None


def test_rejects_empty():
    assert parse_spec("") is None


def test_whitespace_tolerant():
    assert parse_spec(" Ctrl+Alt+K ") == (_MOD_CTRL | _MOD_ALT | _NOREPEAT, ord("K"))


def test_config_roundtrip():
    tmp = Path(tempfile.mkdtemp()) / "c.json"
    tmp.write_text("{}")
    assert config.load_pause_hotkey(tmp) == ""  # 기본 없음
    config.save_pause_hotkey("Ctrl+Alt+P", tmp)
    assert config.load_pause_hotkey(tmp) == "Ctrl+Alt+P"
    # general 섹션에 저장되고 다른 값과 공존
    data = json.loads(tmp.read_text())
    assert data["general"]["pauseHotkey"] == "Ctrl+Alt+P"
    config.save_pause_hotkey("", tmp)  # 지우기
    assert config.load_pause_hotkey(tmp) == ""
