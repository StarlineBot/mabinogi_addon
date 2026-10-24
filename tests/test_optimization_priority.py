"""최적화 명세 13.7: 게임 우선순위 높음 — 원본 기록·원복·외부 변경 존중·되돌아가면 제한적으로 다시 걸기·확인 불가 처리."""
import json
import threading

import pytest

from mabinogi_addon.optimization import engine as engine_module
from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.optimization.session import Recovery
from mabinogi_addon.system.process_priority import HIGH, NORMAL, ABOVE_NORMAL, REALTIME, Unconfirmed
from mabinogi_addon.system.optimization import WindowsOptimization
from test_optimization import Backend, TARGET, _wait

KEY = ('priority', json.dumps(TARGET, sort_keys=True))


class PriorityBackend(Backend):
    def __init__(self):
        super().__init__()
        self.values[KEY] = NORMAL
        self.unconfirmed = False
        self.alive_flag = [True]
        self.game = lambda: TARGET
        self.processes = lambda: []
        self.governor_running = lambda: False
        self.alive = lambda target: self.alive_flag[0]

    def read(self, kind, target):
        if kind == 'priority' and self.unconfirmed:
            raise Unconfirmed('확인 불가(API 보통 · 목록 높음)')
        return super().read(kind, target)


@pytest.fixture
def setup(tmp_path):
    backend = PriorityBackend()
    recovery = Recovery(tmp_path / 'journal.json', backend, lambda: True)
    return recovery, backend


OPTIONS = dict(cpu=False, count=None, adapter=None, tcp=False, rss=False, priority=True)


def test_validate_accepts_priority_classes_but_writes_never_realtime():
    WindowsOptimization.validate('priority', TARGET, HIGH)
    WindowsOptimization.validate('priority', TARGET, REALTIME)  # 원본으로는 기록 가능(되돌리기용)
    with pytest.raises(ValueError):
        WindowsOptimization.validate('priority', TARGET, 0x1234)


def test_priority_only_session_applies_high_and_restores_on_game_exit(setup):
    r, b = setup
    e = Engine(b, r, lambda: True)
    assert e.start(OPTIONS)
    assert _wait(lambda: b.values[KEY] == HIGH)
    assert _wait(lambda: '게임 우선순위: 높음 적용 · 확인 완료' in e.status)
    item = r.items[0]
    assert item['kind'] == 'priority' and item['old'] == NORMAL and item['applied'] == HIGH and item['state'] == 'applied'
    b.alive_flag[0] = False
    e.thread.join(5)
    assert not e.busy and not r.pending and b.values[KEY] == NORMAL  # 세션 끝: 원래 값으로


def test_already_high_is_left_alone(setup):
    r, b = setup
    b.values[KEY] = HIGH
    e = Engine(b, r, lambda: True)
    assert e.start(OPTIONS)
    assert _wait(lambda: '이미 높음 · 그대로 둠' in e.status)
    assert not b.writes and not r.items
    e.stop(); e.thread.join(5)


def test_external_tool_change_is_not_overwritten_or_restored(setup):
    r, b = setup
    e = Engine(b, r, lambda: True)
    assert e.start(OPTIONS)
    assert _wait(lambda: b.values[KEY] == HIGH)
    b.values[KEY] = ABOVE_NORMAL  # 다른 도구가 바꿈
    assert _wait(lambda: '다른 도구가 게임 우선순위를 바꿨어요' in e.status, 6)
    assert r.items[0]['state'] == 'released'
    writes = len(b.writes)
    b.alive_flag[0] = False
    e.thread.join(5)
    assert b.values[KEY] == ABOVE_NORMAL and len(b.writes) == writes  # 원복도 하지 않음


