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


def test_construct_without_login(monkeypatch):
    """보스 패턴은 로그인 없이도 컨트롤이 보이고 동작한다(BETA·로그인 게이팅 제거)."""
    _app()
    from mabinogi_addon.ui.boss_tab import BossTab

    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: None)
    t = BossTab(_Watcher())
    assert "lenen_miir" in t._bosses  # 번들 보스가 로드됨
    assert t._controls.isVisibleTo(t)  # 미로그인이어도 컨트롤 노출
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
    # 짧은 미식별(패턴으로 바가 잠깐 숨음)엔 트래커 유지 + 발동 없음
    for _ in range(5):
        t._tick()
    assert t._tracker is not None  # 아직 전투 중(잠금 유지)
    assert fired == []
    # 오래 미식별(전투 종료)이면 트래커 해제
    for _ in range(t._GONE_FRAMES + 2):
        t._tick()
    assert t._tracker is None
    assert fired == []  # 거짓 40% 경고 없음
    t.shutdown()


def test_upcoming_list_updates_from_tracker(monkeypatch):
    """'다음 패턴 보기'가 켜지면 식별된 보스의 남은 임계가 목록 오버레이에 들어가고,
    준비(5% 전) 알림이 뜬 임계는 목록에서 빠진다."""
    _app()
    from mabinogi_addon.ui import boss_tab as bt_mod
    from mabinogi_addon.ui.boss_tab import BossTab

    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: {"name": "x"})
    t = BossTab(_Watcher())
    t._region = {"x": 0, "y": 0, "w": 150, "h": 36}
    t.show_upcoming.setChecked(True)
    monkeypatch.setattr(t, "_grab_rect", lambda *a: np.zeros((36, 150, 3), np.uint8))
    monkeypatch.setattr(t, "_show_preview", lambda *a: None)

    # 레넨(임계 80,60,40,30) 식별 + HP 90 → 전부 남은 패턴으로 나열
    monkeypatch.setattr(bt_mod, "identify", lambda *a, **k: "lenen_miir")
    monkeypatch.setattr(bt_mod, "read_percent", lambda *a, **k: 90)
    for _ in range(4):
        t._tick()
    assert t._upcoming.items == [80, 60, 40, 30]

    # HP 84로 하강 → 80 준비(85 통과) 발동 → 80이 목록에서 빠짐
    monkeypatch.setattr(bt_mod, "read_percent", lambda *a, **k: 84)
    for _ in range(4):
        t._tick()
    assert t._upcoming.items == [60, 40, 30]
    t.shutdown()


def test_upcoming_hides_quickly_after_boss_gone(monkeypatch):
    """보스가 화면에서 사라지면 '다음 패턴 목록'은 금방 감춰야 한다(#4).
    트래커·HP는 긴 패턴을 버티려 _GONE_FRAMES(~18초)까지 살아 있지만, 목록은
    _UPCOMING_GONE_FRAMES(~2초) 뒤면 숨는다 — 보스 떠난 뒤에도 '다가오는 %'가
    한참 떠 있던 문제 회귀 방지."""
    _app()
    from mabinogi_addon.ui import boss_tab as bt_mod
    from mabinogi_addon.ui.boss_tab import BossTab

    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: {"name": "x"})
    t = BossTab(_Watcher())
    t._region = {"x": 0, "y": 0, "w": 150, "h": 36}
    t.show_upcoming.setChecked(True)
    t._upcoming.set_locked(True)  # 고정(게임 위 표시) — 이 상태에서 게이트가 적용됨
    monkeypatch.setattr(t, "_grab_rect", lambda *a: np.zeros((36, 150, 3), np.uint8))
    monkeypatch.setattr(t, "_show_preview", lambda *a: None)

    # 레넨 식별 + HP 90 → 목록 표시
    monkeypatch.setattr(bt_mod, "identify", lambda *a, **k: "lenen_miir")
    monkeypatch.setattr(bt_mod, "read_percent", lambda *a, **k: 90)
    for _ in range(4):
        t._tick()
    assert t._upcoming.isVisible()
    assert t._upcoming.items == [80, 60, 40, 30]

    # 보스 사라짐: 짧은 미식별(유예 내)엔 목록 유지
    monkeypatch.setattr(bt_mod, "identify", lambda *a, **k: None)
    for _ in range(t._UPCOMING_GONE_FRAMES):
        t._tick()
    assert t._upcoming.isVisible()  # 아직 유예 내 → 유지

    # 유예를 넘기면(아직 _GONE_FRAMES 전) 목록은 숨지만 트래커는 살아 있다
    for _ in range(3):
        t._tick()
    assert not t._upcoming.isVisible()
    assert t._tracker is not None  # 트래커는 _GONE_FRAMES까지 유지(긴 패턴 대비)
    t.shutdown()


def test_warn_lock_toggle_updates_overlay_and_button(monkeypatch):
    """위치 잠금 토글이 실제 오버레이와 같은 상태를 표시한다."""
    _app()
    from mabinogi_addon.ui.boss_tab import BossTab

    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: {"name": "x"})
    t = BossTab(_Watcher())
    # 알려진 상태에서 시작해 양방향 전환과 checked 상태를 모두 검사한다.
    t._overlay.set_locked(True)
    t._sync_warn_btn()
    assert t.warn_lock_btn.text() == "경고 위치 잠금"
    assert t.warn_lock_btn.isChecked()
    t.warn_lock_btn.click()
    assert t._overlay.locked is False  # 해제 → 위치 조정(샘플 표시)
    assert t.warn_lock_btn.text() == "경고 위치 잠금"
    assert not t.warn_lock_btn.isChecked()
    t.warn_lock_btn.click()
    assert t._overlay.locked is True  # 고정 → 경고만 표시(클릭 통과)
    assert t.warn_lock_btn.text() == "경고 위치 잠금"
    assert t.warn_lock_btn.isChecked()
    t.shutdown()


def test_upcoming_hidden_when_option_off(monkeypatch):
    """'다음 패턴 보기'가 꺼져 있으면 보스가 식별돼도 목록 오버레이는 뜨지 않는다."""
    _app()
    from mabinogi_addon.ui import boss_tab as bt_mod
    from mabinogi_addon.ui.boss_tab import BossTab

    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: {"name": "x"})
    t = BossTab(_Watcher())
    t._region = {"x": 0, "y": 0, "w": 150, "h": 36}
    t.show_upcoming.setChecked(False)
    monkeypatch.setattr(t, "_grab_rect", lambda *a: np.zeros((36, 150, 3), np.uint8))
    monkeypatch.setattr(t, "_show_preview", lambda *a: None)
    monkeypatch.setattr(bt_mod, "identify", lambda *a, **k: "lenen_miir")
    monkeypatch.setattr(bt_mod, "read_percent", lambda *a, **k: 90)
    for _ in range(4):
        t._tick()
    assert not t._upcoming.isVisible()
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
