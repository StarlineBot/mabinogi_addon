"""0.32.0: 버프별 추적 끔(실행 중 = 재시작 뒤) + 버프·디버프 '오버레이 창 보이기'(끄면 창만 숨김, 탐지·알림 계속).

예전엔 실행 중에 '오버레이에 표시'를 끄면 engine.set_order만 바뀌어 표시만 숨고, 시작 때 만든 상태 기계로 알림이 계속 울렸다.
재시작 뒤에는 탐지 템플릿에서 빠져 알림도 없었다(같은 설정이 다르게 동작).
"""
import pytest
from PySide6.QtWidgets import QListWidget

from mabinogi_addon import config
from mabinogi_addon.ui import main_window
from mabinogi_addon.ui.buff_controller import BuffController
from mabinogi_addon.ui.buff_tab import ANCHOR_ID
from test_navigation import window  # noqa: F401  (픽스처)


class _Source:
    def close(self):
        pass


@pytest.fixture
def live(window, monkeypatch):
    """캡처·작업 스레드 없이 추적 시작 경로(템플릿·컨트롤러 만들기)만 돌린다."""
    w, app = window
    monkeypatch.setattr(main_window, "create_live_source", lambda *a, **k: _Source())
    monkeypatch.setattr(BuffController, "start", lambda self, *a, **k: None)
    monkeypatch.setattr(BuffController, "stop", lambda self, *a, **k: None)
    raw = config._read_local_config()
    for name in ("buffTracker", "debuffTracker"):
        raw.setdefault(name, {}).update(enabled=True, captureRegion={"x": 10, "y": 20, "w": 80, "h": 40})
    raw.setdefault("general", {}).setdefault("setupSelection", {}).update(buff=True, debuff=True)
    config._write_local_config(raw)
    w._start_buff_tracking()
    w._start_debuff_tracking()
    assert w.buff_controller is not None and w.debuff_controller is not None
    return w, app


def _tracked(w):
    return set(w._engine._machines)


def test_untracking_while_running_equals_after_restart(live):
    w, app = live
    tab = w.buff_tab
    target = tab._order[2]
    assert target in _tracked(w)
    tab.buff_list.setCurrentRow(tab._rows().index(target))
    tab.display_check.setChecked(False)  # 실행 중 '이 버프 추적' 끔
    running = _tracked(w)
    assert target not in running and target not in w.buff_controller._warn_gone_ids  # 탐지·알림·사라짐 경고 없음
    w._start_buff_tracking()  # 재시작 뒤와 같다
    assert _tracked(w) == running
    tab.display_check.setChecked(True)  # 다시 켜면 즉시 탐지 대상
    assert target in _tracked(w) and ANCHOR_ID in _tracked(w)


def test_overlay_window_off_hides_but_keeps_tracking_and_alerts(live):
    w, app = live
    alerts = []
    w._on_buff_alert = alerts.append
    w.buff_controller._on_alert = alerts.append
    w.buff_tab.window_check.setChecked(False)
    w.debuff_tab.window_check.setChecked(False)
    assert config.load_overlay_windows() == (False, False)
    for controller, overlay in ((w.buff_controller, w.buff_overlay), (w.debuff_controller, w.debuff_overlay)):
        controller._game_active = True
        controller._items = [object()]
        controller._apply_visibility()  # 게임 포그라운드 + 보일 항목이 있어도
        assert not overlay.isVisible()
    w.buff_controller._on_alerted(["buff_x"])  # 일시정지와 달리 알림은 계속
    assert alerts == [["buff_x"]]
    assert w._debuff_engine is not None  # 디버프 추적도 그대로
    # 다시 만들어도(재시작 뒤) 창 끔 유지
    w._start_buff_tracking()
    w._start_debuff_tracking()
    assert not w.buff_controller._window_visible and not w.debuff_controller._window_visible
    w.buff_tab.window_check.setChecked(True)
    w.buff_controller._game_active = True
    w.buff_controller._items = [object()]
    w.buff_controller._apply_visibility()
    assert w.buff_overlay.isVisible()
    w.buff_overlay.hide()


def test_overlay_window_setting_saved_per_feature():
    assert config.load_overlay_windows() == (True, True)  # 기본 켜짐
    config.set_buff_window_visible(False)
    assert config.load_overlay_windows() == (False, True)
    config.set_debuff_window_visible(False)
    config.set_buff_window_visible(True)
    assert config.load_overlay_windows() == (True, False)


def test_debuff_untracked_row_dimmed(window):
    w, app = window
    tab = w.debuff_tab
    did = tab._order[1]
    tab.debuff_list.setCurrentRow(1)
    tab.display_check.setChecked(False)
    item = tab.debuff_list.item(1)
    assert item.text().endswith("· 추적 안 함") and not tab.warn_gone_check.isEnabled()
    tab.display_check.setChecked(True)
    assert not tab.debuff_list.item(1).text().endswith("추적 안 함")
    assert isinstance(tab.debuff_list, QListWidget) and did