def test_reverted_to_original_is_reapplied_with_limit(setup, monkeypatch):
    monkeypatch.setattr(engine_module, 'PRIORITY_REAPPLY_LIMIT', 1)
    r, b = setup
    e = Engine(b, r, lambda: True)
    assert e.start(OPTIONS)
    assert _wait(lambda: b.values[KEY] == HIGH)
    b.values[KEY] = NORMAL  # 게임 등이 되돌림
    assert _wait(lambda: b.values[KEY] == HIGH, 6)  # 다시 건다
    b.values[KEY] = NORMAL
    assert _wait(lambda: '계속 보통(으)로 돌아가요' in e.status, 6)  # 한도 뒤에는 다투지 않음
    assert b.values[KEY] == NORMAL
    e.stop(); e.thread.join(5)


def test_unconfirmed_reading_never_reported_as_failure_and_restore_still_writes_original(setup):
    r, b = setup
    real_write = b.write
    def write(kind, target, value):
        real_write(kind, target, value)
        if kind == 'priority' and value == HIGH:
            b.unconfirmed = True  # 쓴 뒤 두 읽기 경로가 다름(2026-10-24 실사용 같은 상황)
    b.write = write
    e = Engine(b, r, lambda: True)
    assert e.start(OPTIONS)
    assert _wait(lambda: '높음 적용 · 확인 불가' in e.status)
    assert '미적용' not in e.status and '일부 미적용' not in e.status
    assert r.items[0]['state'] == 'applied'
    b.alive_flag[0] = False
    e.thread.join(5)
    assert not r.pending and b.values[KEY] == NORMAL  # 확인 불가여도 원본을 다시 써서 '높음'을 남기지 않음


def test_unconfirmed_before_apply_does_not_change_anything(setup):
    r, b = setup
    b.unconfirmed = True
    e = Engine(b, r, lambda: True)
    assert e.start(OPTIONS)
    assert _wait(lambda: '게임 우선순위 확인 불가 · 적용하지 않았어요' in e.status)
    assert not b.writes and not r.items
    e.stop(); e.thread.join(5)


def test_journal_with_priority_survives_restart_and_restores(tmp_path):
    b = PriorityBackend()
    r = Recovery(tmp_path / 'journal.json', b, lambda: True)
    assert r.apply('priority', TARGET, HIGH) == 'applied'
    again = Recovery(tmp_path / 'journal.json', b, lambda: True)  # 앱 재실행
    assert not again.corrupt and again.pending[0]['kind'] == 'priority'
    assert again.restore() == [] and b.values[KEY] == NORMAL and not again.pending


def test_panel_checkbox_default_on_selection_remembered_and_badge_counts_priority(tmp_path):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon import config
    from mabinogi_addon.ui.optimization_controller import optimization_badge
    from mabinogi_addon.ui.optimization_panel import OptimizationPanel
    app = QApplication.instance() or QApplication([])
    panel = OptimizationPanel()
    try:
        assert panel.priority.text() == '게임 우선순위 높음' and panel.priority.isChecked()
    finally:
        panel.deleteLater()
    path = tmp_path / 'config.json'
    config.save_optimization_selection(dict(cpu=False, priority=True, tcp=False, rss=False), path)
    assert config.load_optimization_selection(path)['priority'] is True
    recovery = SimpleNamespace(corrupt=False, restart_targets=set(),
                               pending=[dict(kind='priority', state='applied')])
    busy = SimpleNamespace(busy=True, task='session', cancel=threading.Event())
    assert optimization_badge(recovery, busy) == ('최적화: 적용 중', 'neutral')


def test_game_resets_on_map_moves_are_reapplied_each_time_by_default(setup):
    # 2026-10-24 실측: 재접속·맵 이동마다 게임이 '보통'으로 되돌린다. 기본 한도에서 여러 번 이어져도 계속 다시 건다.
    assert engine_module.PRIORITY_REAPPLY_LIMIT >= 20
    r, b = setup
    e = Engine(b, r, lambda: True)
    assert e.start(OPTIONS)
    assert _wait(lambda: b.values[KEY] == HIGH)
    for _ in range(4):
        b.values[KEY] = NORMAL  # 맵 이동
        assert _wait(lambda: b.values[KEY] == HIGH, 6)
    assert '계속' not in e.status and r.items[0]['state'] == 'applied'
    e.stop(); e.thread.join(5)
