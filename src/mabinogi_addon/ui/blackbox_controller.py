"""제작자 전용 최상위 진입점. 캡처 어댑터가 없는 제품 상태에서는 조작을 열지 않는다."""

from PySide6.QtCore import QObject, QTimer

from ..feature_access import is_creator
from .blackbox_tab import BlackboxTab


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
        panel.audio_info.setText('게임 소리: 대상 프로세스만 · 동기화 검증 전' if self.service.settings.audio
                                 else '게임 소리: 영상 전용 검증 설정 · 소리는 저장하지 않아요.')
        panel.enabled.setChecked(self.service.enabled)
        panel.retention.setText(str(self.service._retention // 60_000_000))
        modifiers = profile.get('hotkey_modifiers', 0) if profile else 0
        keys = [name for mask, name in ((2, 'Ctrl'), (1, 'Alt'), (4, 'Shift'), (8, 'Win')) if modifiers & mask]
        if profile:
            keys.append(f"VK {profile['hotkey_vk']:02X}")
            panel.hotkey.setText('검증용 단축키: ' + '+'.join(keys) + ' · 실게임 미검증')
        for control in (panel.enabled, panel.retention, panel.save, panel.change_folder, panel.open_folder, panel.recovery):
            control.setEnabled(True)
        panel.enabled.toggled.connect(lambda value: self._action(lambda: self.service.set_enabled(value)))
        panel.save.clicked.connect(self._request_save)
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

    def _request_save(self):
        import time
        if self._allowed() and self.service is not None:
            self._action(lambda: self.service.request_save(time.perf_counter_ns() // 1000))

    def _tick(self):
        if self.service is None:
            return
        try:
            target, active = self.events.sample()
        except Exception as exc:
            target, active = None, False
            self.service.error = str(exc)
        self._action(lambda: self.service.tick(target, active=active))
        if self.panel is not None:
            states = {'recording': '보관 중', 'preparing': '녹화 준비 중', 'paused': '일시정지',
                      'pausing': '중단 구간 정리 중', 'disabled': '사용 안 함', 'error': '녹화 오류'}
            self.panel.status.setText(states.get(self.service.status, '게임 실행 대기'))
            runtime = self.service.current
            duration = runtime.session._replay.available_us if runtime else 0
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
            for kind, result in self.service.completed:
                if kind == 'saved':
                    self.panel.save_result.setText(f'저장 완료: {result.output}' +
                        (f' · {result.cleanup_error}' if result.cleanup_error else ''))
                elif kind in ('rejected', 'cancelled'):
                    self.panel.save_result.setText(str(result))
        self.service.completed.clear()
        if self._recovery_dialog is not None and self._recovery_dialog.isVisible():
            self._recovery_dialog.refresh()

    def system_message(self, message, wparam):
        if self.events is not None and self.events.message(message, wparam):
            # 글로벌 키는 게임 포그라운드에서만 접수한다.
            try:
                _, active = self.events.sample()
                if active:
                    self._request_save()
            except Exception as exc:
                self.close_error = str(exc)

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
