"""0.17.2: 프레임·루프마다 config.json 읽기 제거(권한 1초 재사용), FPS 표시 2시간 뒤 꺼짐, 상단 최적화 배지 통일."""
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from mabinogi_addon import config, feature_access
from mabinogi_addon.feature_access import Recheck
from mabinogi_addon.optimization.frames import FrameStream
from mabinogi_addon.ui import optimization_controller as module
from test_navigation import window  # noqa: F401  (픽스처)

import test_blackbox_stream as stream_tests

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def real_interval():
    """conftest는 기존 기능 테스트를 위해 재사용 간격을 0으로 둔다. 여기서는 제품 기본값(1초)으로 확인한다."""
    saved, Recheck.INTERVAL = Recheck.INTERVAL, 1.0
    yield
    Recheck.INTERVAL = saved


# ---- Recheck ----

def test_recheck_reuses_for_interval_and_invalidate_rereads():
    now, calls = [0.0], []
    check = Recheck(lambda: calls.append(1) or len(calls), interval=1.0, clock=lambda: now[0])
    assert [check() for _ in range(1000)] == [1] * 1000
    now[0] = 0.99
    assert check() == 1
    now[0] = 1.0
    assert check() == 2
    check.invalidate()
    assert check() == 3 and len(calls) == 3
    now[0] = 0.5  # 시계가 뒤로 가면 다시 읽는다
    assert check() == 4


# ---- FPS 줄마다 설정 읽기 제거 ----

def _feed(c, monkeypatch, count, start=100.0):
    now = [start]
    monkeypatch.setattr(module.presentmon, 'clock', lambda: (now[0], 1000000))
    c.frames = True; c.target = {'pid': 123, 'birth': 'run-1'}; c.context = (True, (1, 123))
    c.stream = FrameStream(123, 1000000, c.summary)
    c._sync_summary_context(now[0])
    c._line('Application,ProcessID,SwapChainAddress,QPCTime,msBetweenPresents')
    for n in range(count):
        now[0] = start + 0.02 + n * 0.0045
        c._line(f'game,123,0x1,{round(now[0] * 1000000)},4.5')
    return now


def test_fps_lines_read_settings_a_constant_number_of_times(window, monkeypatch, real_interval):
    # QA(qa_0171_fps_line_cost): 줄마다 is_creator → config.json 읽기(분당 2만 줄 중 95%). 이제 1초에 한 번 이하.
    c = window[0].optimization_tools; c.timer.stop()
    reads = []
    monkeypatch.setattr(config, 'load_discord_user', lambda *a: reads.append(1) or {'id': feature_access.CREATOR_DISCORD_ID})
    c.refresh_access()
    reads.clear()
    started = time.monotonic()
    _feed(c, monkeypatch, 20000)
    elapsed = time.monotonic() - started
    assert c.frames
    assert len(reads) <= elapsed + 2  # 시간 간격 기준(1초에 1회) — 줄 수(2만)와 무관


def test_logout_stops_fps_measurement_immediately_through_login_changed(window, monkeypatch, real_interval):
    c = window[0].optimization_tools; c.timer.stop()
    user = [{'id': feature_access.CREATOR_DISCORD_ID}]
    # 2026-10-28부터 최적화·FPS 표시는 전체 공개 — 접근 판정 함수를 직접 바꿔 캐시 무효화·회수 경로를 확인한다
    monkeypatch.setattr(config, 'load_discord_user', lambda *a: user[0])
    monkeypatch.setattr(module, 'optimization_available', lambda: user[0] is not None)
    c.refresh_access()
    _feed(c, monkeypatch, 10)
    assert c.frames
    user[0] = None
    window[0].settings_tab.login_changed.emit()  # 로그아웃: 캐시를 버리고 바로 다시 확인
    assert not c.frames


def test_access_revoked_outside_login_signal_is_seen_within_one_second(window, monkeypatch, real_interval):
    c = window[0].optimization_tools; c.timer.stop()
    user = [{'id': feature_access.CREATOR_DISCORD_ID}]
    # 2026-10-28부터 최적화·FPS 표시는 전체 공개 — 접근 판정 함수를 직접 바꿔 캐시 무효화·회수 경로를 확인한다
    monkeypatch.setattr(config, 'load_discord_user', lambda *a: user[0])
    monkeypatch.setattr(module, 'optimization_available', lambda: user[0] is not None)
    c.refresh_access()
    now = _feed(c, monkeypatch, 10)
    user[0] = None  # 설정 파일이 바뀜(신호 없음)
    deadline = time.monotonic() + 1.5
    while c.frames and time.monotonic() < deadline:
        now[0] += 0.0045
        c._line(f'game,123,0x1,{round(now[0] * 1000000)},4.5')
        time.sleep(0.01)
    assert not c.frames and '사용 불가' in c.frame_status


# ---- FPS 표시 약 2시간 뒤 꺼짐(요약 한도) ----

def _fill_summary(c, monkeypatch, now):
    """구간 한도를 3개로 줄이고 실제 구간을 닫아 한도에 닿게 한다(실사용은 60초 구간 128개 ≈ 2시간)."""
    monkeypatch.setattr(module.FrameSummary, 'MAX_SEGMENTS', 3)
    for _ in range(3):
        for _ in range(5):
            now[0] += 0.0045
            c._line(f'game,123,0x1,{round(now[0] * 1000000)},4.5')
        c.stream.boundary(now[0], 'test_segment')
    assert c.summary.full and len(c.summary.records) == 3


def _next_line(c, now):
    now[0] += 0.0045
    c._line(f'game,123,0x1,{round(now[0] * 1000000)},4.5')


