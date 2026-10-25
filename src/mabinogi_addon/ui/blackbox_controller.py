"""블랙박스 최상위 진입점(디스코드 로그인 사용자, 0.16.0 베타). 캡처 어댑터가 없는 제품 상태에서는 조작을 열지 않는다."""

import time

from PySide6.QtCore import QObject, QTimer

from .. import feature_access
from .blackbox_tab import BlackboxTab


from ..blackbox_shortcut import hotkey_text, key_name  # noqa: F401 — 기존 가져오기 경로 유지
_log = __import__('logging').getLogger(__name__)
_STATES = {'recording': '보관 중', 'preparing': '녹화 준비 중', 'paused': '일시정지',
           'pausing': '중단 구간 정리 중', 'disabled': '사용 안 함', 'error': '녹화 오류',
           'stalled': '녹화 멈춤 · 새 영상이 들어오지 않아요'}  # 0.18.0: 새 구간이 없으면 '보관 중'으로 두지 않음


def save_failure_reason(exc) -> str:
    """저장 요청 거부의 짧은 이유(게임 화면 오버레이용). 자세한 문구는 앱 탭에 남는다."""
    if isinstance(exc, PermissionError):
        return '확보한 영상 없음'
    if type(exc).__name__ == 'TooShortToSave':
        if getattr(exc, 'recording_error', False):
            return '녹화 오류로 저장할 영상이 없어요 · 앱에서 확인'
        return '저장할 영상이 너무 짧아요'
    if isinstance(exc, RuntimeError) and 'already reserved' in str(exc):
        return '이미 저장 중이에요'
    return '앱에서 확인'


def error_summary(text):
    """녹화 오류 원문(영어·내부 문구)을 탭에 보일 한국어 요약으로. 원문은 app.log에만 남긴다(0.16.0)."""
    raw = str(text or '')
    lowered = raw.lower()
    if not raw:
        return ''
    for needle, summary in (('encoder exited', '영상 인코더가 멈춰 녹화를 중단했어요'),
                            ('하드웨어 h.264 인코더', '그래픽카드 영상 인코더를 열지 못했어요'),
                            ('access revoked', '로그인이 풀려 녹화를 멈췄어요'),
                            ('access required', '로그인이 풀려 녹화를 멈췄어요'),
                            ('dimensions changed', '게임 창 크기가 바뀌어 녹화를 다시 시작해요'),
                            ('no space', '저장 공간이 부족해요'), ('budget', '저장 공간이 부족해요'),
                            ('disk', '저장 공간이 부족해요'),
                            ('retained for recovery', '임시 보관 자료를 정리하지 못했어요'),
                            ('timeout', '녹화 장치 응답이 늦어 녹화를 중단했어요'),
                            ('timed out', '녹화 장치 응답이 늦어 녹화를 중단했어요')):
        if needle in lowered:
            return summary + ' (자세한 내용: app.log)'
    if any('\uac00' <= ch <= '\ud7a3' for ch in raw[:40]):
        first = raw.split(' · ')[0].split(': ')[0].strip()  # 이미 한국어 문구: 첫 문장만
        return first + ' (자세한 내용: app.log)'
    return '녹화 중 문제가 생겼어요 (자세한 내용: app.log)'


def _toast_duration(us):
    from .blackbox_toast import format_duration
    return format_duration(us)


def combat_text(gate):
    """전투 녹화 상태 문구(명세 12.2)."""
    return {'unregistered': '전투 대기 · 보스 체력바 영역 미등록',
            'waiting': '전투 대기 · 보스 체력바가 보이면 녹화해요',
            'recording': '보관 중 · 전투',
            'grace': f'보관 중 · 전투 종료 대기 {gate.grace_left}초'}[gate.state]


