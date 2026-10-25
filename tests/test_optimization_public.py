"""최적화 공개 전환(명세 13.15): 로그인 사용자 공개·수집 모드는 제작자만, 미룬 패스트핑은 게임이 끝나면 적용, 근거 줄 삭제, 알파·베타 문구 없음."""
import json
from types import SimpleNamespace as NS

from PySide6.QtWidgets import QAbstractButton, QGroupBox, QLabel

from mabinogi_addon import feature_access
from mabinogi_addon.optimization.engine import Engine, TCP_DEFERRED
from mabinogi_addon.optimization.result_summary import summarize
from mabinogi_addon.optimization.session import Recovery
from mabinogi_addon.ui import optimization_controller as module
from test_navigation import window  # noqa: F401  (픽스처)
from test_optimization import Backend, TARGET, GUID, _wait

NORMAL = 0x20


class GameBackend(Backend):
    def __init__(self):
        super().__init__()
        self.current = [TARGET]
        self.values[('priority', json.dumps(TARGET, sort_keys=True))] = NORMAL
        self.values[('ack', json.dumps(GUID))] = None
        self.values[('autotuning', json.dumps('global'))] = 'restricted'
        self.game = lambda: self.current[0]
        self.alive = lambda target: self.current[0] == target
        self.processes = lambda: []
        self.governor_running = lambda: False


def _engine(tmp_path, auto=False):
    b = GameBackend()
    r = Recovery(tmp_path / 'j.json', b, lambda: True)
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=False, count=None, adapter=GUID, tcp=True, rss=False, priority=True, auto=auto))
    return b, r, e


def _tcp_writes(b):
    return [kind for kind, _t, _v in b.writes if kind in ('ack', 'autotuning')]


REQ = dict(priority=True, tcp=True)


def test_manual_session_applies_deferred_fastping_after_game_exit(tmp_path):
    b, r, e = _engine(tmp_path)
    assert _wait(lambda: e.outcome.get('priority') == ('ok', '') and e.outcome.get('tcp') == ('deferred', TCP_DEFERRED))
    assert TCP_DEFERRED == '게임을 끄면 적용해요' and not _tcp_writes(b)
    assert '• 패스트핑 · 게임을 끄면 적용해요' in summarize(e, r, REQ)[2]
    b.current[0] = None  # 게임 종료 → 우선순위 되돌림 → 패스트핑 적용
    e.thread.join(6)
    assert not e.busy and e.session_end == 'network_only'
    kinds = [kind for kind, _t, _v in b.writes]
    assert kinds.index('ack') > max(i for i, k in enumerate(kinds) if k == 'priority')  # CPU(우선순위) 원복 뒤 적용
    assert b.values[('priority', json.dumps(TARGET, sort_keys=True))] == NORMAL
    assert e.outcome == {'tcp': ('ok', '')}
    headline, level, lines = summarize(e, r, REQ, kept_on=True)
    assert headline == '최적화 적용 중' and lines == ['✓ 패스트핑']


def test_turning_off_while_deferred_never_applies_fastping(tmp_path):
    b, r, e = _engine(tmp_path)
    assert _wait(lambda: e.outcome.get('tcp') == ('deferred', TCP_DEFERRED))
    e.stop()
    b.current[0] = None
    e.thread.join(6)
    assert not _tcp_writes(b) and e.session_end == 'cancel'


def test_auto_session_applies_deferred_fastping_when_game_ends_and_keeps_line(tmp_path):
    b, r, e = _engine(tmp_path, auto=True)
    e.auto = True
    assert _wait(lambda: e.outcome.get('tcp') == ('deferred', TCP_DEFERRED) and e.phase == 'applied')
    b.current[0] = None
    assert _wait(lambda: e.phase == 'ended' and e.outcome.get('tcp') == ('ok', ''), 6)
    headline, _level, lines = summarize(e, r, dict(REQ, auto=True))
    assert headline == '게임이 끝나 원래대로 되돌렸어요' and lines == ['↺ 게임 우선순위 · 되돌림', '✓ 패스트핑']
    e.stop(); e.thread.join(5)