def test_summary_limit_without_collection_keeps_display(window, monkeypatch, caplog):
    # 사용자 app.log 08:33:02 'FPS 표시 중단: 구간/전환 요약 한도' → 수집을 안 하면 표시는 멈추지 않는다
    c = window[0].optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True)
    c.summary.set_condition('마을')
    now = _feed(c, monkeypatch, 30)
    old = c.summary
    _fill_summary(c, monkeypatch, now)
    _next_line(c, now)
    assert c.frames and c.summary is not old and not c.summary.full
    assert c.stream.summary is c.summary and c.summary.condition == '마을'
    for n in range(5):
        now[0] += 0.0045
        c._line(f'game,123,0x1,{round(now[0] * 1000000)},4.5')
    assert c.frames and c.summary.samples  # 새 요약으로 계속 집계·표시


def test_summary_limit_while_collecting_stops_collection_only(window, monkeypatch):
    c = window[0].optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True)
    c.open()
    now = _feed(c, monkeypatch, 30)
    c._collect_only = False
    c._summary_collecting = True
    c.panel.summary_collect.blockSignals(True); c.panel.summary_collect.setChecked(True); c.panel.summary_collect.blockSignals(False)
    monkeypatch.setattr(c.summary_store, 'submit', lambda report: None)
    _fill_summary(c, monkeypatch, now)
    _next_line(c, now)
    assert c.frames  # 표시는 계속
    assert not c._summary_collecting and not c.panel.summary_collect.isChecked()
    assert '수집 한도' in c._summary_message and '저장돼 있어요' in c._summary_message


def test_summary_limit_in_collect_only_mode_ends_measurement(window, monkeypatch):
    c = window[0].optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True)
    c.open()
    now = _feed(c, monkeypatch, 30)
    c._collect_only = True
    c._summary_collecting = True
    monkeypatch.setattr(c.summary_store, 'submit', lambda report: None)
    _fill_summary(c, monkeypatch, now)
    _next_line(c, now)
    assert not c.frames and not c._summary_collecting and '수집 한도' in c.frame_status


# ---- 블랙박스 캡처 루프 권한 확인 ----

class IdleDevice(stream_tests.Device):
    """프레임이 없는 동안에도 캡처 루프는 계속 돈다(실사용 60FPS 모형에서 초당 587회 권한 확인)."""
    def __init__(self):
        super().__init__([])


def _producer(allowed):
    producer = stream_tests._producer([], stream_tests.StreamCodec())
    producer.native = IdleDevice()
    producer.allowed = allowed
    return producer


def test_capture_loop_checks_permission_a_few_times_per_second():
    calls = []
    producer = _producer(lambda: calls.append(1) or True)
    producer.start()
    time.sleep(3)
    producer.request_stop()
    deadline = time.monotonic() + 3
    while not producer.is_stopped() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert producer.error is None
    assert len(calls) <= 3 * 5 + 2  # 0.25초 간격 → 초당 4회 안팎


def test_logout_stops_recording_within_one_second():
    allowed = threading.Event(); allowed.set()
    producer = _producer(lambda: allowed.is_set())
    producer.start()
    time.sleep(0.3)
    allowed.clear()
    revoked = time.monotonic()
    while producer.error is None and time.monotonic() - revoked < 2:
        time.sleep(0.005)
    took = time.monotonic() - revoked
    producer.request_stop()
    assert producer.error is not None and 'PermissionError' in producer.error and took < 1.0


def test_blackbox_controller_shares_cached_permission_with_service(monkeypatch, real_interval):
    from mabinogi_addon.ui import blackbox_controller
    reads = []
    monkeypatch.setattr(feature_access, 'blackbox_available', lambda: reads.append(1) or True)
    c = blackbox_controller.BlackboxController.__new__(blackbox_controller.BlackboxController)
    blackbox_controller.QObject.__init__(c)
    c.window = SimpleNamespace(_closing=False)
    assert all(c._allowed() and c._service_allowed() for _ in range(5000)) and len(reads) == 1
    c._access.invalidate()  # refresh_access(로그인 변경)가 하는 일
    assert c._service_allowed() and len(reads) == 2
    source = (ROOT / 'src/mabinogi_addon/ui/blackbox_controller.py').read_text(encoding='utf-8')
    assert 'allowed=self._service_allowed' in source
    assert source.index('def refresh_access') < source.index('self._access.invalidate()')


# ---- 상단 최적화 배지 통일 ----

@pytest.mark.parametrize('state, color', [
    (('최적화: 적용 중', 'neutral'), '#2ecc71'),
    (('최적화: 적용 중 6+2', 'neutral'), '#2ecc71'),
    (('최적화: 게임 대기', 'neutral'), '#8a8f98'),
    (('최적화: 원복 중', 'neutral'), '#8a8f98'),
    (('최적화: 원복 대기', 'warn'), '#e67e22'),
    (('최적화: 오류', 'error'), '#e74c3c'),
])
def test_optimization_badge_matches_other_status_badges(window, monkeypatch, state, color):
    w = window[0]
    c = w.optimization_tools; c.timer.stop()
    monkeypatch.setattr(module, 'optimization_available', lambda: True)
    monkeypatch.setattr(module, "optimization_badge", lambda *a, **k: state)
    c.refresh_access()
    c._update_badge()
    badge = w._optimization_badge
    assert not badge.isHidden() and badge.text() == '● ' + state[0]
    assert badge.styleSheet() == w.status_style(color) and 'underline' not in badge.styleSheet()
    assert badge.toolTip() == '최적화 상태예요. 성능 개선을 뜻하지 않아요. 누르면 최적화 탭으로 이동해요.'
    assert 'underline' not in w.findChild(type(badge.parentWidget()), 'statusBar').styleSheet()
    badge.click()
    assert w._tabs.currentWidget() is c.panel
