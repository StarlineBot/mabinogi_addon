"""0.41.0 게임 위 정보 표시 — 현재 시각(명세 16절) + FPS 오버레이 깜빡임 수정."""
from __future__ import annotations

import os
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget

from mabinogi_addon.ui import optimization_controller as oc


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


# ---- 현재 시각 ---------------------------------------------------------------------------------
@pytest.mark.parametrize('h,m,s,fmt,sec,expected', [
    (21, 41, 8, '24', True, ('', '21:41:08')),
    (21, 41, 8, '24', False, ('', '21:41')),
    (9, 5, 3, '24', True, ('', '09:05:03')),
    (21, 41, 8, '12', True, ('PM', '9:41:08')),
    (0, 7, 0, '12', False, ('AM', '12:07')),
    (12, 0, 59, '12', True, ('PM', '12:00:59')),
    (11, 59, 59, '12', True, ('AM', '11:59:59')),
])
def test_clock_text(h, m, s, fmt, sec, expected):
    assert oc.clock_text(h, m, s, fmt, sec) == expected


def test_clock_item_reads_the_pc_clock_each_time(monkeypatch):
    """매 갱신마다 시계를 새로 읽는다(앱 안에서 1초씩 더하지 않음) — 형식·초 옵션을 따른다."""
    from PySide6 import QtCore
    times = iter([QtCore.QTime(21, 41, 8), QtCore.QTime(21, 41, 9)])
    monkeypatch.setattr(QtCore.QTime, 'currentTime', staticmethod(lambda: next(times)))
    fake = NS(_clock_format='12', _clock_seconds=True)
    assert oc.OptimizationController._clock_item(fake) == ('현재 시각', '9:41:08', '', 'PM')
    assert oc.OptimizationController._clock_item(fake) == ('현재 시각', '9:41:09', '', 'PM')


def test_clock_is_last_item_and_off_by_default(monkeypatch):
    fake = NS(_metrics=dict(fps=True, cpu=False, gpu=False, memory=True, clock=True))
    fake._clock_item = lambda: ('현재 시각', '21:41:08', '', '')
    items = oc.OptimizationController.overlay_items(fake, 60, {'memory': 2 * 1024 ** 3})
    assert [i[0] for i in items] == ['FPS', '게임 메모리', '현재 시각']
    assert 'clock' in oc.OVERLAY_ITEMS and 'clock' not in oc.METRICS  # OS 지표 수집 대상이 아님
    from mabinogi_addon import config
    config._write_local_config({})
    controller_defaults = {key: key == 'fps' for key in oc.OVERLAY_ITEMS}
    assert controller_defaults['clock'] is False


def test_ampm_is_small_prefix_and_widens_the_item(app):
    from mabinogi_addon.ui.frame_overlay import FrameOverlay
    overlay = FrameOverlay(100)
    try:
        overlay.set_items([('현재 시각', '9:41:08', '')])
        plain = overlay.width()
        overlay.set_items([('현재 시각', '9:41:08', '', 'PM')])
        assert overlay.width() > plain
        assert overlay.items() == [('현재 시각', '9:41:08', '', 'PM')]
        overlay.set_items([('FPS', '60', '')])
        assert overlay.items() == [('FPS', '60', '')]  # 앞글자가 없으면 예전처럼 세 칸
    finally:
        overlay.deleteLater()


def test_panel_names_and_clock_options(app):
    from mabinogi_addon.ui.optimization_panel import OptimizationPanel
    host = QWidget()
    panel = OptimizationPanel(host)
    try:
        assert panel.frames_toggle.text() == '정보 표시'
        assert panel.metric_boxes['clock'].text() == '현재 시각'
        assert [panel.clock_format.itemText(i) for i in range(2)] == ['24시간 (21:41)', '12시간 (PM 9:41)']
        assert panel.clock_seconds.text() == '초 표시' and panel.clock_seconds.isChecked()
        assert not panel.clock_format.isEnabled() and not panel.clock_seconds.isEnabled()  # 현재 시각을 켰을 때만
        panel.set_clock_options_enabled(True)
        assert panel.clock_format.isEnabled() and panel.clock_seconds.isEnabled()
    finally:
        host.deleteLater()


def test_clock_options_are_saved_and_restored(app, monkeypatch):
    from mabinogi_addon import config
    fake = NS(_scale=100, _metrics={k: k in ('fps', 'clock') for k in oc.OVERLAY_ITEMS}, _overlay=None,
              _clock_format='12', _clock_seconds=False)
    config._write_local_config({})
    oc.OptimizationController._save_overlay(fake)
    saved = config._read_local_config()['frameMeter']
    assert saved['clock'] == {'format': '12', 'seconds': False} and saved['metrics']['clock'] is True


