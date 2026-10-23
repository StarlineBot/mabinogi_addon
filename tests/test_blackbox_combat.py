"""블랙박스 녹화 방식(명세 12.2): 평소 녹화 / 전투 녹화."""
import os
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from mabinogi_addon.blackbox_combat import CombatGate, GRACE_SECONDS


def test_boss_bar_starts_recording_and_stops_sixty_seconds_after_it_disappears():
    gate = CombatGate()
    assert GRACE_SECONDS == 60
    assert gate.update(0, False, True) is False and gate.state == 'waiting'
    assert gate.update(1, True, True) is True and gate.state == 'recording'
    assert gate.update(2, False, True) is True and gate.state == 'grace' and gate.grace_left == 59
    assert gate.update(30, False, True) is True and gate.grace_left == 31
    assert gate.update(1 + 60, False, True) is False and gate.state == 'waiting'   # 사라지고 60초 뒤 정지
    assert gate.update(70, True, True) is True and gate.state == 'recording'        # 다시 보이면 이어서


def test_background_keeps_previous_combat_state_without_spending_grace():
    gate = CombatGate()
    gate.update(0, True, True)
    gate.update(10, False, True)                     # 유예 시작(50초 남음)
    assert gate.update(500, None, True) is True        # 게임이 뒤 → 판정 불가 → 직전 상태 유지
    assert gate.state == 'grace' and gate.grace_left == 50
    assert gate.update(501, False, True) is True and gate.grace_left == 49
    waiting = CombatGate()
    assert waiting.update(0, None, True) is False and waiting.state == 'waiting'


def test_unregistered_boss_region_never_records():
    gate = CombatGate()
    assert gate.update(0, True, False) is False and gate.state == 'unregistered'


def test_record_mode_is_saved_and_restored(tmp_path):
    from mabinogi_addon import config
    path = tmp_path / 'config.json'
    assert 'recordMode' not in config.load_blackbox_preferences(path)          # 기본은 평소 녹화
    config.save_blackbox_preference('recordMode', 'combat', path)
    assert config.load_blackbox_preferences(path)['recordMode'] == 'combat'
    with pytest.raises(ValueError):
        config.save_blackbox_preference('recordMode', 'sometimes', path)


def _controller(monkeypatch, mode, boss):
    from mabinogi_addon.ui import blackbox_controller as module
    from mabinogi_addon.blackbox_combat import CombatGate
    monkeypatch.setattr(module, 'is_creator', lambda: True)
    c = module.BlackboxController.__new__(module.BlackboxController)
    c.window, c.panel, c._mode, c._gate = NS(_closing=False, boss_tab=boss), None, mode, CombatGate()
    return c


def test_controller_gates_recording_only_in_combat_mode(monkeypatch):
    boss = NS(has_region=lambda: True, is_boss_present=lambda: False)
    always = _controller(monkeypatch, 'always', boss)
    always.events = NS(foreground=True)
    assert always._combat_record(True) is True                         # 평소 녹화 동작 불변
    combat = _controller(monkeypatch, 'combat', boss)
    combat.events = NS(foreground=True)
    assert combat._combat_record(True) is False                         # 보스바 없음 → 녹화 안 함
    boss.is_boss_present = lambda: True
    assert combat._combat_record(True) is True
    unregistered = _controller(monkeypatch, 'combat', NS(has_region=lambda: False, is_boss_present=lambda: True))
    unregistered.events = NS(foreground=True)
    assert unregistered._combat_record(True) is False and unregistered._gate.state == 'unregistered'


def test_combat_badge_and_status_text():
    from mabinogi_addon.ui.blackbox_controller import blackbox_badge, combat_text
    gate = CombatGate()
    service = NS(enabled=True, status='paused')
    gate.update(0, False, True)
    assert combat_text(gate) == '전투 대기 · 보스 체력바가 보이면 녹화해요'
    assert blackbox_badge(service, 0, gate) == ('블랙박스: 전투 대기', 'neutral')
    gate.update(1, True, True)
    assert combat_text(gate) == '보관 중 · 전투'
    assert blackbox_badge(NS(enabled=True, status='recording'), 184_000_000, gate)[0] == '블랙박스: 보관 중 · 전투 3:04'
    gate.update(2, False, True)
    assert combat_text(gate) == '보관 중 · 전투 종료 대기 59초'
    assert blackbox_badge(service, 0, gate)[0] == '블랙박스: 전투 종료 대기 59초'
    assert blackbox_badge(NS(enabled=True, status='recording'), 60_000_000)[0] == '블랙박스: 보관 중 1:00'  # 평소 녹화 불변
