"""보스 패턴 탭 스모크: 생성·게이팅·미리보기가 예외 없이 동작."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
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
    assert "lenen_miir" in t._bosses  # 번들 보스가 로드됨
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


def test_stale_tracker_cleared_when_boss_gone(monkeypatch):
    """보스가 사라져 이름이 한참 미식별이면 트래커를 지워, 그 뒤 garbage HP로
    옛 보스 경고가 뜨지 않아야 한다. (보스 없는데 40% 알림 뜨던 버그 회귀 방지)"""
    _app()
    from mabinogi_addon.ui import boss_tab as bt_mod
    from mabinogi_addon.ui.boss_tab import BossTab

    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: {"name": "x"})
    t = BossTab(_Watcher())
    t._region = {"x": 0, "y": 0, "w": 150, "h": 36}
    t.enable.setChecked(True)
    monkeypatch.setattr(t, "_grab_rect", lambda *a: np.zeros((36, 150, 3), np.uint8))
    monkeypatch.setattr(t, "_show_preview", lambda *a: None)
    monkeypatch.setattr(t, "_play", lambda *a: None)
    fired: list = []
    monkeypatch.setattr(t._overlay, "show_message", lambda text, *a: fired.append(text))

    # 1) 레넨(임계 80,40) 식별 + HP 90으로 안정화
    monkeypatch.setattr(bt_mod, "identify", lambda *a, **k: "lenen_miir")
    monkeypatch.setattr(bt_mod, "read_percent", lambda *a, **k: 90)
    for _ in range(4):
        t._tick()
    assert t._tracker is not None and t._stable_hp == 90

    # 2) 보스 사라짐: 이름 미식별 + HP는 garbage(40)로 들어와도, 미식별이 길어지면
    #    트래커가 지워져 경고가 안 떠야 한다.
    monkeypatch.setattr(bt_mod, "identify", lambda *a, **k: None)
    monkeypatch.setattr(bt_mod, "read_percent", lambda *a, **k: 40)
    for _ in range(15):
        t._tick()
    assert t._tracker is None
    assert fired == []  # 거짓 40% 경고 없음
    t.shutdown()


def test_accept_hp_ignores_entry_glitch(monkeypatch):
    """진입 순간 순간 오판독(89% 중 2프레임 40%)이 확정 HP를 바꾸지 않아야 한다.
    (레넨 89% 진입 시 40% 경고가 뜨던 버그 회귀 방지)"""
    _app()
    from mabinogi_addon.ui.boss_tab import BossTab

    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: {"name": "x"})
    t = BossTab(_Watcher())

    for _ in range(3):  # 89%로 첫 확정(큰 점프·첫 확정 = 3연속)
        t._accept_hp(89)
    assert t._stable_hp == 89

    t._accept_hp(40)  # 글리치 2프레임 — 큰 점프라 3연속 전엔 반영 안 됨
    t._accept_hp(40)
    assert t._stable_hp == 89

    t._accept_hp(None)  # 못 읽은 프레임: 후보 리셋
    t._accept_hp(40)
    t._accept_hp(40)
    assert t._stable_hp == 89  # 리셋됐으니 아직 2연속

    # 완만한 감소(≤12)는 2연속으로 바로 추적
    t._accept_hp(85)
    t._accept_hp(85)
    assert t._stable_hp == 85
    t.shutdown()
