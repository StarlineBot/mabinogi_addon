"""Discord beta halo guidance with creator-only raw collection."""

import math
import time
from PySide6.QtCore import QSignalBlocker, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
import numpy as np

from .. import config, paths
from ..feature_access import Recheck, is_creator
from ..halo_capture import CaptureSession, MAX_PIXELS, MAX_SHOTS, MAX_BYTES
from ..setup_state import valid_box
from ..version import __version__
from ..detect.halo_timer import read_seconds
from ..tracker.halo import HaloTracker
from .dpi import to_physical
from .region_registration import connect_selection
from .settings_layout import disclosure
from .widgets import FeatureHeader, CapturePathLabel, checkbox, wrapping_row


class HaloCaptureSection(QWidget):
    access_changed = Signal(bool)

    def __init__(self, watcher, grab, parent=None):
        super().__init__(parent)
        self._watcher, self._grab = watcher, grab
        self._pattern_warning = getattr(parent, '_overlay', None)
        self._shutting_down = False
        self._selector = self._highlight = None
        self._autofind_busy = False
        self._autofind_highlight = None
        self._autofind_target = None
        self._session = None
        self._region_generation = 0
        self._region_keys = ('halo_timer',)
        self._last_frame = None
        self._target = None
        self._clock = HaloTracker()
        self._battle_target = None
        self._notifier = None
        self._preview_until = float('-inf')
        self._boss_id = None
        self._boss_seen = float('-inf')
        from .pattern_overlay import PatternWarningOverlay
        self._warning = PatternWarningOverlay(sample='헤일로 5초 전', font_scale=.85,
                                              bold=False, text_color='#F2E8CB')
        self._warning.moved.connect(self._save_warning_position)
        self._countdown = PatternWarningOverlay(sample='다음 헤일로 00:51', font_scale=.85,
                                                bold=False, text_color='#F2E8CB')
        self._countdown.moved.connect(self._save_countdown_position)
        self._root = paths.user_data_dir() / "halo_timer_shots"
        raw = config._read_local_config().get("haloTimer", {})
        self._region = raw.get("box") if isinstance(raw, dict) and valid_box(raw.get("box")) else None
        pos = raw.get('warnPos') if isinstance(raw, dict) else None
        self._warning_positioned = isinstance(pos, dict) and all(type(pos.get(k)) is int for k in ('x', 'y'))
        if self._warning_positioned:
            self._warning.move(pos['x'], pos['y'])
        pos = raw.get('countdownPos') if isinstance(raw, dict) else None
        self._countdown_positioned = isinstance(pos, dict) and all(type(pos.get(k)) is int for k in ('x', 'y'))
        if self._countdown_positioned:
            self._countdown.move(pos['x'], pos['y'])
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(FeatureHeader("믿음의 균열의 1분 헤일로 알림", "게임의 남은 시간을 기준으로 다음 헤일로까지 표시하고, 발생 5초 전에 알립니다."))
        self.state = QLabel("레넨의 미이르 : 회한 식별 대기")
        self.state.setWordWrap(True)
        warning_group = QGroupBox('헤일로 경고')
        warning_layout = QVBoxLayout(warning_group)
        options = QHBoxLayout()
        self.warn_lock = QPushButton('경고 위치 잠금됨')
        self.warn_lock.setCheckable(True)
        self.warn_lock.setChecked(True)
        from .settings_layout import LOCK_STYLE
        self.warn_lock.setStyleSheet(LOCK_STYLE)
        self.warn_lock.clicked.connect(self._toggle_warning_lock)
        options.addWidget(self.warn_lock)
        self.preview_alert = QPushButton('알림 미리보기')
        self.preview_alert.clicked.connect(self._preview_warning)
        options.addWidget(self.preview_alert)
        self.sound = checkbox('소리 알림')
        self.sound.setChecked(isinstance(raw, dict) and raw.get('sound') is True)
        self.sound.toggled.connect(self._save_sound)
        options.addStretch()
        warning_layout.addLayout(options)
        warning_layout.addWidget(self.sound)
        countdown_group = QGroupBox('다음 헤일로 표시')
        countdown_layout = QVBoxLayout(countdown_group)
        countdown_options = QHBoxLayout()
        self.countdown_lock = QPushButton('카운트다운 위치 잠금됨')
        self.countdown_lock.setCheckable(True)
        self.countdown_lock.setChecked(True)
        self.countdown_lock.setStyleSheet(LOCK_STYLE)
        self.countdown_lock.clicked.connect(self._toggle_countdown_lock)
        countdown_options.addWidget(self.countdown_lock)
        countdown_options.addStretch()
        countdown_layout.addLayout(countdown_options)
        v.addWidget(QLabel("판독 영역 · 전투 제한 시간"))
        self.region_label = QLabel()
        self.region_label.setWordWrap(True)
        v.addWidget(self.region_label)
        row = QHBoxLayout()
        self.auto_find_btn = QPushButton('자동 찾기')
        self.auto_find_btn.clicked.connect(self._on_auto_find)
        self.region_btn = QPushButton("직접 지정")
        self.view_btn = QPushButton("지정 영역 보기")
        self.clear_btn = QPushButton("지정 해제")
        for button in (self.auto_find_btn, self.region_btn, self.view_btn):
            row.addWidget(button)
        from .settings_layout import DANGER_STYLE
        self.clear_btn.setStyleSheet(DANGER_STYLE)
        commands = QHBoxLayout()
        commands.addStretch(1)
        commands.addWidget(self.clear_btn)
        self.region_row = wrapping_row(row, commands)
        v.addLayout(self.region_row)
        guide = QLabel('게임 상단의 남은 시간이 분·초까지 모두 들어오도록 지정해 주세요.\n보스 이름을 확인한 뒤 남은 시간을 기준으로 안내해요.')
        guide.setWordWrap(True)
        v.addWidget(guide)
        self.region_btn.clicked.connect(self._pick)
        self.view_btn.clicked.connect(self._view)
        self.clear_btn.clicked.connect(self._clear)
        self.preview = QLabel("원본 미리보기 대기")
        self.preview.setFixedHeight(52)
        self.preview.setFixedWidth(120)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet('background:palette(base);border:1px solid palette(mid);')
        preview_row = QHBoxLayout()
        preview_row.addWidget(self.preview)
        self.reading = QLabel('판독 시간: —')
        self.reading.setStyleSheet('font-size:14px;font-weight:600;')
        preview_row.addWidget(self.reading)
        preview_row.addStretch()
        preview_group = QGroupBox('판독 미리보기')
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.addLayout(preview_row)
        preview_layout.addWidget(self.state)
        v.addWidget(preview_group)
        v.addWidget(countdown_group)
        v.addWidget(warning_group)
        tools = QWidget()
        box = QVBoxLayout(tools)
        self.collect = checkbox("수집 모드")
        self.collect.toggled.connect(self._toggle)
        box.addWidget(self.collect)
        row = QHBoxLayout()
        self.snapshot = QPushButton("스냅샷 저장")
        self.folder = QPushButton("폴더 열기")
        row.addWidget(self.snapshot)
        row.addWidget(self.folder)
        row.addStretch()
        box.addLayout(row)
        self.snapshot.clicked.connect(self._snapshot)
        self.folder.clicked.connect(self._open_folder)
        self.saved = CapturePathLabel()
        box.addWidget(self.saved)
        hint = QLabel("레넨의 미이르 : 회한 식별 중 시간 값이 바뀌면 원본 PNG와 캡처 정보를 저장합니다. 판독 불가 시 숫자 모양 변화를 기준으로 수집하므로 배경 변화가 포함될 수 있습니다. 초당 최대 1장, 세션당 900장 또는 100MB까지 수집합니다.")
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.disclosure = disclosure("진단 · 시간 자료 수집", tools, v)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._refresh()

    def set_boss_context(self, boss_id):
        """Only the existing name matcher supplies this context, never the timer OCR."""
        self._boss_id = boss_id
        self._boss_seen = time.monotonic()
        if boss_id is not None and boss_id != 'lenen_miir_hoehan':
            self._clock.stop()
            self._battle_target = None
            self._hide_live_overlays()

    def _hide_live_overlays(self):
        previewing = (time.monotonic() < self._preview_until and self._allowed()
                      and not getattr(self.window(), '_paused', False))
        if not previewing:
            self._stop_audio()
        for overlay in (self._warning, self._countdown):
            if overlay.locked and not (overlay is self._warning and previewing):
                overlay._timer.stop()
                overlay.hide()

    def _target_boss_active(self):
        return (self._boss_id == 'lenen_miir_hoehan'
                and time.monotonic() - self._boss_seen <= 1.5)

    def _stop_monitoring(self):
        self._clock.stop()
        self._battle_target = None
        self._preview_until = float('-inf')
        self._stop_audio()
        for overlay in (self._warning, self._countdown):
            overlay._timer.stop()
            overlay.hide()
        self.reading.setText('판독 시간: —')

    def _place_warning(self):
        self._place_countdown()
        if not self._warning_positioned:
            self._countdown._relayout()
            self._warning.move(self._countdown.x(), self._countdown.y() + self._countdown.height() + 8)

    def _place_countdown(self):
        if self._countdown_positioned:
            return
        reference = self._pattern_warning
        if reference is not None:
            reference._relayout()
            self._countdown.move(reference.x(), reference.y() + reference.height() + 8)

    def _toggle_warning_lock(self):
        if not self._allowed():
            return
        self._place_warning()
        self._warning.set_locked(not self._warning.locked)
        self.warn_lock.setChecked(self._warning.locked)
        self.warn_lock.setText('경고 위치 잠금됨' if self._warning.locked else '경고 위치 잠금')

    def _toggle_countdown_lock(self):
        if not self._allowed():
            return
        self._place_countdown()
        self._countdown.set_locked(not self._countdown.locked)
        self.countdown_lock.setChecked(self._countdown.locked)
        self.countdown_lock.setText('카운트다운 위치 잠금됨' if self._countdown.locked else '카운트다운 위치 잠금')

    def _save_countdown_position(self):
        self._save_overlay_position(self._countdown, 'countdownPos')

    def _save_warning_position(self):
        self._save_overlay_position(self._warning, 'warnPos')

    def _save_overlay_position(self, overlay, key):
        if not self._allowed():
            return
        raw = config._read_local_config()
        section = raw.get('haloTimer')
        section = dict(section) if isinstance(section, dict) else {}
        section[key] = dict(x=overlay.x(), y=overlay.y())
        raw['haloTimer'] = section
        try:
            config._write_local_config(raw)
            if key == 'warnPos':
                self._warning_positioned = True
            else:
                self._countdown_positioned = True
        except OSError:
            self.state.setText('경고 위치를 저장하지 못했습니다.')

    def _save_sound(self, checked):
        if not checked:
            self._stop_audio()
        if not self._allowed():
            return
        raw = config._read_local_config()
        section = raw.get('haloTimer')
        section = dict(section) if isinstance(section, dict) else {}
        previous = section.get('sound') is True
        section['sound'] = bool(checked)
        raw['haloTimer'] = section
        try:
            config._write_local_config(raw)
        except OSError:
            with QSignalBlocker(self.sound):
                self.sound.setChecked(previous)
            self.state.setText('소리 설정을 저장하지 못했습니다.')

    def _stop_audio(self):
        notifier, self._notifier = self._notifier, None
        if notifier is not None:
            notifier.stop()
            notifier.deleteLater()

    def _preview_warning(self):
        if not self._allowed() or getattr(self.window(), '_paused', False):
            return
        self._place_warning()
        self._preview_until = time.monotonic() + 2.5
        self._warning.show_message('헤일로 5초 전', 2500)
        self._play_warning(preview=True)

    def _play_warning(self, *, preview=False):
        if (not self._allowed() or not self.sound.isChecked() or not preview and not self._warning.locked
                or not preview and not self._watcher.is_game_active()
                or getattr(self.window(), '_paused', False)):
            return
        try:
            from .notifier import SoundNotifier
            sound = paths.resource_dir() / 'sounds' / '헤일로 알림.mp3'
            if not sound.is_file():
                return
            if self._notifier is None:
                self._notifier = SoundNotifier({'halo':sound}, parent=self, volume=0.8)
            self._notifier.play('halo')
        except Exception:
            # Audio failure must not stop the independent clock or visual warning.
            self._stop_audio()

    @staticmethod
    def _time_text(seconds):
        value = max(0, math.ceil(seconds))
        return f'{value // 60:02}:{value % 60:02}'

    def _monitor(self, raw):
        paused = getattr(self.window(),'_paused',False)
        for overlay in (self._warning,self._countdown):
            if overlay._paused != paused: overlay.set_paused(paused)
        if paused: self._stop_audio()
        if not self._allowed():
            self._stop_monitoring()
            return
        now = time.monotonic()
        target = self._target[:2] if self._target else None
        if self._battle_target is not None and target != self._battle_target:
            self._stop_monitoring()
            self._boss_id = None
            self._boss_seen = float('-inf')
        context = (self._target_boss_active() or
                   self._battle_target is not None and target == self._battle_target and self._clock.armed)
        if context and not self._clock.armed:
            self._clock.arm()
        result = self._clock.observe(raw, now, eligible=context,
                                     target=target)
        if not context:
            self._hide_live_overlays()
            self.state.setText('레넨의 미이르 : 회한 식별 대기')
        elif result.phase == 'synced':
            self._battle_target = target
            following = ('다음 헤일로 없음' if result.until_halo is None else
                         f'다음 헤일로까지 {self._time_text(result.until_halo)}')
            self.state.setText(f'감시 중 · {following}')
            self._place_warning()
            if result.until_halo is not None:
                self._place_countdown()
                self._countdown.show_message('다음 헤일로 ' + self._time_text(result.until_halo), 1500)
            elif self._countdown.locked:
                self._countdown.hide()
            if result.warning is not None:
                self._warning.show_message('헤일로 5초 전', 5000)
                self._play_warning()
        else:
            if result.phase in ('stopped', 'ended'):
                self._battle_target = None
                self._boss_id = None
                self._boss_seen = float('-inf')
            self._hide_live_overlays()
            self.state.setText('시간 판독 확인 중 · 경고 보류')

    def set_paused(self, paused):
        for overlay in (self._warning, self._countdown):
            overlay.set_paused(paused)
            if not paused and not overlay.locked and self._allowed():
                overlay.set_locked(False)
        if paused:
            self._preview_until = float('-inf')
            self._stop_audio()

    def _login(self):
        """로그인·제작자 판정(config.json 읽기)을 500ms 타이머마다 하지 않고 1초 동안 재사용한다(0.17.2)."""
        checks = self.__dict__.get('_access_checks')
        if checks is None:
            checks = self.__dict__['_access_checks'] = (Recheck(lambda: bool(config.load_discord_user())),
                                                        Recheck(lambda: is_creator()))
        return checks

    def login_refresh(self):
        """로그인 변경(login_changed): 판정을 바로 다시 읽고 한 번 갱신한다."""
        for check in self._login():
            check.invalidate()
        self._tick()

    def _allowed(self):
        window = self.window()
        return (self._login()[0]() and not self._shutting_down and not getattr(window, "_closing", False)
                and not getattr(window, "_config_pending_restart", False))

    def _collect_allowed(self):
        return self._allowed() and self._login()[1]()

    def _logged_in(self):
        return self._allowed()

    def _autofind_capture(self):
        from ..autofind_diagnostics import capture_info
        from .screen_grab import capture_for_autofind
        from .region_registration import editing_allowed
        result = capture_for_autofind(require_game=True, strict_game=True,
            restore_allowed=lambda:editing_allowed(self), capture_allowed=self._allowed,
            restore_widget_allowed=lambda widget:widget not in (self._warning,self._countdown))
        info = capture_info.get() or {}
        target = info.get('game_target')
        self._autofind_target = tuple(target) if target else None
        return result

    def _autofind_applicable(self):
        from ..system.window_capture import registered_game_target
        return (self._allowed() and self._autofind_target is not None
                and registered_game_target(self._autofind_target)==self._autofind_target)

    def _on_auto_find(self):
        if not self._allowed() or self._autofind_busy:
            return
        from .autofind_confirm import confirm_autofind
        self._stop()
        self._stop_monitoring()
        self._close_marks()
        confirm_autofind(self,'halo_timer','전투 제한 시간 (분:초)',self._save_region,
                         capture=self._autofind_capture,allowed=self._autofind_applicable)

    def _refresh(self):
        allowed = self._allowed()
        self.setVisible(allowed)
        self.access_changed.emit(allowed)
        self.region_label.setText("영역 미등록" if self._region is None else
            "등록 영역 {x}, {y} / {w} × {h}".format(**self._region))
        self.region_btn.setEnabled(allowed)
        self.auto_find_btn.setEnabled(allowed and not self._autofind_busy)
        for button in (self.view_btn, self.clear_btn):
            button.setEnabled(allowed and self._region is not None)
        collect_allowed = self._collect_allowed()
        self.collect.setEnabled(collect_allowed and self._region is not None)
        self.snapshot.setEnabled(collect_allowed and self._region is not None)
        self.folder.setEnabled(collect_allowed)
        self.disclosure.setVisible(collect_allowed)
        self.collect.parentWidget().setVisible(collect_allowed and self.disclosure.isChecked())
        self.sound.setEnabled(allowed)
        session = self._session
        self.saved.setText((f"저장 {session.count}장 · {session.bytes:,}바이트\n{session.path}" if session else
                            f"저장 0장\n{self._root}"))

    def _stop(self):
        with QSignalBlocker(self.collect):
            self.collect.setChecked(False)
        if self._session is not None:
            self._session.stop()
        self._last_frame = None

    def _toggle(self, checked):
        if not checked or not self._collect_allowed() or not self._region:
            self._stop()
            return
        if self._session is not None and self._session.thread is not None:
            self._stop()
            self.state.setText("이전 저장 작업이 끝난 뒤 다시 시작하세요.")
            return
        self._session = CaptureSession(self._root)
        self.state.setText("시간 원본 수집 중")
        self._refresh()

    def _save_region(self, x, y, w, h):
        if not self._allowed():
            return
        box = dict(x=x, y=y, w=w, h=h)
        if not valid_box(box) or w*h > MAX_PIXELS:
            self.state.setText("시간 숫자를 감싸는 작은 영역을 지정하세요.")
            return
        self._persist(box)

    def _persist(self, box):
        raw = config._read_local_config()
        section = raw.get("haloTimer")
        section = dict(section) if isinstance(section, dict) else {}
        section["box"] = box
        raw["haloTimer"] = section
        config._write_local_config(raw)
        from .region_registration import invalidate_region
        invalidate_region('halo_timer')
        self._stop()
        self._stop_monitoring()
        self._region = box
        self._region_generation += 1
        self.preview.clear()
        self._refresh()

    def _pick(self):
        if not self._allowed():
            return
        from .region_selector import RegionSelector
        self._stop()
        self._close_marks()
        self._selector = RegionSelector()
        connect_selection(self, self._selector, self._save_region)
        self._selector.start()

    def _view(self):
        if not self._allowed() or not self._region:
            return
        from .region_highlight import RegionHighlight
        self._close_marks()
        self._highlight = RegionHighlight()
        self._highlight.flash(*(self._region[k] for k in ("x", "y", "w", "h")), "전투 제한 시간", "분:초 숫자와 구분자")

    def _clear(self):
        if not self._allowed() or not self._region:
            return
        from PySide6.QtWidgets import QMessageBox
        from .region_registration import confirm_clear
        stamp = self._region_generation
        if (confirm_clear(self, "시간 영역 지정 해제", "시간 영역만 해제합니다. 기존 수집 파일과 보스 체력바 설정은 유지합니다.")
                != QMessageBox.StandardButton.Yes or not self._allowed() or stamp != self._region_generation):
            return
        try:
            self._persist(None)
            self._close_marks()
        except OSError:
            self.state.setText("영역을 저장하지 못했습니다. 기존 영역을 유지합니다.")

    def _capture(self):
        if (not self._allowed() or not self._region or not self._watcher.is_game_active()
                or self._selector is not None and self._selector.isVisible()):
            return None
        rect = to_physical(self._region)
        if rect[2] * rect[3] > MAX_PIXELS:
            return None
        target = self._foreground_target()
        if target is None:
            return None
        _,_,left,top,width,height = target
        x,y,w,h = rect
        if not (left <= x and top <= y and x+w <= left+width and y+h <= top+height):
            return None
        frame = self._grab(*rect)
        if frame is None or frame.shape[:2] != (h,w) or self._foreground_target() != target:
            return None
        self._target = target
        return frame

    def _foreground_target(self):
        from ..system.window_capture import registered_game_target
        try:
            import win32gui
            target = registered_game_target(self._target)
            if target is not None and win32gui.GetForegroundWindow() == target[0] and not win32gui.IsIconic(target[0]):
                return target
        except Exception:
            pass
        return None

    def _store(self, frame, force=False):
        if not self._collect_allowed() or not self._target_boss_active():
            return
        if self._session is None or self._session.cancelled.is_set():
            if self._session is not None and self._session.thread is not None:
                return
            self._session = CaptureSession(self._root)
        self._session.submit(frame, {"region_logical": dict(self._region),
            "region_physical": list(to_physical(self._region)), "source":"foreground_game_region",
            "game_target":self._target, "backend":"mss", "app_version":__version__,
            "raw_time":read_seconds(frame), "read_status":"observed"}, force=force)

    def _snapshot(self):
        if not self._collect_allowed():
            return
        if not self._target_boss_active():
            self.state.setText('수집 대기 · 레넨의 미이르 : 회한 식별 필요')
            return
        try:
            frame = self._capture()
            if frame is None:
                self.state.setText("캡처 불가 · 게임창과 지정 영역을 확인하세요.")
                return
            self._store(frame, force=True)
        except Exception:
            self._stop()
            self.state.setText("수집을 중단했습니다. 영역과 수집 한도를 확인하세요.")

    def _tick(self):
        try:
            self._refresh()
            if not self._allowed():
                self._stop()
                self._stop_monitoring()
                self._close_marks()
                self.preview.clear()
                return
            if self._autofind_busy or getattr(self.window(), '_setup_busy', lambda:False)():
                self._stop_audio()
                for overlay in (self._warning,self._countdown):
                    overlay._timer.stop()
                    overlay.hide()
                return
            if not self._collect_allowed():
                self._stop()
            if self._session is not None:
                error = self._session.poll()
                if error and error != "cancelled":
                    self._stop()
                    self.state.setText(error)
                    self._refresh()
                    return
                elif self._session.count >= MAX_SHOTS or self._session.bytes >= MAX_BYTES:
                    self._stop()
                    self.state.setText("수집 한도에 도달해 중단했습니다.")
                    self._refresh()
                    return
            if (not self.collect.isChecked() and not self.isVisible()
                    and not self._clock.armed and self._boss_id != 'lenen_miir_hoehan'):
                return
            frame = self._capture()
            if frame is None:
                self.preview.clear()
                self.reading.setText('판독 시간: —')
                self._monitor(None)
                self.state.setText("캡처 대기 · 게임창이 활성 상태인지 확인하세요.")
                return
            self._last_frame = frame
            raw_time = read_seconds(frame)
            self.reading.setText('판독 시간: ' + ('—' if raw_time is None else self._time_text(raw_time)))
            self._monitor(raw_time)
            rgb = np.ascontiguousarray(frame[:,:,::-1])
            h,w = rgb.shape[:2]
            img = QImage(rgb.data,w,h,rgb.strides[0],QImage.Format.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(img).scaled(360,48,Qt.AspectRatioMode.KeepAspectRatio)
            self.preview.setFixedSize(pixmap.width() + 2, pixmap.height() + 2)
            self.preview.setPixmap(pixmap)
            if self.collect.isChecked():
                self._store(frame)
            self._refresh()
        except Exception:
            self._stop()
            self._stop_monitoring()
            self.state.setText("캡처 또는 저장 실패로 수집을 중단했습니다.")

    def _open_folder(self):
        if self._collect_allowed():
            target = self._session.path if self._session else self._root
            try:
                target.mkdir(parents=True, exist_ok=True)
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
                    self.state.setText("폴더를 열지 못했습니다.")
            except OSError:
                self.state.setText("저장 폴더에 접근할 수 없습니다.")

    def _close_marks(self):
        if self._autofind_highlight is not None:
            self._autofind_highlight.close()
        for mark in (self._selector, self._highlight):
            if mark is not None:
                mark.close()
                mark.deleteLater()
        self._selector = self._highlight = None

    def shutdown(self):
        self._stop_monitoring()
        self._warning.close()
        self._countdown.close()
        self._shutting_down = True
        self._timer.stop()
        self._stop()
        self._close_marks()
