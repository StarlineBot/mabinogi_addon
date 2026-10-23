"""FPS 명세 8.1·8.4 / 블랙박스 명세 11.1·11.2 회귀."""
import os
import threading
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from mabinogi_addon.system import perf_metrics as pm


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_busiest_core_ignores_total_and_clamps():
    assert pm.busiest_core({'_Total': 6.2, '0': 3.0, '7': 100.4, '3': 12}) == 100.0
    assert pm.busiest_core({'_Total': 5}) is None


def test_gpu_matches_task_manager_engine_aggregation():
    # 같은 엔진 종류는 프로세스별로 더하고, 종류(3D/Copy/VideoEncode) 중 최댓값.
    values = {
        'pid_100_luid_0x0_0x1_phys_0_eng_0_engtype_3D': 20.0,
        'pid_200_luid_0x0_0x1_phys_0_eng_0_engtype_3D': 15.0,
        'pid_300_luid_0x0_0x1_phys_0_eng_5_engtype_VideoEncode': 30.0,
        'pid_300_luid_0x0_0x1_phys_0_eng_2_engtype_Copy': 1.0,
        'pid_400_luid_0x0_0x2_phys_0_eng_0_engtype_3D': 90.0,  # 다른 GPU(내장)는 따로
    }
    assert pm.gpu_utilization(values) == 90.0
    del values['pid_400_luid_0x0_0x2_phys_0_eng_0_engtype_3D']
    assert pm.gpu_utilization(values) == pytest.approx(35.0)
    # 같은 종류 엔진이 여럿이면(예: VideoDecode eng_6·eng_7) 작업 관리자처럼 엔진별로 본다.
    assert pm.gpu_utilization({'pid_1_luid_0x0_0x1_phys_0_eng_6_engtype_VideoDecode': 30.0,
                               'pid_1_luid_0x0_0x1_phys_0_eng_7_engtype_VideoDecode': 30.0}) == 30.0
    assert pm.gpu_utilization({'garbage': 1}) is None


def test_sampler_reads_only_enabled_metrics_off_ui_thread_and_stops():
    calls, opened, done = [], [], threading.Event()

    class Reader:
        def __init__(self, metrics):
            opened.append(set(metrics))

        def read(self, pid, metrics):
            calls.append((pid, threading.current_thread().name))
            done.set()
            return {'cpu': 41.0}

        def close(self):
            calls.append('closed')

    sampler = pm.PerfSampler(Reader, interval=.01)
    sampler.update(['fps'], 7)  # FPS만 켜면 조회 스레드를 만들지 않는다(기본값)
    assert sampler._thread is None and opened == []
    sampler.update(['fps', 'cpu'], 7)
    assert done.wait(2)
    assert opened == [{'cpu'}] and calls[0] == (7, 'overlay-metrics')
    for _ in range(200):
        if sampler.latest:
            break
        threading.Event().wait(.01)
    assert sampler.latest == {'cpu': 41.0}
    thread = sampler._thread
    sampler.update([], None)  # UI 스레드는 기다리지 않고, 조회 스레드는 다음 대기에서 끝난다
    assert sampler._thread is None
    thread.join(2)
    assert 'closed' in calls


def test_overlay_items_follow_toggles_and_default_is_fps_only(app, tmp_path, monkeypatch):
    from mabinogi_addon.ui.frame_overlay import FrameOverlay
    from mabinogi_addon.ui.optimization_controller import OptimizationController
    fake = NS(_metrics=dict(fps=True, cpu=False, gpu=False, memory=False))
    items = OptimizationController.overlay_items(fake, 143.7, {'cpu': 50})
    assert items == [('FPS', '144', '')]  # 정수 표시(8.1)
    fake._metrics.update(cpu=True, gpu=True, memory=True, fps=False)
    items = OptimizationController.overlay_items(fake, 60, {'cpu': 34.4, 'memory': 3.2 * 1024 ** 3})
    assert items == [('CPU', '34', '%'), ('GPU', '—', ''), ('메모리', '3.2', 'GB')]  # 숨긴 FPS 자리는 당겨 붙음
    overlay = FrameOverlay(100)
    overlay.set_items([('FPS', '144', '')])
    one = overlay.width()
    overlay.set_items([('FPS', '144', ''), ('CPU', '34', '%')])
    assert overlay.width() > one
    overlay.set_scale(200)
    assert overlay.height() > 0 and overlay.items()[1] == ('CPU', '34', '%')


def test_fps_tab_has_no_render_target_combo_and_default_metrics(app):
    from PySide6.QtWidgets import QWidget
    from mabinogi_addon.ui.optimization_panel import OptimizationPanel
    panel = OptimizationPanel(QWidget())
    assert not hasattr(panel, 'source')  # 8.2 렌더링 대상 선택 제거
    assert list(panel.metric_boxes) == ['fps', 'cpu', 'gpu', 'memory']