BADGE_COLORS = {'ok': '#2ecc71', 'muted': '#8a8f98', 'error': '#e74c3c'}  # 전투 보조 상태와 같은 색(0.16.0)
BADGE_TIPS = {'ok': '누르면 블랙박스 탭으로 이동해요.',  # 0.17.2: 모든 상태에서 탭 이동(끄기는 탭에서)
              'muted': '누르면 블랙박스 탭으로 이동해요.',
              'error': '녹화 오류예요. 누르면 블랙박스 탭에서 내용을 볼 수 있어요.'}


def blackbox_badge(service, available_us=0, combat=None):
    """상단 블랙박스 상태(명세 11.2): (문구, 'ok'|'muted'|'error'). '블랙박스 사용'이 꺼져 있으면 None(숨김).

    보관 중은 초록, 게임 대기·일시정지·전투 대기·전투 종료 대기 등은 회색, 녹화 오류는 빨강. combat: 전투 녹화 판정(CombatGate)."""
    if service is None or not getattr(service, 'enabled', False) or getattr(service, 'status', None) == 'disabled':
        return None
    if service.status == 'error':
        return '● 블랙박스: 녹화 오류', 'error'
    seconds = max(0, int(available_us) // 1_000_000)
    clock = f'{seconds // 60}:{seconds % 60:02d}'
    if combat is not None:
        if combat.state in ('waiting', 'unregistered'):
            return '● 블랙박스: 전투 대기', 'muted'
        if combat.state == 'grace':
            return f'● 블랙박스: 전투 종료 대기 {combat.grace_left}초', 'muted'
        if service.status == 'recording':
            return f'● 블랙박스: 보관 중 · 전투 {clock}', 'ok'
    if service.status == 'recording':
        return f'● 블랙박스: 보관 중 {clock}', 'ok'
    if service.status == 'stalled':
        return '● 블랙박스: 녹화 멈춤', 'muted'  # 새 영상이 안 들어옴(스스로 다시 시작해요)
    return '● 블랙박스: ' + _STATES.get(service.status, '게임 대기'), 'muted'


class BlackboxController(QObject):
    def __init__(self, window, *, session=None, lifecycle=None):
        super().__init__(window)
        self.window = window
        # 세션은 패널과 별개로 소유한다. 탭 제거가 접수된 저장을 폐기하지 않는다.
        if lifecycle is not None:
            if session is not None and session is not lifecycle.runtime.session:
                raise ValueError('lifecycle and controller must share one session')
            session = lifecycle.runtime.session
        self.session = session
        self.lifecycle = lifecycle
        self.close_error = None
        self.service = None
        self.events = None
        self._timer = None
        self._recovery_dialog = None
        self._profile_error = None
        self._hotkey = None  # 저장 단축키 (수식, 키) — 설정값 또는 제품 기본값(0.16.0)
        self._capturing_hotkey = False  # 변경 창이 떠 있는 동안 기존 단축키 입력은 반응 없이 버린다
        self._logged_error = None  # 탭에는 한국어 요약, 원문은 바뀔 때 한 번 app.log에
        self._toast = None  # 게임 화면 위 저장 반응(명세 11.1)
        from ..blackbox_combat import CombatGate
        from .. import config as _config
        self._mode = _config.load_blackbox_preferences().get('recordMode', 'combat')  # 녹화 방식(명세 12.2). 저장값이 없으면 전투 녹화(2026-10-25 사용자 결정)
        self._gate = CombatGate()
        self._last_target = None  # 마지막으로 관측한 게임 창: 완료·실패 반응도 게임 모니터에 띄운다
        self._toasted_failures = set()
        self._badge_wired = False
        self.panel = None
        self._page = None
        self.refresh_access()

    @property
    def _access(self):
        """권한(디스코드 로그인) 확인은 config.json 읽기라 100ms 타이머·캡처 루프(초당 수백 회)마다 하지 않고 1초 동안
        재사용한다(0.17.2). 로그인 변경(login_changed → refresh_access)에는 바로 다시 확인한다."""
        check = self.__dict__.get('_access_check')
        if check is None:
            check = self.__dict__['_access_check'] = feature_access.Recheck(lambda: feature_access.blackbox_available())
        return check

    def _allowed(self):
        try:
            return self._access() is True and not getattr(self.window, '_closing', False)
        except Exception:
            return False

    def _service_allowed(self):
        """서비스·생산자(캡처 스레드)용 권한 확인: 같은 1초 재사용 판정."""
        try:
            return self._access() is True
        except Exception:
            return False

    def refresh_access(self):
        self._access.invalidate()
        if self.session is not None:
            # 접근 해제 관측으로 이전 캡처 허가를 무효화. 사용 체크/저장 pin은 유지.
            self.session.state
        tabs = self.window._tabs
        if not self._allowed():
            if self._page is not None:
                tabs.removeTab(tabs.indexOf(self._page))
                self._page.deleteLater()
                self._page = None
                self.panel = None
            return
        if self._page is None:
            from .main_window import _scrolled
            self.panel = BlackboxTab()
            self._page = _scrolled(self.panel)
            # 탭 순서는 항상 … · 최적화 · 블랙박스 · 설정(2026-10-26 사용자 결정) — 설정 바로 앞에 넣는다
            tabs.insertTab(tabs.indexOf(self.window._settings_scroll), self._page, '블랙박스')
            self._connect_service()

    def _require_session(self):
        if not self._allowed():
            raise PermissionError('블랙박스는 디스코드 로그인 후 사용할 수 있어요.')
        if self.session is None:
            raise RuntimeError('capture and export adapters are not connected')
        return self.session

    def request_save(self, request_us):
        return self._require_session().request_save(request_us)

    def set_enabled(self, enabled):
        self._require_session().set_enabled(enabled)

    def prepare_close(self) -> bool:
        # 권한 해제·탭 제거 후에도 종료/보호 경로는 살아 있다.
        if self.service is not None:
            ready = self.service.prepare_close()
            if ready:
                self._timer.stop()
                self.events.close()
                return True
            self.close_error = self.service.error or '저장/캡처 종료 또는 복구 결정 대기'
            if self.closing_capture_only():
                # 녹화 중지만 진행 중이면 잠시 뒤 자동으로 끝난다: 복구 창을 띄우지 않고 호출자가 다시 시도한다(0.14.1).
                if self.panel is not None:
                    self.panel.status.setText('블랙박스 녹화 정리 중…')
                return False
            self.show_recovery()
            return False
        if self.lifecycle is None:
            return True
        ready = self.lifecycle.prepare_close()
        self.close_error = self.lifecycle.pending_reason
        if not ready and self.panel is not None:
            self.panel.status.setText('종료 대기 · 저장 결과 또는 복구 자료를 확인해야 해요.')
        return ready

    def closing_capture_only(self):
        """종료를 막는 이유가 녹화 중지 진행뿐인지(저장 대기·실패 자료 없음). 호출자는 200ms 뒤 다시 시도한다."""
        reason = getattr(self.service, 'close_wait_reason', None)
        return bool(reason is not None and reason() == 'capture')

    def resume_after_update_failure(self):
        if self.service is not None and self.service._closed:
            self.service = None
            self.events = None
            if self._timer is not None:
                self._timer.deleteLater()
                self._timer = None
            if self._recovery_dialog is not None:
                self._recovery_dialog.close()
                self._recovery_dialog.deleteLater()
                self._recovery_dialog = None
            # 재연결 시 기존 위젯의 신호를 중복 연결하지 않는다.
            if self._page is not None:
                self.window._tabs.removeTab(self.window._tabs.indexOf(self._page))
                self._page.deleteLater()
                self._page = self.panel = None
            self.refresh_access()

    def _connect_service(self):
        from .. import config
        try:
            profile = config.load_blackbox_profile()
        except Exception as exc:
            self._profile_error = str(exc)
            profile = None
        if self.service is None and profile is not None:
            try:
                from ..blackbox_service import BlackboxService, ServiceSettings
                from .blackbox_events import WindowsEvents
                preferences = config.load_blackbox_preferences()
                profile = dict(profile)
                if 'outputFolder' in preferences:
                    profile['output_folder'] = preferences['outputFolder']
                settings = ServiceSettings.from_dict(profile)
                # 저장 단축키: 사용자 설정(규칙을 지킨 값만 불러옴) 또는 제품 기본값
                self._hotkey = tuple(preferences.get('hotkey') or (profile['hotkey_modifiers'], profile['hotkey_vk']))
                events = WindowsEvents(int(self.window.winId()), *self._hotkey)
                try:
                    service = BlackboxService(settings, enabled=config.load_blackbox_enabled(),
                                              persist_enabled=config.save_blackbox_enabled,
                                              allowed=self._service_allowed)
                    service.set_retention(preferences.get('retentionMinutes', 5) * 60 * 1_000_000)
                except BaseException:
                    events.close()
                    raise
                self.events, self.service = events, service
                # 지난 실행에서 남은 실패 자료는 게임 화면에 다시 알리지 않는다(앱 탭·복구 창에서 확인).
                self._toasted_failures = {ticket for _r, ticket, result in service.recoveries()
                                          if result is not None and not result.completed}
                self._timer = QTimer(self)
                self._timer.setInterval(100)
                self._timer.timeout.connect(self._tick)
                self._timer.start()
            except Exception as exc:
                self._profile_error = str(exc)
        if self.service is None:
            if self._profile_error:
                self.panel.status.setText('녹화 준비 실패')
                self._show_error(self._profile_error)
            return
        panel = self.panel
        failures = getattr(self.service, 'leftover_failures', None)
        if failures:
            # 지난 실행이 남긴 임시 자료를 자동 정리하지 못했을 때만 안내한다(정리 성공은 조용히).
            panel.show_error(f'지난 실행에서 남은 블랙박스 임시 자료 {len(failures)}건을 지우지 못했어요. '
                             '다음 실행 때 다시 정리해요.')
        panel.enabled.setChecked(self.service.enabled)
        panel.retention.setValue(max(1, min(panel.retention.maximum(), self.service._retention // 60_000_000)))
        if self._hotkey is not None:
            panel.hotkey.setText(hotkey_text(*self._hotkey))
        panel.folder.setText(str(self.service.settings.output_folder))
        for control in panel.controls():
            control.setEnabled(True)
        panel.enabled.toggled.connect(lambda value: self._action(lambda: self.service.set_enabled(value)))
        (panel.mode_combat if self._mode == 'combat' else panel.mode_always).setChecked(True)
        panel.mode_always.toggled.connect(lambda on: on and self._set_mode('always'))
        panel.mode_combat.toggled.connect(lambda on: on and self._set_mode('combat'))
        self._show_mode_notice()
        panel.save.clicked.connect(lambda checked=False: self._request_save())
        panel.retention.valueChanged.connect(lambda value: self._action(lambda: self._set_retention(value)))
        panel.change_hotkey.clicked.connect(self._change_hotkey)
        panel.change_folder.clicked.connect(self._change_folder)
        panel.open_folder.clicked.connect(self._open_folder)
        panel.recovery.clicked.connect(self.show_recovery)

    def _action(self, operation):
        try:
            return operation()
        except Exception as exc:
            self._show_error(str(exc))
            self.close_error = str(exc)

    def _show_error(self, raw):
        """오류 줄: 한국어 요약 + '(자세한 내용: app.log)'. 원문은 바뀔 때 한 번만 app.log에 남긴다."""
        if raw and raw != getattr(self, '_logged_error', None):
            _log.warning('블랙박스 오류: %s', raw)
        self._logged_error = raw or None
        if self.panel is not None:
            self.panel.show_error(error_summary(raw))

    def _set_recent(self, text):
        if self.panel is not None:
            self.panel.recent.setText('최근 저장: ' + text)

    def _request_save(self, request_us=None):
        if self._allowed() and self.service is not None:
            try:
                self.service.request_save(time.perf_counter_ns() // 1000 if request_us is None else request_us)
            except Exception as exc:
                self._set_recent('저장 안 함 · ' + save_failure_reason(exc))
                self.close_error = str(exc)
                _log.warning('블랙박스 저장 요청 실패(버튼): %s: %s · 상태 %s', type(exc).__name__, exc,
                             getattr(self.service, 'status', None))
                self._react('저장 실패 · ' + save_failure_reason(exc), 'failed', self._last_target)
                return
            self._set_recent('저장 요청을 접수했어요')
            self._react('저장 중 0%', 'pending', self._last_target)

    def _react(self, text, kind, target=None):
        """게임 화면 오버레이 문구 + 효과음(접수·실패만). 전투 보조 일시정지와 무관하게 표시한다(저장 확인)."""
        if not self._allowed():
            return
        from .blackbox_toast import BlackboxToast
        from .notifier import play_blackbox_sound
        if self._toast is None:
            self._toast = BlackboxToast()
        self._toast.show_message(text, kind, self._screen_rect(target), sticky=kind == 'pending')
        if kind in ('pending', 'failed'):
            play_blackbox_sound('accepted' if kind == 'pending' else 'failed')

    @staticmethod
    def _screen_rect(target):
        hwnd = getattr(target, 'hwnd', None)
        if hwnd is None:
            return None
        from ..system.blackbox_events import window_rect
        rect = window_rect(hwnd)  # 게임 창이 있는 모니터의 상단 중앙에 띄운다
        if rect is None:
            return None
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
        try:
            from .dpi import to_logical
            # GetWindowRect는 물리 픽셀: 다른 오버레이처럼 논리 좌표로 바꾼 뒤 화면을 찾는다(혼합 배율 대응).
            left, top, width, height = to_logical(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
            screen = QGuiApplication.screenAt(QPoint(left + width // 2, top + height // 2))
        except Exception:
            return None
        return screen.geometry() if screen is not None else None

    def _hotkey_pressed(self, shortcut, target, active):
        """단축키 입력마다 결과를 남긴다(저장 불가 상태 포함). 게임 창에서 받은 입력만 저장한다."""
        if not self._allowed():
            return
        foreground = getattr(self.events, 'foreground', active)  # 녹화는 뒤에서도 하지만 단축키는 게임이 앞에 있을 때만
        if not (active and foreground and target is not None and shortcut[1] == target.hwnd):
            self._react('저장 실패 · 게임 창이 앞에 있을 때만 저장해요', 'failed', target)
            return
        try:
            self.service.request_save(shortcut[0])
        except Exception as exc:
            # 2026-10-25: 저장 실패 원인이 화면(close_error)에만 있고 app.log에 없어 사후 판정을 못 했다
            self.close_error = str(exc)
            _log.warning('블랙박스 저장 요청 실패(단축키): %s: %s · 상태 %s', type(exc).__name__, exc,
                         getattr(self.service, 'status', None))
            self._set_recent('저장 안 함 · ' + save_failure_reason(exc))
            self._react('저장 실패 · ' + save_failure_reason(exc), 'failed', target)
            return
        self._set_recent('저장 요청을 접수했어요')
        self._react('저장 중 0%', 'pending', target)

    def wants_boss_presence(self):
        """보스 탭이 보스바 존재 판정을 돌려야 하는지(전투 녹화 + 블랙박스 사용 중)."""
        return self._mode == 'combat' and self.service is not None and bool(getattr(self.service, 'enabled', False))

    def _combat_record(self, active):
        """전투 녹화면 보스바 판정으로 녹화 여부를 정한다. 평소 녹화면 항상 True."""
        if self._mode != 'combat':
            return True
        boss = getattr(self.window, 'boss_tab', None)
        registered = bool(boss is not None and boss.has_region())
        foreground = getattr(self.events, 'foreground', active)
        # 게임이 뒤에 있으면 보스바를 볼 수 없어 판정 불가(None) → 직전 전투 상태 유지
        present = bool(boss.is_boss_present()) if (boss is not None and foreground) else None
        return self._gate.update(time.monotonic(), present, registered)

    def _set_mode(self, mode):
        from .. import config
        if mode == self._mode:
            return
        self._mode = mode
        self._action(lambda: config.save_blackbox_preference('recordMode', mode))
        self._show_mode_notice()

    def _show_mode_notice(self):
        if self.panel is None:
            return
        boss = getattr(self.window, 'boss_tab', None)
        missing = self._mode == 'combat' and not (boss is not None and boss.has_region())
        self.panel.mode_notice.setText('보스 체력바 영역을 먼저 등록해 주세요. 등록 전에는 녹화하지 않아요(평소 녹화로 바꾸지 않아요).'
                                       if missing else '')
        self.panel.mode_notice.setVisible(missing)

    def _tick(self):
        if self.service is None:
            return
        try:
            target, active = self.events.sample()
        except Exception as exc:
            target, active = None, False
            self.service.error = str(exc)
        if target is not None:
            self._last_target = target
        self._action(lambda: self.service.tick(target, active=active and self._combat_record(active)))
        try:
            shortcut = self.events.consume_hotkey()
            if shortcut is not None and not getattr(self, '_capturing_hotkey', False):
                self._hotkey_pressed(shortcut, target, active)
        except Exception as exc:
            self.close_error = str(exc)
            self.service.error = str(exc)
        runtime = getattr(self.service, 'current', None)
        duration = runtime.session._replay.available_us if runtime else 0
        self._update_badge(duration)
        # 처리할 결과를 먼저 꺼내고 비운다(0.14.2: 처리 중 예외로 비우지 못해 완료 알림이 매 틱 반복되던 회귀).
        completed = list(self.service.completed)
        self.service.completed.clear()
        # 저장 결과 반응(명세 11.1): 완료는 검증을 마친 결과에서만, 실패는 작업마다 한 번.
        for kind, result in completed:
            if kind == 'saved':
                self._react('저장 완료' + (' · ' + _toast_duration(result.duration_us)
                                          if getattr(result, 'duration_us', None) else ''), 'done', self._last_target)
            elif kind == 'rejected':
                self._save_started = None
                self._react('저장 실패 · 앱에서 확인', 'failed', self._last_target)
            elif kind == 'cancelled':
                self._save_started = None
        for _runtime, ticket, result in getattr(self.service, 'recoveries', list)():
            if result is not None and not result.completed and ticket not in self._toasted_failures:
                self._toasted_failures.add(ticket)
                self._save_started = None
                self._set_recent('실패 · 저장 내역·복구에서 확인하세요')
                self._react('저장 실패 · 앱에서 확인', 'failed', self._last_target)
        entries = getattr(self.service, 'recoveries', list)()
        self._update_save_toast(sum(r is None for _, _, r in entries))
        if self.panel is not None:
            text = _STATES.get(self.service.status, '게임 실행 대기')
            if self._mode == 'combat' and self.service.enabled and self.service.status not in ('error', 'disabled'):
                text = combat_text(self._gate)
            self.panel.status.setText(text)
            self._show_mode_notice()
            native = getattr(getattr(self.service, 'producer', None), 'native', None)
            border = getattr(native, 'border_note', None)  # Windows 11 캡처 테두리를 끄지 못했을 때만
            self.panel.capture_info.setText('게임 화면만 · 1080p / 60FPS · 게임 소리는 저장하지 않아요'
                                            + ('\n' + border if border else ''))
            retention = self.service._retention // 60_000_000
            self.panel.available.setText(f'확보한 영상 {_toast_duration(duration)} / 설정 {retention}분')
            self.panel.folder.setText(str(self.service.settings.output_folder))
            # 녹화 오류는 매 틱 반영하되, 오류가 없을 때 직접 띄운 안내(단축키 변경 실패·지난 실행 임시 자료)를 지우지 않는다.
            # 녹화 오류가 풀린 순간에만 오류 줄을 비운다(0.16.0 QA: 0.1초 뒤 안내가 사라지던 문제).
            if self.service.error:
                self._show_error(self.service.error)
                self._service_error_shown = True
            elif getattr(self, '_service_error_shown', False):
                self._service_error_shown = False
                self._show_error(None)
            running = sum(r is None for _, _, r in entries)
            if running:
                self._set_recent(self._progress_text(running))
            for kind, result in completed:
                if kind == 'saved':
                    self._save_started = None
                    name = getattr(getattr(result, 'output', None), 'name', '') or str(getattr(result, 'output', ''))
                    detail = f" · {_toast_duration(result.duration_us)} 영상" if getattr(result, 'duration_us', None) else ''
                    self._set_recent(time.strftime('%H:%M') + detail + (f' · {name}' if name else '') +
                                     (f' · {result.cleanup_error}' if getattr(result, 'cleanup_error', None) else ''))
                elif kind in ('rejected', 'cancelled'):
                    self._set_recent(('실패 · ' if kind == 'rejected' else '') + str(result))
        if self._recovery_dialog is not None and self._recovery_dialog.isVisible():
            self._recovery_dialog.refresh()

    def _update_save_toast(self, running):
        """게임 화면 저장 진행 알림(0.14.2): 접수부터 끝날 때까지 유지, 1초마다 퍼센트 갱신. 완료·실패만 3초 뒤 사라짐."""
        toast = getattr(self, '_toast', None)
        if toast is None or not self._allowed():
            return
        if running <= 0:
            if toast.sticky:
                toast.hide_message()  # 저장이 없는데 진행 알림이 남지 않게(완료·실패 3초 알림은 그대로)
            return
        if not toast.sticky and toast.isVisible():
            return  # 방금 뜬 완료·실패 알림은 3초 동안 둔다
        codec = getattr(self.service, 'codec', None)
        snapshot = codec.progress_snapshot() if codec is not None and hasattr(codec, 'progress_snapshot') else None
        if snapshot is not None and snapshot[0] == 'validate':
            text = '저장 마무리 중'
        else:
            fraction = snapshot[3] if snapshot is not None else None
            text = f'저장 중 {round((fraction or 0) * 100)}%'
            if running > 1:
                text += f' · 대기 {running - 1}'
        if text != toast.text() or not toast.isVisible():
            toast.show_message(text, 'pending', self._screen_rect(self._last_target), sticky=True)

    def _progress_text(self, running):
        """저장 진행 표시(0.14.1): 저장 분량·경과·인코딩 퍼센트 또는 마무리 확인, 뒤에 기다리는 저장 수."""
        codec = getattr(self.service, 'codec', None)
        snapshot = codec.progress_snapshot() if codec is not None and hasattr(codec, 'progress_snapshot') else None
        if snapshot is None:
            # 인코딩 전후(접수 직후·검증 뒤 게시 중)에는 앞 작업이 없을 수 있다: 1건이면 중립 문구(0.14.2)
            return '저장 준비·마무리 중' if running == 1 else f'저장 대기 {running}건 · 앞 작업이 끝나면 시작해요'
        stage, duration_us, elapsed, fraction = snapshot
        if getattr(self, '_save_started', None) is None:
            self._save_started = time.monotonic() - elapsed
        elapsed = int(elapsed)
        text = f'저장 중 · {_toast_duration(duration_us)} 분량 · 경과 {elapsed // 60}:{elapsed % 60:02d}'
        if stage == 'validate':
            text += ' · 마무리 확인 중(검증)'
        elif fraction is not None:
            text += f' · 약 {round(fraction * 100)}% (인코딩)'
        else:
            text += ' · 인코딩 시작 중'
        if running > 1:
            text += f'\n다음 저장 대기 {running - 1}건 · 앞 저장이 끝나면 시작해요'
        return text

    def _update_badge(self, available_us):
        badge = getattr(self.window, '_blackbox_badge', None)
        if badge is None:
            return
        if not self._badge_wired:
            self._badge_wired = True
            badge.clicked.connect(self._badge_clicked)
        state = (blackbox_badge(self.service, available_us, self._gate if self._mode == 'combat' else None)
                 if self._allowed() else None)
        self._badge_kind = state[1] if state is not None else None
        badge.setVisible(state is not None)
        if state is not None:
            badge.setText(state[0])
            style = getattr(type(self.window), 'status_style', None)
            color = BADGE_COLORS[state[1]]
            badge.setStyleSheet(style(color) if style else f'color:{color}; font-size:12px; border:none;')
            badge.setToolTip(BADGE_TIPS[state[1]])

    def _badge_clicked(self):
        """상단 배지(0.17.2 사용자 결정): 모든 상태에서 블랙박스 탭으로 이동한다. 끄기는 탭의 '블랙박스 사용'에서 한다."""
        if not self._allowed():
            return
        self._open_tab()

    def _open_tab(self):
        if self._page is not None and self.window._tabs.indexOf(self._page) >= 0:
            self.window._tabs.setCurrentWidget(self._page)

    def system_message(self, message, wparam):
        if self.events is not None:
            self.events.message(message, wparam)

    def show_recovery(self):
        if self.service is None:
            return
        from .blackbox_recovery import BlackboxRecovery
        if self._recovery_dialog is None:
            self._recovery_dialog = BlackboxRecovery(self.service, self.window)
        else:
            self._recovery_dialog.refresh()
        self._recovery_dialog.show()
        self._recovery_dialog.raise_()

    def _set_retention(self, minutes):
        from .. import config
        if not self._allowed() or self.service._closing:
            return
        config.save_blackbox_preference('retentionMinutes', int(minutes))
        self.service.set_retention(int(minutes) * 60_000_000)

    def _change_hotkey(self):
        """저장 단축키 변경 창(0.16.0). 저장하면 설정에 남기고 앱 재시작 없이 바로 새 조합으로 바꾼다."""
        if not self._allowed() or self._hotkey is None:
            return
        from .blackbox_hotkey_dialog import HotkeyDialog
        dialog = HotkeyDialog(self._hotkey, self.window)
        self._capturing_hotkey = True  # 변경 창에서 누른 기존 조합이 '게임 창이 앞에 없어 저장 실패' 알림을 띄우지 않게
        try:
            accepted = dialog.exec()
        finally:
            self._capturing_hotkey = False
        chosen = dialog.result_hotkey if accepted else None
        dialog.deleteLater()
        if chosen is None:
            self._discard_hotkey_input()
            return
        self._apply_hotkey(chosen)

    def _apply_hotkey(self, chosen):
        from .. import config
        try:
            config.save_blackbox_preference('hotkey', chosen)
            if self.events is not None:
                self.events.set_hotkey(*chosen)  # 훅은 유지하고 조합만 교체: 녹화·저장 진행에 영향 없음
        except Exception as exc:
            self._show_error(f'단축키를 바꾸지 못했어요: {exc}')
            return
        self._hotkey = tuple(chosen)
        if self.panel is not None:
            self.panel.hotkey.setText(hotkey_text(*self._hotkey))

    def _discard_hotkey_input(self):
        discard = getattr(getattr(self.events, 'observer', None), 'discard', None)
        if discard is not None:
            discard()

    def _change_folder(self):
        if not self._allowed():
            return
        from dataclasses import replace
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self.window, '블랙박스 저장 폴더', str(self.service.settings.output_folder))
        if folder:
            from .. import config
            self._action(lambda: config.save_blackbox_preference('outputFolder', folder))
            if config.load_blackbox_preferences().get('outputFolder') == folder:
                self.service.settings = replace(self.service.settings, output_folder=Path(folder))

    def _open_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if self._allowed():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.settings.output_folder)))
