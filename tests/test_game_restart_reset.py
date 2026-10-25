"""게임 종료·재시작(프로세스 기준) 때 추적 상태 초기화(2026-10-25 사용자 결정 A: 내부 시계 추적기 전부)."""
from PySide6.QtGui import QPixmap

from mabinogi_addon.tracker.game_session import GONE_GRACE_S, GameSession
from mabinogi_addon.ui.overlay import OverlayItem
from test_navigation import window  # noqa: F401  (픽스처)

GAME = (1234, '133500000000000000')
NEW = (5678, '133500000099999999')


def test_session_resets_only_on_process_change_or_exit():
    s = GameSession()
    assert s.update(None, 0) is None                 # 게임 전: 지울 것 없음
    assert s.update(GAME, 1) is None                 # 처음 본 게임
    assert s.update(GAME, 2) is None                 # 알트탭·가림: 같은 프로세스 → 유지
    assert s.update(NEW, 3) == 'restart'             # PID·시작 시각이 다른 새 프로세스 → 바로
    assert s.update(None, 4) is None                 # 프로세스 없음: 유예 중
    assert s.update(None, 4 + GONE_GRACE_S - 0.1) is None
    assert s.update(NEW, 4 + GONE_GRACE_S - 0.05) is None  # 잠깐 안 잡혔다 같은 프로세스 → 지우지 않음
    assert s.update(None, 10) is None
    assert s.update(None, 10 + GONE_GRACE_S) == 'exit'
    assert s.update(None, 20) is None                # 한 번만
    assert s.update(GAME, 21) is None                # 종료 뒤 새 게임은 이미 비운 상태에서 시작


def _seed(w):
    """ACTIVE 버프가 떠 있고 보스·투아림·도르카 값이 남은 상태."""
    w.buff_overlay.set_items([OverlayItem(QPixmap(8, 8), '4:30')])
    w.buff_overlay.show()
    w.boss_tab._tracker = object()
    w.boss_tab._cur_boss = 'boss'
    w.boss_tab._stable_hp = 70
    w.tuarim_tab._stable_value = 80
    w.dorcha_tab._set_value(12)


def _run(w, monkeypatch, sequence):
    restarts = []
    monkeypatch.setattr(w, '_start_buff_tracking', lambda: restarts.append('buff'))
    monkeypatch.setattr(w, '_start_debuff_tracking', lambda: restarts.append('debuff'))
    for now, identity in sequence:
        monkeypatch.setattr(w, '_game_identity', lambda identity=identity: identity)
        w._check_game_process(now)
    return restarts


def _cleared(w):
    return (not w.buff_overlay.isVisible() and w.buff_overlay._items == [] and w.boss_tab._tracker is None
            and w.boss_tab._cur_boss is None and w.boss_tab._stable_hp is None and w.tuarim_tab._stable_value is None
            and w.dorcha_tab.preview.value is None)


def test_game_exit_clears_trackers_and_hides_overlays(window, monkeypatch):
    w = window[0]
    _seed(w)
    restarts = _run(w, monkeypatch, [(100, GAME), (101.5, None), (103, None)])
    assert restarts == [] and w.buff_overlay.isVisible() and w.boss_tab._stable_hp == 70  # 유예 중
    restarts = _run(w, monkeypatch, [(105, None)])
    assert restarts == ['buff', 'debuff']  # 엔진 새로 만듦 → 상태 ABSENT·앵커 기록 초기화
    assert _cleared(w)


def test_new_process_clears_previous_buffs(window, monkeypatch):
    w = window[0]
    _run(w, monkeypatch, [(100, GAME)])
    _seed(w)
    restarts = _run(w, monkeypatch, [(101.5, NEW)])
    assert restarts == ['buff', 'debuff'] and _cleared(w)


def test_alt_tab_same_process_keeps_state(window, monkeypatch):
    w = window[0]
    _seed(w)
    restarts = _run(w, monkeypatch, [(100, GAME), (101.5, GAME), (103, GAME), (110, GAME)])
    assert restarts == [] and w.buff_overlay.isVisible() and w.boss_tab._stable_hp == 70 and w.tuarim_tab._stable_value == 80


def test_check_is_throttled_to_about_once_a_second(window, monkeypatch):
    w = window[0]
    calls = []
    monkeypatch.setattr(w, '_game_identity', lambda: calls.append(1) or GAME)
    for now in (200, 200.3, 200.7, 201.0, 201.2):
        w._check_game_process(now)
    assert len(calls) == 2
