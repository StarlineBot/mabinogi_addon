"""0.35.1 최적화를 꺼도 패스트핑은 그대로(사용자 결정) — 게임 중에 최적화를 끄면 게임이 꺼지던 문제.

제보: 게임을 켠 채 최적화를 끄면 '네트워크 재연결' 확인 → 예 → TcpAckFrequency·자동 조정 원복 + Restart-NetAdapter
→ 인터넷이 끊겨 게임 종료. 이제 최적화 끄기는 게임 여부와 관계없이 CPU·우선순위·그래픽만 되돌리고(확인 창·재연결 없음),
패스트핑 되돌리기는 상세 설정 [패스트핑 되돌리기](게임이 꺼져 있을 때만)에서만 한다.
"""
import json

import pytest
from PySide6.QtWidgets import QMessageBox

from mabinogi_addon.optimization.engine import FASTPING_KEPT, Engine
from mabinogi_addon.optimization.session import Recovery
from mabinogi_addon.ui import optimization_controller as module
from test_fastping_game_running import GameBackend
from test_navigation import window  # noqa: F401  (픽스처)
from test_optimization import GUID

ACK = dict(kind='ack', target=GUID, old=None, applied=1, state='applied')
CPU = dict(kind='priority', target={'pid': 1, 'birth': '1'}, old=0x20, applied=0x80, state='applied')


def _applied(tmp_path):
    """게임이 꺼진 상태에서 패스트핑 + 우선순위를 적용한 엔진(재연결 1회)."""
    b = GameBackend(running=False)
    r = Recovery(tmp_path / 'j.json', b, lambda: True)
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=False, count=None, adapter=GUID, tcp=True, rss=False, priority=False, auto=False))
    e.thread.join(5)
    assert b.restarts == [GUID] and b.values[('ack', json.dumps(GUID))] == 1
    return b, r, e


@pytest.mark.parametrize('game', [True, False])
def test_turning_off_never_reconnects_and_keeps_fastping(tmp_path, game):
    b, r, e = _applied(tmp_path)
    b.current[0] = {'pid': 9, 'birth': '9'} if game else None
    assert e.stop_and_restore(network=False, network_kept=True)
    e.thread.join(5)
    assert b.restarts == [GUID]  # 재연결 없음
    assert b.values[('ack', json.dumps(GUID))] == 1  # 패스트핑 그대로
    assert any(i['kind'] == 'ack' for i in r.pending)  # 기록 유지(나중에 되돌릴 수 있게)
    assert FASTPING_KEPT in e.status and '원복 대기' not in e.status
    # 상세 설정 [패스트핑 되돌리기]만 네트워크를 되돌린다(재연결 1회, 기록 정리)
    assert e.restore_network()
    e.thread.join(5)
    assert b.restarts == [GUID, GUID] and not r.pending


def _controller(window, monkeypatch, game):
    w, app = window
    c = w.optimization_tools
    monkeypatch.setattr(module, 'optimization_available', lambda: True)
    c.refresh_access()
    if c.panel is None or not c._can_start():
        pytest.skip('최적화 화면 없음(로그인 필요 환경)')
    monkeypatch.setattr(c, '_game_running', lambda: game[0])
    return w, c


@pytest.mark.parametrize('running', [True, False])
def test_toggle_off_restores_cpu_only_without_prompt(window, monkeypatch, running):
    w, c = _controller(window, monkeypatch, [running])
    calls = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: pytest.fail('최적화 끄기는 묻지 않음'))
    monkeypatch.setattr(c.engine, 'restore_network', lambda **k: pytest.fail('최적화 끄기는 재연결하지 않음'))
    monkeypatch.setattr(c.engine, 'stop_and_restore', lambda **k: calls.append(k))
    c.recovery.items = [dict(CPU), dict(ACK)]
    try:
        c._tick()
        assert c.panel.toggle.isChecked()
        c.panel.toggle.click()
        assert calls == [dict(network=False, network_kept=True)]
        c.recovery.items = [dict(ACK)]  # CPU는 되돌려졌고 패스트핑 기록은 남음
        c._tick()
        assert not c.panel.toggle.isChecked() and '원복 대기' not in c.panel.toggle.text()
        assert w._optimization_badge.isHidden()
    finally:
        c.recovery.items = []


def test_revert_button_only_when_game_off_and_guarded(window, monkeypatch):
    game = [True]
    w, c = _controller(window, monkeypatch, game)
    d = c.panel
    calls, asked = [], []
    monkeypatch.setattr(c.engine, 'restore_network', lambda **k: calls.append(k))
    c.recovery.items = [dict(ACK)]
    try:
        c._tick()
        # 게임 실행 중: 보이지만 회색 + 이유 툴팁, 눌러도 아무것도 안 함
        assert not d.fastping_revert.isHidden() and not d.fastping_revert.isEnabled()
        assert d.fastping_revert.toolTip() == '인터넷이 끊기면 게임이 종료돼요 · 게임을 끈 뒤 눌러 주세요'
        c._revert_fastping()
        assert calls == []
        # 게임 꺼짐: 활성 → 확인 → 재연결 1회
        game[0] = False
        c._tick()
        assert d.fastping_revert.isEnabled()
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: asked.append(a[1]) or QMessageBox.StandardButton.Yes)
        d.fastping_revert.click()
        assert asked == ['패스트핑 되돌리기'] and calls == [{'accept_normalized': False}]
        # 확인 창이 떠 있는 사이 게임이 켜지면 재연결하지 않는다
        def yes_but_game_started(*a, **k):
            game[0] = True
            return QMessageBox.StandardButton.Yes
        game[0] = False
        monkeypatch.setattr(QMessageBox, 'question', yes_but_game_started)
        c._revert_fastping()
        assert len(calls) == 1
        # 거절하면 아무것도 안 함
        game[0] = False
        monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.No)
        c._revert_fastping()
        assert len(calls) == 1
    finally:
        c.recovery.items = []
    c._tick()
    assert d.fastping_revert.isHidden()  # 패스트핑 기록이 없으면 숨김


def test_other_paths_never_restore_network(window, monkeypatch):
    """자동 적용 끄기·앱 종료 준비에서도 네트워크 원복·재연결이 없다."""
    w, c = _controller(window, monkeypatch, [False])
    calls = []
    monkeypatch.setattr(c.engine, 'restore_network', lambda **k: pytest.fail('네트워크 원복 금지'))
    monkeypatch.setattr(c.engine, 'stop_and_restore', lambda **k: calls.append(k))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: pytest.fail('확인 창 금지'))
    c.recovery.items = [dict(CPU), dict(ACK)]
    try:
        c._tick()
        c.panel.auto.setChecked(True)
        c.panel.auto.setChecked(False)  # 최적화 사용 끄기 → 지금 적용분 원복
        assert calls and all(k == dict(network=False, network_kept=True) for k in calls)
    finally:
        c.recovery.items = []
    # 앱 종료 준비: 엔진 stop(CPU만) — 네트워크 원복 경로를 부르지 않는다
    stops = []
    monkeypatch.setattr(c.engine, 'stop', lambda: stops.append(1))
    monkeypatch.setattr(c, 'stop_frames', lambda *a, **k: None)
    c.recovery.items = [dict(ACK)]
    try:
        c.closing = False
        c.prepare_close()
        assert stops == [1]
    finally:
        c.recovery.items = []
        c.closing = False
