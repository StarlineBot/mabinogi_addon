"""블랙박스 녹화 방식(명세 12.2): 평소 녹화 / 전투 녹화."""
import os
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from mabinogi_addon.blackbox_combat import CombatGate, GRACE_SECONDS
from test_navigation import window  # noqa: F401  (픽스처)


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
    monkeypatch.setattr(module.feature_access, 'blackbox_available', lambda: True)
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
    assert blackbox_badge(service, 0, gate) == ('● 블랙박스: 전투 대기', 'muted')
    gate.update(1, True, True)
    assert combat_text(gate) == '보관 중 · 전투'
    assert blackbox_badge(NS(enabled=True, status='recording'), 184_000_000, gate)== ('● 블랙박스: 보관 중 · 전투 3:04', 'ok')
    gate.update(2, False, True)
    assert combat_text(gate) == '보관 중 · 전투 종료 대기 59초'
    assert blackbox_badge(service, 0, gate)== ('● 블랙박스: 전투 종료 대기 59초', 'muted')
    assert blackbox_badge(NS(enabled=True, status='recording'), 60_000_000)== ('● 블랙박스: 보관 중 1:00', 'ok')  # 평소 녹화 불변


def test_save_progress_reads_ffmpeg_report_and_formats_text(tmp_path, monkeypatch):
    # 0.14.1 저장 진행 표시: ffmpeg -progress의 out_time_us를 저장 분량 대비 퍼센트로.
    import time
    from mabinogi_addon.blackbox_codec import FFmpegEncoder
    from mabinogi_addon.ui import blackbox_controller as module
    codec = FFmpegEncoder.__new__(FFmpegEncoder)
    report = tmp_path / 'progress.txt'
    report.write_text('frame=10\nout_time_us=60000000\nprogress=continue\nout_time_us=120000000\n', encoding='utf-8')
    codec.progress = dict(stage='encode', duration_us=300_000_000, started=time.monotonic() - 72, path=report)
    stage, duration, elapsed, fraction = codec.progress_snapshot()
    assert stage == 'encode' and duration == 300_000_000 and 71 <= elapsed < 74 and fraction == 0.4
    c = module.BlackboxController.__new__(module.BlackboxController)
    c.service = NS(codec=codec)
    c._save_started = None
    text = c._progress_text(2)
    assert text.startswith('저장 중 · 5분 0초 분량 · 경과 1:1') and '약 40% (인코딩)' in text
    assert '다음 저장 대기 1건' in text
    codec.progress = dict(codec.progress, stage='validate')
    assert '마무리 확인 중(검증)' in c._progress_text(1)
    codec.progress = None
    assert c._progress_text(1) == '저장 준비·마무리 중'               # 0.14.2: 1건뿐이면 중립 문구
    assert c._progress_text(2) == '저장 대기 2건 · 앞 작업이 끝나면 시작해요'


def test_saved_result_is_handled_once_without_hotkey_note(monkeypatch):
    # 0.14.2 회귀: 지역 import time 때문에 UnboundLocalError → completed를 비우지 못해 완료 알림이 매 틱 반복되던 문제.
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('qa_stuck', root / 'scripts/qa_0141_blackbox_saved_toast_stuck.py')
    qa = importlib.util.module_from_spec(spec); spec.loader.exec_module(qa)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    c, toasts = qa.controller(None)
    for _ in range(5):
        c._tick()
    assert toasts == ['저장 완료 · 1분 49초'] and c.service.completed == []
    # 0.16.0: '최근 저장: HH:MM · 1분 49초 영상 · 파일이름.mp4'(다음 저장까지 유지)
    import re
    assert re.fullmatch(r'최근 저장: \d\d:\d\d · 1분 49초 영상 · clip\.mp4', c.panel.recent.value), c.panel.recent.value


def test_game_screen_progress_toast_stays_until_finished_then_hides(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from mabinogi_addon.ui import blackbox_controller as module
    from mabinogi_addon.ui.blackbox_toast import BlackboxToast
    app = QApplication.instance() or QApplication([])
    import time
    c = module.BlackboxController.__new__(module.BlackboxController)
    c.window, c._last_target = NS(_closing=False), None
    monkeypatch.setattr(module.feature_access, 'blackbox_available', lambda: True)
    c._toast = BlackboxToast()
    snap = {'value': None}
    c.service = NS(codec=NS(progress_snapshot=lambda: snap['value']))
    c._toast.show_message('저장 중 0%', 'pending', sticky=True)
    snap['value'] = ('encode', 300_000_000, 10.0, 0.42)
    c._update_save_toast(2)
    assert c._toast.text() == '저장 중 42% · 대기 1' and c._toast.sticky and not c._toast._timer.isActive()
    snap['value'] = ('validate', 300_000_000, 20.0, None)
    c._update_save_toast(1)
    assert c._toast.text() == '저장 마무리 중'
    c._toast.show_message('저장 완료 · 5분 0초', 'done')      # 완료는 3초 알림
    c._update_save_toast(0)
    assert c._toast.isVisible() and c._toast._timer.isActive()
    c._toast.show_message('저장 중 0%', 'pending', sticky=True)
    c._update_save_toast(0)                                    # 저장이 없으면 진행 알림을 남기지 않음
    assert not c._toast.isVisible()
    assert c._toast._font.pixelSize() == 14


def test_encode_failure_clears_progress():
    import pytest
    from mabinogi_addon import blackbox_codec as codec_module
    encoder = codec_module.FFmpegEncoder.__new__(codec_module.FFmpegEncoder)
    encoder.progress = None
    encoder.settings = NS(ffmpeg='ffmpeg', timeout=5, host=None, fps=60, bitrate=1, audio_bitrate=None)
    encoder.resolve = lambda source: '/tmp/x.mp4'
    encoder._output = lambda audio=False: ['-f', 'null', '-']
    segment = NS(format_key='1x1:60:video', source='s')
    plan = NS(slices=(NS(segment=segment, offset_us=0, duration_us=1_000_000),), duration_us=1_000_000)
    def boom(*a, **k): raise OSError('encoder exited 1')
    original = codec_module.stream_process
    codec_module.stream_process = boom
    try:
        with pytest.raises(OSError):
            encoder.encode(plan, NS(write=lambda b: None))
    finally:
        codec_module.stream_process = original
    assert encoder.progress is None and encoder.progress_snapshot() is None


def test_combat_mode_is_first_and_default(window):  # noqa: F811
    """2026-10-25 사용자 결정: 전투 녹화를 앞에, 저장값이 없으면 전투 녹화."""
    from mabinogi_addon.ui.blackbox_tab import BlackboxTab
    tab = BlackboxTab()
    row = [tab.mode_group.buttons()[i].text() for i in range(2)]
    assert row == ['전투 녹화', '평소 녹화'] and tab.mode_combat.isChecked()
    assert tab.mode_help.text().startswith('전투 녹화')
    assert window[0].blackbox_tools._mode == 'combat'