def test_fastping_stays_deferred_if_game_restarts_before_applying(tmp_path):
    b, r, e = _engine(tmp_path)
    assert _wait(lambda: e.outcome.get('tcp') == ('deferred', TCP_DEFERRED))
    other = {'pid': 456, 'birth': '1'}
    b.values[('priority', json.dumps(other, sort_keys=True))] = NORMAL
    original = b.game
    calls = []
    def game():  # 끝난 게임을 확인한 직후 새 게임이 켜짐
        calls.append(1)
        return other if b.current[0] is None and len(calls) > 1 else original()
    b.alive = lambda target: target == TARGET and b.current[0] == TARGET
    b.game = game
    b.current[0] = None
    e.thread.join(6)
    assert not _tcp_writes(b) and e.outcome['tcp'][0] == 'fail'


# ---- 화면 ----

def _texts(widget):
    texts = [w.text() for w in widget.findChildren(QLabel)] + [w.text() for w in widget.findChildren(QAbstractButton)]
    return texts + [w.title() for w in widget.findChildren(QGroupBox)]


def test_logged_in_user_sees_tab_but_collection_only_for_creator(window, monkeypatch):
    w = window[0]
    c = w.optimization_tools; c.timer.stop()
    user = [None]
    monkeypatch.setattr(module.config, 'load_discord_user', lambda *a: user[0])
    monkeypatch.setattr(feature_access.config, 'load_discord_user', lambda *a: user[0])
    c.refresh_access()
    assert w._tabs.indexOf(c.panel) == -1
    user[0] = {'id': '1234', 'username': 'someone'}
    c.refresh_access()
    assert w._tabs.indexOf(c.panel) >= 0 and c._can_start()
    assert c.panel.collect_box.isHidden()
    c.panel.summary_collect.setChecked(True)
    assert not c.panel.summary_collect.isChecked() and not c._summary_collecting
    user[0] = {'id': feature_access.CREATOR_DISCORD_ID}
    c.refresh_access()
    assert not c.panel.collect_box.isHidden() and c.panel.collect_box.title() == '프레임 수집'


def test_no_alpha_or_beta_words_on_screen_and_no_basis_line(window, monkeypatch):
    from test_cpu_layouts import X9800
    w = window[0]
    c = w.optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True)
    monkeypatch.setattr(module, 'is_creator', lambda: True); c.refresh_access()
    c._apply_inspection(X9800, [])
    assert c.panel.split_detail.text() == '게임 6코어 · 그 외 2코어 (6+2)'
    for widget in (c.panel, w.settings_tab):
        joined = ' '.join(_texts(widget))
        assert '알파' not in joined and '베타' not in joined and '근거' not in joined
    assert '로그인하면 블랙박스와 최적화를 사용할 수 있어요.' in _texts(w.settings_tab)


def test_auto_game_end_shows_applying_line_when_fastping_was_applied_at_start(tmp_path):
    # QA(0.22.0): 시작 때 이미 적용한 패스트핑은 게임 종료 뒤에도 13.13 '적용 중' 줄(결과 줄 ✓는 미룬 것을 이번 종료 때 적용한 경우만)
    b = GameBackend()
    b.current[0] = None  # 게임 없을 때 시작 → 패스트핑 즉시 적용
    r = Recovery(tmp_path / 'j.json', b, lambda: True)
    e = Engine(b, r, lambda: True)
    assert e.start(dict(cpu=False, count=None, adapter=GUID, tcp=True, rss=False, priority=True, auto=True))
    e.auto = True
    assert _wait(lambda: e.outcome.get('tcp') == ('ok', '') and e.phase == 'waiting')
    b.current[0] = TARGET
    assert _wait(lambda: e.phase == 'applied' and e.outcome.get('priority') == ('ok', ''), 6)
    b.current[0] = None
    assert _wait(lambda: e.phase == 'ended', 6)
    headline, _level, lines = summarize(e, r, dict(REQ, auto=True))
    assert headline == '게임이 끝나 원래대로 되돌렸어요'
    assert lines == ['↺ 게임 우선순위 · 되돌림', '• 패스트핑 · 적용 중 (최적화를 끄면 되돌려요)']
    e.stop(); e.thread.join(5)
