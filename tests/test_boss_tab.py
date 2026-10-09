"""보스 패턴 탭 스모크: 생성·게이팅·미리보기가 예외 없이 동작."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mabinogi_addon import config


def _app():
    return QApplication.instance() or QApplication([])


class _Watcher:
    def is_game_active(self):
        return False

    def is_self_active(self):
        return True


def test_construct_and_gate(monkeypatch):
    _app()
    from mabinogi_addon.ui.boss_tab import BossTab

    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: None)
    t = BossTab(_Watcher())
    assert len(t._bosses) == 3  # 번들 3보스
    t._apply_gate()  # 미로그인 → 컨트롤 숨김(예외 없이)
    t._preview_warning()  # 경고 미리보기 — 예외 없이
    t.shutdown()


def test_supported_label_lists_thresholds(monkeypatch):
    _app()
    from mabinogi_addon.ui.boss_tab import BossTab

    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: {"name": "x"})
    t = BossTab(_Watcher())
    txt = t._supported_label().text()
    assert "고목의 페타크" in txt and "85%" in txt
    assert "레넨의 미이르 : 회한" in txt and "65%" in txt
    t.shutdown()
