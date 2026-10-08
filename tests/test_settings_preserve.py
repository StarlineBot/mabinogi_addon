"""회귀: 아이콘이 (일시적으로) 없는 버프·디버프 설정이 자동저장에 지워지지 않는다.

업데이트 중 카탈로그가 잠깐 비면, 저장이 사용자의 버프/디버프 설정을 영구 삭제하던
버그에 대한 방어. _save는 목록에 없는(아이콘 없는) 저장분도 함께 기록해야 한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui.buff_tab import ANCHOR_ID, BuffTab
from mabinogi_addon.ui.debuff_tab import DebuffTab


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_debuff_save_preserves_iconless(monkeypatch) -> None:
    _app()
    tab = DebuffTab()
    captured: dict = {}
    monkeypatch.setattr(
        config, "save_debuff_settings",
        lambda items, *a, **k: captured.update(ids=[s.id for s in items]),
    )
    # 아이콘이 없어 카탈로그·목록(_order)에 없는 저장분을 흉내낸다.
    tab._settings["ghost"] = config.BuffSettings(id="ghost")
    assert "ghost" not in tab._order
    tab._save()
    assert "ghost" in captured["ids"]  # 저장에서 사라지지 않아야 함


def test_buff_save_preserves_iconless(monkeypatch) -> None:
    _app()
    tab = BuffTab()
    captured: dict = {}
    monkeypatch.setattr(
        config, "save_buff_settings",
        lambda items, *a, **k: captured.update(ids=[s.id for s in items]),
    )
    tab._settings["ghost"] = config.BuffSettings(id="ghost")
    assert "ghost" not in tab._order
    assert "ghost" != ANCHOR_ID
    tab._save()
    assert "ghost" in captured["ids"]
