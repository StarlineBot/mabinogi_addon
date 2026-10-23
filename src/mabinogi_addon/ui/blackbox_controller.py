"""제작자 전용 최상위 진입점. 캡처 어댑터가 없는 제품 상태에서는 조작을 열지 않는다."""

from PySide6.QtCore import QObject, QTimer

from ..feature_access import is_creator
from .blackbox_tab import BlackboxTab


# 가상 키 코드 → 사용자가 아는 키 이름. 'VK 79'처럼 16진 코드로 보이면 실제 키(F10)를 알 수 없다.
_KEY_NAMES = {0x08: 'Backspace', 0x09: 'Tab', 0x0D: 'Enter', 0x13: 'Pause', 0x14: 'CapsLock',
              0x1B: 'Esc', 0x20: 'Space', 0x21: 'PageUp', 0x22: 'PageDown', 0x23: 'End',
              0x24: 'Home', 0x25: '←', 0x26: '↑', 0x27: '→', 0x28: '↓', 0x2C: 'PrintScreen',
              0x2D: 'Insert', 0x2E: 'Delete', 0x6A: 'Num *', 0x6B: 'Num +', 0x6D: 'Num -',
              0x6E: 'Num .', 0x6F: 'Num /', 0x90: 'NumLock', 0x91: 'ScrollLock', 0xBA: ';',
              0xBB: '=', 0xBC: ',', 0xBD: '-', 0xBE: '.', 0xBF: '/', 0xC0: '`', 0xDB: '[',
              0xDC: '\\', 0xDD: ']', 0xDE: "'"}
_HOTKEY_NOTE_SEC = 6.0
_STATES = {'recording': '보관 중', 'preparing': '녹화 준비 중', 'paused': '일시정지',
           'pausing': '중단 구간 정리 중', 'disabled': '사용 안 함', 'error': '녹화 오류'}


def save_failure_reason(exc) -> str:
    """저장 요청 거부의 짧은 이유(게임 화면 오버레이용). 자세한 문구는 앱 탭에 남는다."""
    if isinstance(exc, PermissionError):
        return '확보한 영상 없음'
    if isinstance(exc, RuntimeError) and 'already reserved' in str(exc):
        return '이미 저장 중이에요'
    return '앱에서 확인해 주세요'


def _toast_duration(us):
    from .blackbox_toast import format_duration
    return format_duration(us)