def test_home_row_name():
    from mabinogi_addon.ui.home_page import BOTTOM_BOXES
    rows = dict(BOTTOM_BOXES)['최적화']
    assert ('fps', '게임 위 정보', True) in rows


# ---- 깜빡임 ------------------------------------------------------------------------------------
def _stream():
    from mabinogi_addon.optimization.frames import FrameStream
    s = FrameStream(7, 1_000_000)
    s.feed('Application,ProcessID,SwapChainAddress,QPCTime,msBetweenPresents', 100)
    return s


def _batch(s, start, count, arrive, rate=50, source='0x1'):
    """start초부터 rate FPS 이벤트 count개가 arrive초에 한꺼번에(묶여) 도착."""
    for n in range(count):
        stamp = start + n / rate
        s.feed(f'game,7,{source},{round(stamp * 1_000_000)},{1000 / rate:.0f}', arrive)


def test_late_batched_events_keep_fps_and_source():
    """PresentMon 출력이 2.5초 늦게 묶여 와도 fps·대상이 순간 None이 되지 않는다(예전 STALE 2초 → 깜빡임)."""
    s = _stream()
    _batch(s, 100.0, 50, 101.0)
    assert s.snapshot(101.0)['fps'] == pytest.approx(50)
    _batch(s, 101.0, 125, 103.5)  # 101~103.5초 프레임이 묶여 도착(가장 오래된 것 2.5초 지연)
    for now in (103.0, 103.4, 103.6, 105.0, 105.9):  # 다음 묶음(약 2.5초 뒤)까지 기다리는 사이
        snap = s.snapshot(now)
        assert snap['fps'] == pytest.approx(50) and snap['source'] == '0x1', now
    assert s.arrival_stale(106.0) == pytest.approx(3.5)  # 최근 최대 지연 2.5초 + 1초
    assert s.snapshot(107.1)['fps'] is None  # 정말 끊기면(마지막 프레임 뒤 3.5초 넘게) 없음


def test_two_render_targets_still_not_chosen():
    """대상 창이 실제로 둘 이상이면 기존처럼 '고르지 못했어요'(합치지 않음)."""
    s = _stream()
    _batch(s, 100.0, 50, 101.0, source='0x1')
    _batch(s, 100.0, 50, 101.0, source='0x2')
    snap = s.snapshot(102.5)
    assert snap['fps'] is None and snap['source'] is None and '고르지 못했어요' in snap['status']


def test_overlay_keeps_last_value_then_dash_and_hides_only_when_told(app):
    """잠깐 비면(묶임) 마지막 값 유지 → FPS_HOLD초 넘게 계속 없으면 '—' → 숨김은 비활성·일시정지·중지 때만."""
    fake = NS(_last_fps=None, _fps_seen_at=0.0, _overlay=None)
    show = lambda fps, now: oc.OptimizationController._display_fps(fake, fps, now)  # noqa: E731
    assert show(None, 0.0) == (None, False)  # 첫 값 전에는 띄우지 않음(예전과 같음)
    assert show(60.0, 1.0) == (60.0, True)
    assert show(None, 2.5) == (60.0, True)  # 2.5초 늦은 묶음을 기다리는 동안 — 숨기지 않고 값 유지
    assert show(None, 1.0 + oc.FPS_HOLD - 0.1) == (60.0, True)
    assert show(None, 1.0 + oc.FPS_HOLD + 0.1) == (None, True)  # 계속 없음 → '—'
    items = oc.OptimizationController.overlay_items(NS(_metrics=dict(fps=True, cpu=False, gpu=False, memory=False)),
                                                    None, {})
    assert items == [('FPS', '—', '')]
    assert show(58.0, 9.0) == (58.0, True)
    oc.OptimizationController._hide_overlay(fake)  # 게임 비활성·일시정지·대상 경계
    assert show(None, 9.5) == (None, False)  # 다시 보일 때는 새 값부터(옛 값 유지 안 함)


@pytest.mark.parametrize('scale', [100, 150])
def test_clock_and_fps_width_do_not_change_with_digits(app, scale):
    """0.41.1: 숫자는 고정 칸 — 초마다 값이 바뀌어도 형식이 같으면 오버레이 폭이 같다(오른쪽 끝 흔들림 방지)."""
    from mabinogi_addon.ui.frame_overlay import FrameOverlay
    overlay = FrameOverlay(scale)
    try:
        widths = set()
        for clock in ('11:11:11', '20:00:00', '23:59:59', '08:48:18'):
            overlay.set_items([('FPS', '60', ''), ('현재 시각', clock, '')])
            widths.add(overlay.width())
        assert len(widths) == 1
        fps_widths = set()
        for fps in ('11', '88', '40', '17'):
            overlay.set_items([('FPS', fps, '')])
            fps_widths.add(overlay.width())
        assert len(fps_widths) == 1
    finally:
        overlay.deleteLater()