def test_multiple_render_targets_are_explained_in_status():
    from mabinogi_addon.optimization.frames import FrameStream
    stream = FrameStream(7, 1_000_000)
    stream.feed('Application,ProcessID,SwapChainAddress,QPCTime,msBetweenPresents', 100)
    for n in range(5):
        for source in ('0x1', '0x2'):
            stream.feed(f'game,7,{source},{round((100 + n * .02) * 1_000_000)},20', 100 + n * .02)
    assert '여러 개' in stream.snapshot(100.1)['status']


def test_blackbox_toggle_button_text(app):
    from mabinogi_addon.ui.blackbox_tab import BlackboxTab
    tab = BlackboxTab()
    tab.enabled.setEnabled(True)
    assert tab.enabled.isCheckable() and tab.enabled.text() == '블랙박스 사용'
    tab.enabled.setChecked(True)
    assert tab.enabled.text() == '블랙박스 사용 중'


def test_blackbox_badge_states():
    from mabinogi_addon.ui.blackbox_controller import blackbox_badge, save_failure_reason
    service = lambda status, enabled=True: NS(status=status, enabled=enabled)
    assert blackbox_badge(None) is None
    assert blackbox_badge(service('recording', enabled=False)) is None  # 사용 꺼짐 → 숨김
    assert blackbox_badge(service('recording'), 192_000_000) == ('블랙박스: 보관 중 3:12', 'neutral')
    assert blackbox_badge(service('paused'))[0] == '블랙박스: 일시정지'
    assert blackbox_badge(service('waiting'))[0] == '블랙박스: 게임 대기'
    assert blackbox_badge(service('error')) == ('블랙박스: 녹화 오류', 'error')
    assert save_failure_reason(PermissionError('save unavailable')) == '확보한 영상 없음'
    assert save_failure_reason(RuntimeError('one active and one queued save already reserved')) == '이미 저장 중이에요'


def test_blackbox_reactions_toast_and_sound_slots(app, monkeypatch):
    from mabinogi_addon.ui import blackbox_controller as module, notifier
    from mabinogi_addon.ui.blackbox_toast import format_duration
    played = []
    monkeypatch.setattr(notifier, 'play_blackbox_sound', lambda kind: played.append(kind) or False)
    monkeypatch.setattr(module, 'is_creator', lambda: True)

    class Service:
        error = None
        def __init__(self): self.completed, self.calls = [], 0
        def request_save(self, us):
            self.calls += 1
            if self.calls > 1: raise PermissionError('save unavailable')

    controller = module.BlackboxController.__new__(module.BlackboxController)
    controller.window, controller.panel, controller._toast = NS(_closing=False), None, None
    controller._last_target = None
    controller.service, controller.close_error = Service(), None
    controller._request_save(1)
    assert controller._toast.text() == '영상 저장 중…' and played == ['accepted']
    controller._request_save(2)
    assert controller._toast.text() == '저장하지 못했어요 · 확보한 영상 없음' and played[-1] == 'failed'
    controller._react('영상 저장 완료 · ' + format_duration(192_000_000), 'done')
    assert controller._toast.text() == '영상 저장 완료 · 3분 12초' and len(played) == 2  # 완료는 문구만


def test_blackbox_sound_slot_is_silent_without_files(app):
    # 효과음 파일은 검토 후 추가 예정: 없으면 재생하지 않고 False(문구 오버레이는 그대로).
    from mabinogi_addon.ui import notifier
    if not any(notifier.sound_path(n).exists() for n in notifier.BLACKBOX_SOUND_FILES.values()):
        assert notifier.play_blackbox_sound('accepted') is False
    assert notifier.play_blackbox_sound('unknown') is False


def test_failed_reader_is_retried_only_after_interval_and_warned_once(caplog):
    # 0.13.0 QA 2: 조회기 생성이 실패하는 PC에서 0.25초마다 다시 만들고 경고를 반복하지 않는다.
    now, calls = [0.0], []

    def failing(metrics):
        calls.append(now[0])
        raise OSError('PDH 실패')

    sampler = pm.PerfSampler(failing, interval=.01, clock=lambda: now[0])
    for step in range(40):  # 10초 동안 0.25초 간격
        now[0] = step * .25
        sampler.update(['cpu'], 1)
        if sampler._thread is not None:
            sampler._thread.join(2)
    assert len(calls) == 1
    now[0] = pm.PerfSampler.RETRY_SECONDS + 1
    sampler.update(['cpu'], 1)
    sampler._thread.join(2)
    assert len(calls) == 2
    assert sum('시작하지 못했어요' in r.getMessage() for r in caplog.records) == 1
    sampler.stop()