def blackbox_badge(service, available_us=0):
    """상단 블랙박스 상태(명세 11.2). '블랙박스 사용'이 꺼져 있으면 None(숨김)."""
    if service is None or not getattr(service, 'enabled', False) or getattr(service, 'status', None) == 'disabled':
        return None
    if service.status == 'recording':
        seconds = max(0, int(available_us) // 1_000_000)
        return f'블랙박스: 보관 중 {seconds // 60}:{seconds % 60:02d}', 'neutral'
    if service.status == 'error':
        return '블랙박스: 녹화 오류', 'error'
    return '블랙박스: ' + _STATES.get(service.status, '게임 대기'), 'neutral'


def key_name(vk):
    if 0x70 <= vk <= 0x87:
        return f'F{vk - 0x6F}'
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f'Num {vk - 0x60}'
    return _KEY_NAMES.get(vk, f'키 코드 0x{vk:02X}')


def hotkey_text(modifiers, vk):
    """RegisterHotKey 수식 마스크(Alt=1, Ctrl=2, Shift=4, Win=8)와 키 코드를 'Ctrl+Alt+F10' 형식으로."""
    keys = [name for mask, name in ((2, 'Ctrl'), (1, 'Alt'), (4, 'Shift'), (8, 'Win')) if modifiers & mask]
    return '+'.join(keys + [key_name(vk)])


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
        self._hotkey_note = None  # (문구, 표시 종료 monotonic) — 단축키 반응을 오류 문구에 묻히지 않게
        self._hotkey_base = None  # '검증용 단축키: …' 줄
        self._hotkey_last = None  # '마지막 단축키 입력 HH:MM:SS · 결과' — 앱으로 돌아와도 남아 있게
        self._toast = None  # 게임 화면 위 저장 반응(명세 11.1)
        self._last_target = None  # 마지막으로 관측한 게임 창: 완료·실패 반응도 게임 모니터에 띄운다
        self._toasted_failures = set()
        self._badge_wired = False
        self.panel = None
        self._page = None
        self.refresh_access()

    def _allowed(self):
        try:
            return is_creator() is True and not getattr(self.window, '_closing', False)
        except Exception:
            return False

    def refresh_access(self):
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
            tabs.insertTab(tabs.indexOf(self.window._settings_scroll), self._page, '블랙박스')
            self._connect_service()

    def _require_session(self):
        if not self._allowed():
            raise PermissionError('creator access required')
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
            self.show_recovery()
            return False
        if self.lifecycle is None:
            return True
        ready = self.lifecycle.prepare_close()
        self.close_error = self.lifecycle.pending_reason
        if not ready and self.panel is not None:
            self.panel.status.setText('종료 대기 · 저장 결과 또는 복구 자료를 확인해야 해요.')
        return ready

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
                events = WindowsEvents(int(self.window.winId()), profile['hotkey_modifiers'], profile['hotkey_vk'])
                try:
                    service = BlackboxService(settings, enabled=config.load_blackbox_enabled(),
                                              persist_enabled=config.save_blackbox_enabled)
                    service.set_retention(preferences.get('retentionMinutes', 10) * 60 * 1_000_000)
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
                self.panel.status.setText('녹화 준비 실패: ' + self._profile_error)
            return
        panel = self.panel
        panel.preview_notice.setText('제작자 알파 · Windows 실게임 검증 전이에요.')
        failures = getattr(self.service, 'leftover_failures', None)
        if failures:
            # 지난 실행이 남긴 임시 자료를 자동 정리하지 못했을 때만 안내한다(정리 성공은 조용히).
            panel.save_result.setText(f'지난 실행에서 남은 블랙박스 임시 자료 {len(failures)}건을 지우지 못했어요. '
                                      '다음 실행 때 다시 정리해요.')
        panel.audio_info.setText('게임 소리: 대상 프로세스만 · 동기화 검증 전' if self.service.settings.audio
                                 else '게임 소리: 영상 전용 검증 설정 · 소리는 저장하지 않아요.')
        panel.enabled.setChecked(self.service.enabled)
        panel.retention.setText(str(self.service._retention // 60_000_000))
        if profile:
            self._hotkey_base = ('검증용 단축키: ' + hotkey_text(profile.get('hotkey_modifiers', 0),
                                                              profile['hotkey_vk']) + ' · 실게임 미검증')
            self._show_hotkey()
        for control in (panel.enabled, panel.retention, panel.save, panel.change_folder, panel.open_folder, panel.recovery):
            control.setEnabled(True)
        panel.enabled.toggled.connect(lambda value: self._action(lambda: self.service.set_enabled(value)))
        panel.save.clicked.connect(lambda checked=False: self._request_save())
        panel.retention.editingFinished.connect(lambda: self._action(self._set_retention))
        panel.change_folder.clicked.connect(self._change_folder)
        panel.open_folder.clicked.connect(self._open_folder)
        panel.recovery.clicked.connect(self.show_recovery)

    def _action(self, operation):
        try:
            return operation()
        except Exception as exc:
            if self.panel is not None:
                self.panel.save_result.setText(str(exc))
            self.close_error = str(exc)

    def _request_save(self, request_us=None):
        import time
        if self._allowed() and self.service is not None:
            try:
                self.service.request_save(time.perf_counter_ns() // 1000 if request_us is None else request_us)
            except Exception as exc:
                if self.panel is not None:
                    self.panel.save_result.setText(str(exc))
                self.close_error = str(exc)
                self._react('저장하지 못했어요 · ' + save_failure_reason(exc), 'failed', self._last_target)
                return
            self._react('영상 저장 중…', 'pending', self._last_target)

    def _react(self, text, kind, target=None):
        """게임 화면 오버레이 문구 + 효과음(접수·실패만). 전투 보조 일시정지와 무관하게 표시한다(저장 확인)."""
        if not self._allowed():
            return
        from .blackbox_toast import BlackboxToast
        from .notifier import play_blackbox_sound
        if self._toast is None:
            self._toast = BlackboxToast()
        self._toast.show_message(text, kind, self._screen_rect(target))
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

    def _show_hotkey(self):
        if self.panel is None or self._hotkey_base is None:
            return
        self.panel.hotkey.setText(self._hotkey_base + ('\n' + self._hotkey_last if self._hotkey_last else ''))

    def _note_hotkey(self, text, result):
        import time
        self._hotkey_note = (text, time.monotonic() + _HOTKEY_NOTE_SEC)
        # 게임→앱 전환 사이에 6초 강조가 사라져도 마지막 입력 시각·결과는 계속 남긴다.
        self._hotkey_last = f"마지막 단축키 입력 {time.strftime('%H:%M:%S')} · {result}"
        self._show_hotkey()

    def _hotkey_pressed(self, shortcut, target, active):
        """단축키 입력마다 결과를 남긴다(저장 불가 상태 포함). 게임 창에서 받은 입력만 저장한다."""
        if not self._allowed():
            return
        if not (active and target is not None and shortcut[1] == target.hwnd):
            self._note_hotkey('단축키 입력을 받았어요 · 게임 창이 앞에 있을 때만 저장해요.',
                              '게임 창이 앞에 있지 않아 저장 안 함')
            self._react('저장하지 못했어요 · 게임 창이 앞에 있을 때만 저장해요', 'failed', target)
            return
        try:
            self.service.request_save(shortcut[0])
        except Exception as exc:
            reason = self.service.error or str(exc)
            self._note_hotkey(f'단축키 입력을 받았지만 지금은 저장할 수 없어요: {reason}', f'저장 불가: {reason}')
            self._react('저장하지 못했어요 · ' + save_failure_reason(exc), 'failed', target)
            return
        self._note_hotkey('단축키 입력을 받았어요 · 저장 요청을 접수했어요.', '저장 요청 접수')
        self._react('영상 저장 중…', 'pending', target)

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
        self._action(lambda: self.service.tick(target, active=active))
        try:
            shortcut = self.events.consume_hotkey()
            if shortcut is not None:
                self._hotkey_pressed(shortcut, target, active)
        except Exception as exc:
            self.close_error = str(exc)
            self.service.error = str(exc)
        runtime = getattr(self.service, 'current', None)
        duration = runtime.session._replay.available_us if runtime else 0
        self._update_badge(duration)
        # 저장 결과 반응(명세 11.1): 완료는 검증을 마친 결과에서만, 실패는 작업마다 한 번.
        for kind, result in self.service.completed:
            if kind == 'saved':
                self._react('영상 저장 완료' + (' · ' + _toast_duration(result.duration_us)
                                                if getattr(result, 'duration_us', None) else ''), 'done',
                            self._last_target)
            elif kind == 'rejected':
                self._react('저장하지 못했어요 · 앱에서 확인해 주세요', 'failed', self._last_target)
        for _runtime, ticket, result in getattr(self.service, 'recoveries', list)():
            if result is not None and not result.completed and ticket not in self._toasted_failures:
                self._toasted_failures.add(ticket)
                self._react('저장하지 못했어요 · 앱에서 확인해 주세요', 'failed', self._last_target)
        if self.panel is not None:
            self.panel.status.setText(_STATES.get(self.service.status, '게임 실행 대기'))
            self.panel.available.setText(f'확보한 영상 {duration // 1_000_000}초 / 설정 {self.service._retention // 60_000_000}분')
            self.panel.folder.setText(str(self.service.settings.output_folder))
            entries = self.service.recoveries()
            failures = [r for _, _, r in entries if r is not None and not r.completed]
            running = sum(r is None for _, _, r in entries)
            if failures:
                self.panel.save_result.setText('저장 실패 · 저장 내역·복구에서 확인하세요: ' + str(failures[0].error))
            elif running:
                self.panel.save_result.setText(f'저장 처리·대기 {running}건 · 녹화 상태는 위에서 확인하세요.')
            if self.service.error:
                self.panel.save_result.setText(self.service.error)
            note = self._hotkey_note
            if note is not None:
                import time
                if time.monotonic() < note[1]:
                    # 녹화 오류 문구가 매 틱 덮어써도 단축키를 눌렀다는 반응은 잠시 보이게 한다.
                    self.panel.save_result.setText(note[0])
                else:
                    self._hotkey_note = None
            for kind, result in self.service.completed:
                if kind == 'saved':
                    self.panel.save_result.setText(f'저장 완료: {result.output}' +
                        (f' · {result.cleanup_error}' if result.cleanup_error else ''))
                elif kind in ('rejected', 'cancelled'):
                    self.panel.save_result.setText(str(result))
        self.service.completed.clear()
        if self._recovery_dialog is not None and self._recovery_dialog.isVisible():
            self._recovery_dialog.refresh()

    def _update_badge(self, available_us):
        badge = getattr(self.window, '_blackbox_badge', None)
        if badge is None:
            return
        if not self._badge_wired:
            self._badge_wired = True
            badge.clicked.connect(self._open_tab)
        state = blackbox_badge(self.service, available_us) if self._allowed() else None
        badge.setVisible(state is not None)
        if state is not None:
            badge.setText(state[0])
            badge.setStyleSheet('color:#e74c3c;' if state[1] == 'error' else '')

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

    def _set_retention(self):
        from .. import config
        minutes = int(self.panel.retention.text())
        if not self._allowed() or self.service._closing or minutes <= 0:
            raise ValueError('보관 시간은 양의 정수로 입력하세요.')
        config.save_blackbox_preference('retentionMinutes', minutes)
        self.service.set_retention(minutes * 60_000_000)

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
