"""디버프 오버레이를 보스바가 보일 때만(사용자 요청 2026-11-06) — 보스 존재 신호를 그대로 따름(0.49.0: 추가 10초 유예 없앰),
판정 불가는 유지, 영역 없음·옵션 끔은 항상."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from mabinogi_addon import config
from mabinogi_addon.debuff_gate import DebuffOverlayGate


def run(gate, now, present, *, enabled=True, registered=True):
    return gate.update(now, enabled=enabled, registered=registered, present=present)


def test_follows_boss_presence_hides_with_it_and_returns_immediately():
    """사용자 결정(11-14, #231 실측 12~13초 남음): 보스바 안 보임 = 디버프 안 보임 — 존재 신호가 꺼지는 그 판정에 같이 숨김."""
    g = DebuffOverlayGate()
    assert run(g, 0.0, True)  # 보스바 보임 → 표시
    assert run(g, 0.7, True)
    assert not run(g, 1.4, False)  # 존재 신호가 꺼지면(그쪽 유예 ~2초 뒤) 바로 숨김 — 추가 유예 없음
    assert not run(g, 30.0, False)
    assert run(g, 30.7, True)  # 다시 보임 → 즉시


def test_blackbox_combat_grace_unchanged():
    from mabinogi_addon.blackbox_combat import GRACE_SECONDS, CombatGate
    assert GRACE_SECONDS == 60.0 and CombatGate().grace == 60.0  # 같은 CombatGate를 쓰는 블랙박스 전투 녹화 유예는 그대로


def test_no_boss_at_start_hides():
    g = DebuffOverlayGate()
    assert not run(g, 0.0, False)  # 마을: 보스 없음 → 숨김


def test_unregistered_region_or_option_off_always_shows():
    g = DebuffOverlayGate()
    assert run(g, 0.0, False, registered=False)
    assert run(g, 100.0, False, enabled=False)
    assert run(g, 200.0, None, enabled=False)


def test_game_inactive_keeps_previous_state():
    g = DebuffOverlayGate()
    assert run(g, 0.0, True)
    assert run(g, 60.0, None)  # 뒤로 감(판정 불가) — 유예 시간도 흐르지 않음
    assert not run(g, 65.0, False)  # 돌아와서 보스 없음 → 숨김
    h = DebuffOverlayGate()
    assert not run(h, 0.0, False)
    assert not run(h, 5.0, None)  # 숨김 상태도 그대로 유지


def test_option_saved_default_on(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{}", encoding="utf-8")
    assert config.load_debuff_boss_only(path)
    config.set_debuff_boss_only(False, path)
    assert not config.load_debuff_boss_only(path)
    assert json.loads(path.read_text(encoding="utf-8"))["overlay"]["debuffBossOnly"] is False


def test_controller_gate_hides_only_locked_window_and_keeps_detection():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.buff_controller import BuffController
    from mabinogi_addon.ui.overlay import BuffOverlay
    QApplication.instance() or QApplication([])
    overlay = BuffOverlay()
    overlay.set_locked(True)
    ctrl = BuffController(overlay, catalog={}, show_duration={})
    ctrl._game_active = True
    ctrl._items = [object()]
    ctrl._apply_visibility()
    assert overlay.isVisible()
    ctrl.set_gate_visible(False)
    assert not overlay.isVisible()  # 고정 상태: 보스 없으면 숨김
    ctrl._on_foreground_changed(True, False)
    assert not overlay.isVisible()
    ctrl.set_gate_visible(True)
    assert overlay.isVisible()  # 보스바 나타남 → 바로 표시(탐지는 계속 돌던 상태)


def test_main_window_wiring_uses_boss_presence_and_feeds_controller():
    from types import SimpleNamespace

    from mabinogi_addon.ui.main_window import MainWindow
    state = {"present": True, "active": True}
    got = []
    me = SimpleNamespace(
        boss_tab=SimpleNamespace(is_boss_present=lambda: state["present"], has_region=lambda: True),
        _watcher=SimpleNamespace(is_game_active=lambda: state["active"]),
        debuff_controller=SimpleNamespace(set_gate_visible=got.append),
        debuff_tab=SimpleNamespace(window_check=SimpleNamespace(isChecked=lambda: True)),
        _debuff_boss_only=True)
    MainWindow._update_debuff_gate(me)
    assert got[-1] is True
    me._debuff_gate.update(0.0, enabled=True, registered=True, present=False)  # 오래전에 사라짐
    state["present"] = False
    me._debuff_gate._gate._last_seen = -100.0
    MainWindow._update_debuff_gate(me)
    assert got[-1] is False
    state["active"] = False
    MainWindow._update_debuff_gate(me)
    assert got[-1] is False  # 판정 불가 → 유지
    assert MainWindow._debuff_gate_wants_presence(me)  # 보스 존재 판정 필요
    me._debuff_boss_only = False
    assert not MainWindow._debuff_gate_wants_presence(me)
    MainWindow._update_debuff_gate(me)
    assert got[-1] is True  # 옵션 끔 → 항상 표시