def test_one_missing_counter_keeps_the_other(monkeypatch):
    # 0.13.0 QA 2: CPU/GPU 카운터를 따로 추가해 하나가 없어도 나머지를 표시한다.
    import sys
    from types import ModuleType
    fake = ModuleType('win32pdh')
    fake.PDH_FMT_DOUBLE, fake.PDH_FMT_NOCAP100 = 0x200, 0x8000
    fake.OpenQuery = lambda: 'q'
    fake.CloseQuery = lambda q: None
    fake.CollectQueryData = lambda q: None

    def add(query, path):
        if 'GPU' in path:
            raise OSError('GPU Engine 카운터 없음')
        return 'cpu-counter'
    fake.AddEnglishCounter = add
    fake.GetFormattedCounterArray = lambda counter, fmt: {'_Total': 9, '0': 55.0}
    monkeypatch.setitem(sys.modules, 'win32pdh', fake)
    reader = pm.WindowsPerfReader({'cpu', 'gpu'})
    assert reader.read(None, {'cpu', 'gpu'}) == {'cpu': 55.0}
    fake.AddEnglishCounter = lambda q, p: (_ for _ in ()).throw(OSError('없음'))
    with pytest.raises(OSError):
        pm.WindowsPerfReader({'cpu', 'gpu'})


def test_save_results_toast_on_game_monitor_using_logical_coordinates(app, monkeypatch):
    # 0.13.0 QA 1: 완료·실패 반응도 게임 창이 있는 모니터에. GetWindowRect(물리) → 논리 좌표로 화면 찾기.
    from mabinogi_addon.ui import blackbox_controller as module, notifier, dpi
    from mabinogi_addon.system import blackbox_events
    monkeypatch.setattr(notifier, 'play_blackbox_sound', lambda kind: False)
    monkeypatch.setattr(module, 'is_creator', lambda: True)
    monkeypatch.setattr(blackbox_events, 'window_rect', lambda hwnd: (0, 0, 2000, 1000))
    logical = []
    monkeypatch.setattr(dpi, 'to_logical', lambda *a: logical.append(a) or (0, 0, 1000, 500))
    shown = []
    controller = module.BlackboxController.__new__(module.BlackboxController)
    controller.window, controller.panel = NS(_closing=False), None
    controller._toasted_failures, controller._badge_wired = set(), True
    result = NS(duration_us=5_000_000, output='x')
    controller.service = NS(completed=[('saved', result)], status='recording', enabled=True,
                            tick=lambda *a, **k: None, error=None, recoveries=list,
                            _retention=600_000_000, settings=NS(output_folder='f'), current=None)
    controller.events = NS(sample=lambda: (NS(hwnd=42), True), consume_hotkey=lambda: None)
    controller._toast = NS(show_message=lambda text, kind, rect: shown.append((text, rect)))
    controller._recovery_dialog = None
    controller._tick()
    assert shown[0][0] == '영상 저장 완료 · 5초'
    assert logical == [(0, 0, 2000, 1000)] and shown[0][1] is not None


def test_fps_overlay_drag_snaps_to_grid_like_other_overlays(app, monkeypatch):
    # 0.13.0 실사용 회귀: 전용 그리기로 바꾸며 격자 이동·안내선이 빠졌다.
    from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
    from PySide6.QtGui import QMouseEvent
    from mabinogi_addon.ui import grid
    from mabinogi_addon.ui.frame_overlay import FrameOverlay
    guides = []
    monkeypatch.setattr(grid, 'enabled', lambda: True)
    monkeypatch.setattr(grid, 'size', lambda: 32)
    monkeypatch.setattr(grid, 'show_guide', lambda: guides.append('show'))
    monkeypatch.setattr(grid, 'hide_guide', lambda: guides.append('hide'))
    snapped = []
    monkeypatch.setattr(grid, 'snap', lambda point, size: snapped.append((point, size)) or QPoint(64, 96))
    overlay = FrameOverlay(100); overlay.set_locked(False); overlay.move(0, 0)
    def mouse(kind, x, y):
        return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    overlay.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, 5, 5))
    overlay.mouseMoveEvent(mouse(QEvent.Type.MouseMove, 70, 100))
    overlay.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, 70, 100))
    assert guides == ['show', 'hide'] and snapped and snapped[0][1] == 32
    assert overlay.pos() == QPoint(64, 96)


def test_too_short_recording_is_not_saved_as_zero_second_file():
    # 0.13.1 실사용: 녹화가 멈춰 보관분이 0초인데 저장이 '성공'해 0초 mp4가 생겼다.
    from mabinogi_addon.blackbox_service import BlackboxService, MIN_SAVE_US, TooShortToSave
    from mabinogi_addon.ui.blackbox_controller import save_failure_reason
    service = BlackboxService.__new__(BlackboxService)
    service._allowed, service._closing = (lambda: True), False
    service.settings = NS(min_save_us=MIN_SAVE_US)
    service.current = NS(session=NS(_replay=NS(available_us=400_000)))
    with pytest.raises(TooShortToSave) as error:
        service.request_save(1)
    assert save_failure_reason(error.value) == '저장할 영상이 너무 짧아요'
    assert MIN_SAVE_US == 1_000_000
