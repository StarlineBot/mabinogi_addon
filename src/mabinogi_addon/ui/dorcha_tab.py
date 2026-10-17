"""Independent opt-in beta display; no Tuarim alerts or saved values."""

import logging
from time import monotonic

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget

from .. import config
from ..detect.dorcha_reader import read_dorcha
from .dorcha_overlay import DorchaOverlay
from .widgets import checkbox, hint_label

_log = logging.getLogger(__name__)


class DorchaTab(QWidget):
    def __init__(self, watcher):
        super().__init__()
        self._watcher = watcher
        self._cfg = config.load_dorcha()
        self._region = self._cfg["box"]
        self._paused = False
        self._shutting_down = False
        self._autofind_busy = False
        self._autofind_highlight = None
        self._selector = None
        self._selector_timer_was_running = False
        self._highlight = None
        self._sct = None
        self._capture_failed = False
        self._save_failed = False
        self._overlay = None
        self._view = self
        self._tuarim_source = None
        self._percent_control = None
        self._percent = None
        self._live_box = None
        self._live_target = None
        self._tracking_lost = False
        self._search_worker = None
        self._search_epoch = 0
        self._next_search = 0.0
        self._search_backoff = 2.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(14)
        self._beta_notice = hint_label("베타 · Discord 로그인 사용자")
        layout.addWidget(self._beta_notice)
        row = QHBoxLayout()
        self.auto_find_btn = QPushButton("자동 찾기")
        self.auto_find_btn.clicked.connect(self._on_auto_find)
        self.region_btn = QPushButton("직접 지정")
        self.region_btn.clicked.connect(self._on_region)
        self.view_region_btn = QPushButton("영역 보기")
        self.view_region_btn.clicked.connect(self._flash_region)
        for button in (self.auto_find_btn,self.region_btn,self.view_region_btn):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.region_label = QLabel()
        self.region_label.setWordWrap(True)
        layout.addWidget(self.region_label)
        row = QHBoxLayout()
        self.enable = checkbox("도르카 오버레이 사용")
        self.enable.setChecked(self._cfg["enabled"])
        self.enable.toggled.connect(self._on_enabled)
        row.addWidget(self.enable)
        row.addStretch()
        row.addWidget(QLabel("전체 배율"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50,300)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(self._cfg["scale"])
        self.scale_spin.valueChanged.connect(self._on_scale)
        row.addWidget(self.scale_spin)
        self.lock_chk = checkbox("위치 고정")
        self.lock_chk.setChecked(self._cfg["locked"])
        self.lock_chk.toggled.connect(self._on_locked)
        row.addWidget(self.lock_chk)
        layout.addLayout(row)
        layout.addWidget(QLabel("표시 미리보기"))
        self.preview = DorchaOverlay(self._cfg["scale"]/100, parent=self)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidget(self.preview)
        self.preview_scroll.setFixedHeight(self.preview.height()+24)
        self.preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.preview_scroll)
        self.value_label = QLabel("현재 판독  --/15")
        layout.addWidget(self.value_label)
        layout.addStretch()
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        self._apply_gate()
        self._timer.start()

    def _logged_in(self):
        return bool(config.load_discord_user())

    def _active(self):
        return self._watcher.is_game_active() or (self._watcher.is_self_active() and self._view.isVisible())

    def bind_tuarim(self, source, control):
        self._tuarim_source = source
        self._percent_control = control
        source._display_requested = self.percent_requested
        source.observed.connect(self._set_percent)
        control.toggled.connect(self._on_percent_enabled)
        self._update_elements()

    def percent_requested(self):
        return (self._cfg["showTuarim"] and self._tuarim_source is not None
                and not self._render_suspended() and not self._paused and self._logged_in() and self._active())

    def _render_suspended(self):
        for controller in (self,self._tuarim_source):
            if controller is not None and (controller._shutting_down or controller._autofind_busy
                    or (controller._selector is not None and controller._selector.isVisible())):
                return True
        return False

    def _on_percent_enabled(self, checked):
        self._cfg["showTuarim"] = checked
        self._set_percent(None)
        self._update_value_label()
        self._update_elements()
        self._sync_overlay()
        self._save()

    def _set_percent(self, value):
        if not self._cfg["showTuarim"] and self._percent is None:
            return
        self._percent = value if self.percent_requested() and type(value) is int and 0 <= value < 100 else None
        self.preview.set_percent(self._percent)
        self._update_value_label()
        if self._overlay is not None:
            self._overlay.set_percent(self._percent)
        self._sync_overlay()

    def _update_elements(self):
        for overlay in (self.preview,self._overlay):
            if overlay is not None:
                overlay.set_elements(self._cfg["enabled"],self._cfg["showTuarim"])

    def _sync_overlay(self):
        visible = (not self._render_suspended() and not self._paused and self._logged_in() and self._active()
                   and ((self._cfg["enabled"] and self._region is not None) or self.percent_requested()))
        if visible:
            self._ensure_overlay()
            self._update_elements()
            if not self._overlay.isVisible():
                self._overlay.show()
        elif self._overlay is not None:
            self._overlay.hide()

    def _apply_gate(self):
        logged = self._logged_in()
        for control in (self.enable,self.scale_spin,self.lock_chk,self.region_btn,self.auto_find_btn):
            control.setEnabled(logged and not self._shutting_down and not self._autofind_busy)
        if self._percent_control is not None:
            self._percent_control.setEnabled(logged and not self._shutting_down)
        self.view_region_btn.setEnabled(logged and self._region is not None and not self._shutting_down)
        self.region_label.setText("영역 미등록" if self._region is None else
                                 "등록 영역  {x}, {y}  /  {w} × {h}".format(**self._region))

    def _set_value(self, value):
        self.preview.set_value(value)
        self._update_value_label()
        if self._overlay is not None:
            self._overlay.set_value(value)

    def _update_value_label(self):
        value = self.preview.value
        dorcha = f"{value}/15" if value is not None else "--/15"
        percent = f"{self._percent}%" if self._percent is not None else "--%"
        if self._cfg["showTuarim"]:
            text = f"도르카 {dorcha} · 투아림 {percent}" if self._cfg["enabled"] else f"투아림 {percent}"
        else:
            text = dorcha
        self.value_label.setText("현재 판독  " + text)

    def _hide(self):
        self._invalidate_search()
        self._set_value(None)
        self._percent = None
        self.preview.set_percent(None)
        self._update_value_label()
        if self._overlay is not None:
            self._overlay.set_percent(None)
            self._overlay.hide()

    def _ensure_overlay(self):
        if self._overlay is not None:
            return
        overlay = DorchaOverlay(self._cfg["scale"]/100)
        overlay.set_locked(self._cfg["locked"])
        position = self._cfg["pos"]
        screen = QGuiApplication.primaryScreen()
        if position is not None:
            overlay.move(position["x"],position["y"])
        elif screen is not None:
            rect = screen.availableGeometry()
            overlay.move(rect.center().x()-overlay.width()-40, rect.center().y()-overlay.height()//2)
        overlay.moved.connect(self._save)
        overlay.set_value(self.preview.value)
        overlay.set_percent(self._percent)
        self._overlay = overlay
        self._update_elements()

    def _tick(self):
        if self._shutting_down or self._autofind_busy:
            return
        if self._selector is not None and self._selector.isVisible():
            self._hide()
            return
        self._apply_gate()
        if self._paused or not self._logged_in() or not self._active():
            self._hide()
            return
        if not self._cfg["enabled"] or not self._region:
            self._invalidate_search()
            self._set_value(None)
            self._sync_overlay()
            return
        from .dpi import to_physical
        self._ensure_overlay()
        box = self._live_box or to_physical(self._region)
        target = None if self._tracking_lost else self._search_target()
        if not self._tracking_lost and (
                (self._live_target is not None and target != self._live_target)
                or (target is not None and not self._inside_target(box,target))):
            self._invalidate_search()
            self._tracking_lost = True
        value = None
        if not self._tracking_lost:
            frame = self._grab_rect(*box)
            if target is not None and self._search_target() != target:
                self._invalidate_search()
                self._tracking_lost = True
            else:
                value = read_dorcha(frame)
                if value is not None and target is not None:
                    self._live_box, self._live_target = box, target
        self._set_value(value)
        if value is None:
            self._start_search()
        else:
            self._search_epoch += 1
            if self._search_worker is not None:
                self._search_worker.requestInterruption()
            self._next_search = 0.0
            self._search_backoff = 2.0
        self._sync_overlay()

    def _invalidate_search(self):
        self._search_epoch += 1
        self._tracking_lost = self._tracking_lost or self._live_target is not None
        self._live_box = None
        self._live_target = None
        self._next_search = 0.0
        self._search_backoff = 2.0
        if self._search_worker is not None:
            self._search_worker.requestInterruption()

    def _search_target(self):
        from ..system.window_capture import registered_game_target
        return registered_game_target(self._live_target)

    @staticmethod
    def _inside_target(box,target):
        x,y,w,h = box
        _,_,left,top,width,height = target
        return w > 0 and h > 0 and left <= x and top <= y and x+w <= left+width and y+h <= top+height

    def _start_search(self):
        if (self._search_worker is not None or monotonic() < self._next_search
                or not self._watcher.is_game_active()):
            return
        self._next_search = monotonic() + self._search_backoff
        self._search_backoff = min(10.0, self._search_backoff * 2)
        target = self._search_target()
        if target is None:
            return
        _, _, x, y, w, h = target
        # A single full-frame job is allowed; no queue or unbounded image allocation.
        if w*h > 16_777_216:
            return
        frame = self._grab_rect(x,y,w,h)
        if frame is None or frame.shape[:2] != (h,w):
            return
        from .dorcha_search import DorchaSearch
        worker = DorchaSearch(np.array(frame, copy=True, order="C"), target, self._search_epoch)
        self._search_worker = worker
        worker.finished.connect(self._finish_search)
        worker.start()

    def _finish_search(self):
        worker = self._search_worker
        if worker is None:
            return
        worker.wait()
        self._search_worker = None
        try:
            if (worker.epoch != self._search_epoch or worker.isInterruptionRequested()
                    or self._shutting_down or self._autofind_busy or self._paused
                    or not self._cfg["enabled"] or not self._logged_in() or not self._region
                    or not self._watcher.is_game_active() or self._search_target() != worker.target):
                return
            self._next_search = max(self._next_search, monotonic() + worker.elapsed*20)
            if worker.error:
                _log.warning("도르카 재탐색 실패: %s", worker.error)
            if worker.box is None:
                return
            _, _, ox, oy, _, _ = worker.target
            x,y,w,h = worker.box
            box = (x+ox,y+oy,w,h)
            if not self._inside_target(box,worker.target):
                return
            # Re-read current pixels: the worker's old screenshot is never displayed.
            value = read_dorcha(self._grab_rect(*box))
            if value is None or self._search_target() != worker.target:
                return
            self._live_box = box
            self._live_target = worker.target
            self._tracking_lost = False
            self._set_value(value)
            self._next_search = 0.0
            self._search_backoff = 2.0
        finally:
            worker.deleteLater()

    def _grab_rect(self,x,y,w,h):
        try:
            if self._sct is None:
                import mss
                self._sct = mss.mss()
            shot = self._sct.grab(dict(left=x,top=y,width=w,height=h))
            frame = np.frombuffer(shot.bgra,np.uint8).reshape(shot.height,shot.width,4)[:,:,:3]
            self._capture_failed = False
            return frame
        except Exception:
            if not self._capture_failed:
                _log.warning("도르카 캡처 실패", exc_info=True)
            self._capture_failed = True
            return None

    def _save(self):
        if self._shutting_down:
            return
        if self._overlay is not None:
            self._cfg["pos"] = {"x":self._overlay.x(),"y":self._overlay.y()}
        try:
            config.save_dorcha(self._cfg)
            self._save_failed = False
        except OSError:
            if not self._save_failed:
                self._save_failed = True
                QMessageBox.warning(self,"설정 저장 실패","현재 설정을 저장하지 못했습니다. 재실행하면 이전 설정으로 돌아갈 수 있습니다.")

    def _on_enabled(self, checked):
        self._cfg["enabled"] = checked
        self._invalidate_search()
        self._set_value(None)
        self._update_elements()
        self._sync_overlay()
        self._save()

    def _on_scale(self, value):
        self._cfg["scale"] = value
        self.preview.set_scale(value/100)
        self.preview_scroll.setFixedHeight(self.preview.height()+24)
        if self._overlay is not None:
            self._overlay.set_scale(value/100)
        self._save()

    def _on_locked(self, checked):
        self._cfg["locked"] = checked
        if self._overlay is not None:
            self._overlay.set_locked(checked)
        self._save()

    def _apply_region(self,x,y,w,h):
        if self._shutting_down:
            return
        region = dict(x=x,y=y,w=w,h=h)
        config.save_dorcha({"box":region})
        self._cfg["box"] = self._region = region
        self._invalidate_search()
        self._set_value(None)
        self._sync_overlay()
        self._tracking_lost = False
        self._apply_gate()

    def _on_region(self):
        if not self._logged_in() or self._shutting_down or self._autofind_busy:
            return
        from .region_selector import RegionSelector
        size = (self._region["w"],self._region["h"]) if self._region else (28,23)
        if self._selector is not None:
            self._selector.close()
            self._selector.deleteLater()
        self._selector_timer_was_running = self._timer.isActive()
        self._timer.stop()
        self._hide()
        self._selector = RegionSelector(fixed_size=size)
        self._selector.selected.connect(self._on_selected)
        self._selector.cancelled.connect(self._resume_after_selector)
        self._selector.start()

    def _resume_after_selector(self):
        if self._selector_timer_was_running and not self._shutting_down:
            self._timer.start()
        self._selector_timer_was_running = False

    def _on_selected(self,x,y,w,h):
        try:
            self._apply_region(x,y,w,h)
        except OSError:
            QMessageBox.warning(self,"영역 저장 실패","기존 등록 영역을 유지합니다.")
            return
        finally:
            self._resume_after_selector()
        if not self._shutting_down:
            self._flash_region()

    def _on_auto_find(self):
        from .autofind_confirm import confirm_autofind
        self._hide()
        confirm_autofind(self,"dorcha","원 안의 도르카 숫자 (0~15)",self._apply_region)

    def _flash_region(self):
        if self._region is None or self._shutting_down:
            return
        from .region_highlight import RegionHighlight
        if self._highlight is not None:
            self._highlight.close()
            self._highlight.deleteLater()
        self._highlight = RegionHighlight()
        from .dpi import to_logical
        box = (to_logical(*self._live_box) if self._live_box is not None else
               tuple(self._region[key] for key in ("x","y","w","h")))
        self._highlight.flash(*box,
                              "도르카 영역 확인","원 안의 숫자 0~15가 모두 들어가야 합니다.")

    def set_paused(self, paused):
        self._paused = paused
        if paused:
            self._hide()

    def shutdown(self):
        self._shutting_down = True
        self._timer.stop()
        self._hide()
        if self._search_worker is not None:
            worker = self._search_worker
            worker.requestInterruption()
            worker.wait()
            self._search_worker = None
            worker.deleteLater()
        for widget in (self._overlay,self._selector,self._highlight,self._autofind_highlight):
            if widget is not None:
                widget.close()
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                _log.warning("도르카 캡처 정리 실패",exc_info=True)
            self._sct = None
