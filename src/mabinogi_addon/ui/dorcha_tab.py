"""Independent opt-in beta display; no Tuarim alerts or saved values."""

from .. import perf_meter
import logging
import threading
from time import monotonic, perf_counter as monotonic_perf
import weakref

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget

from .settings_layout import set_lock_text
from .. import config
from ..detect.dorcha_reader import read_dorcha
from .dorcha_overlay import DorchaOverlay
from .widgets import checkbox, hint_label, switch

_log = logging.getLogger(__name__)



def _note_dorcha(trace, value):
    """버그 문의 진단에 최근 판독 결과(값 또는 거절 이유)를 남기고, 바뀔 때만 app.log에 한 줄."""
    global _last_dorcha_state
    from .. import diagnostics
    text = diagnostics.describe_dorcha(trace, value)
    state = "읽음" if value is not None else trace.get("rejection")
    if state != _last_dorcha_state:  # 읽힘 ↔ 거절 이유가 바뀔 때만(값이 바뀔 때마다 남기지 않음)
        _last_dorcha_state = state
        _log.info("도르카 판독: %s", text)
    diagnostics.note("도르카 최근 판독", text)


_last_dorcha_state = None

class DorchaTab(QWidget):
    from .. import autofind_regions as _afr
    _region = _afr.region_property("dorcha")  # 자동 찾기 v2: 읽기 = 쓸 영역, 쓰기 = 저장 영역(_cfg["box"]도 저장 영역)
    _job_ready = Signal(object)  # 작업 스레드 → 화면 스레드 결과 전달(대기열 연결)

    def __init__(self, watcher):
        super().__init__()
        self._watcher = watcher
        self._alpha_ready = False
        try:
            config.migrate_tuarim_alpha()
            self._alpha_ready = True
        except OSError:
            _log.warning("투아림 표시 설정 전환 저장 실패; 표시를 보류합니다.")
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
        self._capture_restore = {}
        self._capture_failed = False
        self._save_failed = False
        self._overlay = None
        self._view = self
        self._tuarim_source = None
        self._percent_control = None
        self._percent = None
        self._live_box = None
        self._live_target = None
        self._approved_target = None
        self._tracking_lost = False
        self._search_worker = None
        self._search_epoch = 0
        self._next_search = 0.0
        self._next_region_probe = 0.0
        self._search_backoff = 2.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(14)
        self._beta_notice = hint_label("")
        self._beta_notice.hide()
        row = QHBoxLayout()
        self.auto_find_btn = QPushButton("자동 찾기")
        self.auto_find_btn.clicked.connect(self._on_auto_find)
        self.region_btn = QPushButton("직접 지정")
        self.region_btn.clicked.connect(self._on_region)
        self.view_region_btn = QPushButton("지정 영역 보기")
        self.view_region_btn.clicked.connect(self._flash_region)
        from .region_registration import clear_button
        self.clear_region_btn = clear_button(self, "dorcha", self._region_cleared)
        for button in (self.auto_find_btn,self.region_btn,self.view_region_btn,self.clear_region_btn):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.region_label = QLabel()
        self.region_label.setWordWrap(True)
        layout.addWidget(self.region_label)
        row = QHBoxLayout()
        self.enable = switch("도르카 오버레이 사용")  # 기능 켜기 = 스위치(명세 14.5)
        self.enable.setChecked(self._cfg["enabled"])
        self.enable.toggled.connect(self._on_enabled)
        row.addWidget(self.enable)
        row.addStretch()
        row.addWidget(QLabel("표시 배율"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50,300)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(self._cfg["scale"])
        self.scale_spin.valueChanged.connect(self._on_scale)
        row.addWidget(self.scale_spin)
        from .settings_layout import lock_button
        self.lock_chk = lock_button(self._cfg["locked"])
        self.lock_chk.toggled.connect(self._on_locked)
        row.addWidget(self.lock_chk)
        layout.addLayout(row)
        layout.addWidget(QLabel("표시 미리보기"))
        self.preview = DorchaOverlay(self._cfg["scale"]/100, parent=self)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.preview_scroll.setWidget(self.preview)
        self.preview_scroll.setFixedHeight(self.preview.height()+24)
        self.preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.preview_scroll)
        self.value_label = QLabel("현재 판독: --/15")
        layout.addWidget(self.value_label)
        self.source_preview = QLabel()
        self.source_preview.setFixedSize(80, 40)
        self.source_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_preview.setStyleSheet("background:palette(base); border:1px solid palette(mid);")
        layout.addWidget(self.source_preview)
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

    def login_refresh(self):
        """로그인 변경(login_changed): 표시 조건을 다시 적용한다(투아림 %는 2026-10-28부터 모든 사용자)."""
        self._apply_gate()

    def percent_requested(self):
        return (self._cfg["showTuarim"] and self._tuarim_source is not None
                and self._alpha_ready
                and not self._render_suspended() and not self._paused and self._active())

    def _render_suspended(self):
        for controller in (self,self._tuarim_source):
            if controller is not None and (controller._shutting_down or controller._autofind_busy
                    or (controller._selector is not None and controller._selector.isVisible())):
                return True
        return False

    def _on_percent_enabled(self, checked):
        if not (self._alpha_ready):
            from PySide6.QtCore import QSignalBlocker
            with QSignalBlocker(self._percent_control):
                self._percent_control.setChecked(self._cfg["showTuarim"])
            return
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
                overlay.set_elements(self._cfg["enabled"],self._cfg["showTuarim"] and self._alpha_ready)

    def _sync_overlay(self):
        visible = (not self._render_suspended() and not self._paused and self._active()
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
        self.clear_region_btn.setEnabled(self._region is not None and not self._shutting_down)
        for control in (self.enable,self.scale_spin,self.lock_chk,self.region_btn):
            control.setEnabled(not self._shutting_down and not self._autofind_busy)
        self.auto_find_btn.setEnabled(not self._shutting_down and not self._autofind_busy)
        if self._percent_control is not None:
            self._percent_control.setVisible(self._alpha_ready)
            self._percent_control.setEnabled(self._alpha_ready and not self._shutting_down)
        if not (self._alpha_ready):
            self._percent = None
            self.preview.set_percent(None)
            if self._overlay is not None:
                self._overlay.set_percent(None)
        self._update_elements()
        self.view_region_btn.setEnabled(self._region is not None and not self._shutting_down)
        self._update_value_label()
        self._sync_overlay()
        self.region_label.setText("영역 미지정" if self._region is None else
                                 "등록 영역  {x}, {y}  /  {w} × {h}".format(**self._region))
        if (reference:=getattr(self,"_resource_view",None)) is not None and (view:=reference()) is not None:
            view.refresh_registration()

    def _set_value(self, value):
        if value is None:
            self.source_preview.clear()
        self.preview.set_value(value)
        self._update_value_label()
        if self._overlay is not None:
            self._overlay.set_value(value)

    def _update_value_label(self):
        value = self.preview.value
        dorcha = f"{value}/15" if value is not None else "--/15"
        percent = f"{self._percent}%" if self._percent is not None else "--%"
        if self._cfg["showTuarim"] and self._alpha_ready:
            text = f"도르카 {dorcha} · 투아림 {percent}" if self._cfg["enabled"] else f"투아림 {percent}"
        else:
            text = dorcha
        self.value_label.setText("현재 판독: " + text)

    def _show_source(self, frame):
        if frame is None or frame.size == 0:
            self.source_preview.clear()
            return
        rgb = np.ascontiguousarray(frame[:, :, :3][:, :, ::-1])
        h, w = rgb.shape[:2]
        image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self.source_preview.setPixmap(QPixmap.fromImage(image).scaled(
            self.source_preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation))

    def _hide(self):
        self._restore_capture_windows()
        self._invalidate_search()
        self._set_value(None)
        self._percent = None
        self.preview.set_percent(None)
        self._update_value_label()
        if self._overlay is not None:
            self._overlay.set_percent(None)
            self._overlay.hide()

    def reset_for_new_game(self):
        """게임 종료·재시작(프로세스 기준): 지난 도르카·투아림 값을 지우고 오버레이를 숨긴다(영역은 유지, 새 게임에서 다시 읽음)."""
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

    # ---- 판독 틱(0.38.0: 대상 확인·캡처·판독은 작업 스레드, 화면 스레드는 결과 반영만) ----------------
    # 사용자 실측(0.37.1): 도르카 켬이면 커서·오버레이가 1초에 2~3번 0.1~0.24초 멈춤 — 이 틱이 화면 스레드에서
    # 설정 파일 읽기·프로세스 조회·mss 캡처·판독·(실패 때) 게임 창 전체 캡처를 했다. 이제 그 일은 작업 스레드에서 한다.
    INLINE_JOBS = False  # 테스트: 같은 계산을 바로(동기로) 돌린다 — 판정 로직 회귀를 그대로 확인
    SLOW_TICK_MS = 30.0  # 틱 하나가 이보다 오래 걸리면 단계별 소요를 app.log에(분당 1번)

    @perf_meter.timed("도르카")  # 앱 CPU 절감 1단계: 기능별 처리 시간(측정만)
    def _tick(self):
        self._restore_capture_windows()
        if self._shutting_down or self._autofind_busy:
            return
        if self._selector is not None and self._selector.isVisible():
            self._hide()
            return
        self._apply_gate()
        if self._paused or not self._active():
            self._hide()
            return
        if not self._cfg["enabled"] or not self._region:
            self._invalidate_search()
            self._set_value(None)
            self._sync_overlay()
            return
        from .dpi import to_physical
        self._ensure_overlay()
        if getattr(self, "_tick_job", None) is not None:
            self._sync_overlay()  # 지난 틱 계산이 아직 도는 중 — 쌓지 않고 이번 틱은 건너뛴다
            return
        snap = dict(region=to_physical(self._region), live_box=self._live_box, live_target=self._live_target,
                    approved=self._approved_target, lost=self._tracking_lost, epoch=self._search_epoch,
                    probe_due=(self._tracking_lost and self._search_worker is None
                               and self._watcher.is_game_active() and monotonic() >= self._next_region_probe),
                    search_due=(self._search_worker is None and monotonic() >= self._next_search
                                and self._watcher.is_game_active()),
                    now=monotonic())
        box = self._live_box or snap["region"]
        guarded = self._own_window_over((box[0]-box[2], box[1]-2*box[3], box[2]*3, box[3]*4))
        # 우리 창(메인 창 등)이 도르카 자리를 덮고 있으면 캡처 순간 제외가 필요하다 — 창 조작은 화면 스레드 전용이라
        # 이때만 예전처럼 화면 스레드에서 바로 돈다(오버레이는 0.37.1부터 상시 제외라 해당 없음).
        snap["grab"] = self._grab_tracking_rect if guarded else self._grab_rect
        self._run_job(lambda: self._compute_tick(snap), lambda result: self._apply_tick(snap, result), inline=guarded)

    def _own_window_over(self, area):
        """캡처에서 상시 제외되지 않은 우리 창이 area(물리 픽셀)와 겹치나 — 보스와 공용(capture_guard.own_window_over)."""
        from .capture_guard import own_window_over
        return own_window_over(area)

    def _run_job(self, work, done, slot="_tick_job", inline=False):
        """work()는 작업 스레드(테스트는 바로), done(결과)는 화면 스레드에서. slot마다 하나씩만 돈다."""
        if self.INLINE_JOBS or inline:
            done(work())
            return
        if getattr(self, slot, None) is not None or self._shutting_down:
            return
        executor = self._job_executor()
        token = object()
        setattr(self, slot, token)

        def deliver(result):
            if getattr(self, slot, None) is token:
                setattr(self, slot, None)
            if not self._shutting_down:
                done(result)

        def run():
            try:
                result = work()
            except Exception:  # noqa: BLE001 — 계산 함수가 스스로 잡지만 마지막 방어
                _log.warning("도르카 작업 실패", exc_info=True)
                result = None
            self._job_ready.emit(lambda: deliver(result))
        executor.submit(run)

    def _job_executor(self):
        """0.38.0 QA: 작업마다 새 스레드(+스레드마다 새 mss, 미반납 → GDI 누수) 대신 오래 사는 작업 스레드 1개.
        판독 틱·다시 읽기를 순서대로 처리하고 그 스레드의 mss 하나를 재사용, 종료 때 그 스레드에서 닫는다."""
        executor = self.__dict__.get("_executor")
        if executor is None:
            from concurrent.futures import ThreadPoolExecutor
            executor = self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dorcha-job")
            self._job_ready.connect(self._deliver_job)
        return executor

    def _deliver_job(self, deliver):
        deliver()  # 화면 스레드

    @perf_meter.timed("도르카")  # 앱 CPU 절감 1단계: 기능별 처리 시간(측정만)
    def _compute_tick(self, snap):
        """작업 스레드: 대상 창 확인 → (필요하면) 등록 영역 확인 → 캡처 → 판독. 위젯·Qt 객체는 건드리지 않는다.
        상태는 바꾸지 않고 결과(events·값·프레임·판독 기록)만 돌려준다 — 화면 스레드가 순서대로 반영."""
        steps = {}
        out = dict(events=[], notes=[], value=None, frame=None, live=None, target=None, steps=steps, error=None)

        def timed(name, fn, *args):
            started = monotonic_perf()
            try:
                return fn(*args)
            finally:
                steps[name] = steps.get(name, 0.0) + (monotonic_perf() - started) * 1000

        try:
            box = snap["live_box"] or snap["region"]
            lost = snap["lost"]
            target = timed("대상 확인", self._search_target) if not lost or snap["probe_due"] else None
            recovered = None
            if snap["probe_due"]:
                out["events"].append(("probe", snap["now"] + 2.0))
                registered = snap["region"]
                # Recovery must remain a small ROI check, not a second full search.
                if (target is not None and registered[2]*registered[3] <= 16_384
                        and self._inside_target(registered, target)):
                    recovered = timed("영역 확인", self._verify_region_job, registered, target, out["notes"], snap["grab"])
                    if recovered is not None:
                        box = recovered
                        lost = False
            if not lost and ((snap["live_target"] is not None and target != snap["live_target"])
                             or (target is not None and not self._inside_target(box, target))):
                out["events"].append(("invalidate",))
                lost = True
            if (recovered is None and not lost and target is not None and snap["live_target"] is None
                    and snap["approved"] != target):
                verified = timed("영역 확인", self._verify_region_job, box, target, out["notes"], snap["grab"])
                if verified is None:
                    lost = True
                    out["events"].append(("probe", snap["now"] + 2.0))
                else:
                    box = verified
            if not lost:
                frame = timed("캡처", snap["grab"], *box)
                out["frame"] = frame
                if target is not None and timed("대상 확인", self._search_target) != target:
                    out["events"].append(("invalidate",))
                    lost = True
                else:
                    trace = {}
                    value = timed("판독", read_dorcha, frame, trace)
                    out["notes"].append((trace, value))
                    out["value"] = value
                    if value is not None and target is not None:
                        out["live"] = (box, target)
            out["lost"] = lost
            # 못 읽었으면 화면 스레드가 전체 탐색을 시작할 수 있다 — 탐색 대상은 지금 다시 확인(작업 스레드에서)
            # (탐색 대기 중이면 조회하지 않는다 — 추적을 잃은 틱마다 대상 조회 금지)
            if out["value"] is None and snap["search_due"]:
                out["target"] = timed("대상 확인", self._search_target)
            else:
                out["target"] = target
        except Exception as exc:  # noqa: BLE001 — 작업 스레드 예외는 화면 스레드에서 한 번 기록
            out["error"] = exc
            out["lost"] = snap["lost"]
        return out

    def _apply_tick(self, snap, out):
        """화면 스레드: 계산 결과를 원래 틱과 같은 순서로 반영한다."""
        if out.get("error") is not None:
            _log.warning("도르카 판독 틱 실패: %r", out["error"])
            return
        if (self._shutting_down or self._autofind_busy or self._paused or not self._cfg["enabled"]
                or not self._region or not self._active()):
            return  # 계산하는 사이 멈춤·끔·숨김 — 결과를 쓰지 않는다(다음 틱이 화면을 정리)
        if snap["epoch"] != self._search_epoch:
            return  # 계산하는 사이 숨김·영역 변경·대상 변경 등으로 무효화 — 낡은 결과는 쓰지 않는다
        for trace, value in out["notes"]:
            _note_dorcha(trace, value)
        for event in out["events"]:
            if event[0] == "invalidate":
                self._invalidate_search()
            else:
                self._next_region_probe = event[1]
        self._tracking_lost = out["lost"]
        if out["live"] is not None:
            self._live_box, self._live_target = out["live"]
        self._last_target = out["target"]
        value, frame = out["value"], out["frame"]
        self._set_value(value)
        self._show_source(frame)
        if value is None:
            self._start_search()
        else:
            self._search_epoch += 1
            if self._search_worker is not None:
                self._search_worker.requestInterruption()
            self._next_search = 0.0
            self._search_backoff = 2.0
        self._sync_overlay()
        self._log_slow("판독 틱", out["steps"])

    def _log_slow(self, kind, steps):
        total = sum(steps.values())
        if total < self.SLOW_TICK_MS:
            return
        now = monotonic()
        if now < getattr(self, "_slow_logged_until", 0.0):
            return
        self._slow_logged_until = now + 60.0
        detail = " · ".join(f"{name} {ms:.0f}ms" for name, ms in steps.items())
        _log.info("도르카 %s 느림(작업 스레드) %.0fms: %s", kind, total, detail)

    def _verify_region_job(self, box, target, notes, grab=None):
        """작업 스레드: 저장된 사각형 주변을 캡처해 도르카 장식이 정말 그 안에 있는지 확인."""
        x,y,w,h = box
        _,_,tx,ty,tw,th = target
        pad_x,pad_y = max(8,w//2),max(17,h)
        left,top = max(tx,x-pad_x),max(ty,y-pad_y)
        right,bottom = min(tx+tw,x+w+pad_x),min(ty+th,y+h+pad_y)
        frame = (grab or self._grab_rect)(left,top,right-left,bottom-top)
        if frame is None or frame.shape[:2] != (bottom-top,right-left) or self._search_target() != target:
            return None
        from ..detect.dorcha_anchor import locate_dorcha
        trace = {}
        try:
            found = locate_dorcha(frame, diagnostics=trace)
        except Exception:
            _log.warning("도르카 초기 영역 검증 실패",exc_info=True)
            return None
        if found is None:
            notes.append((trace, None))
            return None
        fx,fy,fw,fh = found
        current = (left+fx,top+fy,fw,fh)
        if (not self._inside_target(current,target)
                or not (x <= current[0]+fw/2 < x+w and y <= current[1]+fh/2 < y+h)):
            return None
        return current

    def _verify_registered_region(self, box, target):
        """(호환) 화면 스레드에서 바로 확인 — 수동 작업용. 틱은 _verify_region_job을 작업 스레드에서 쓴다."""
        notes = []
        result = self._verify_region_job(box, target, notes, self._grab_tracking_rect)
        for trace, value in notes:
            _note_dorcha(trace, value)
        return result

    def _invalidate_search(self):
        self._search_epoch += 1
        self._tracking_lost = self._tracking_lost or self._live_target is not None
        self._live_box = None
        self._live_target = None
        self._approved_target = None
        self._next_region_probe = 0.0
        self._next_search = 0.0
        self._search_backoff = 2.0
        if self._search_worker is not None:
            self._search_worker.requestInterruption()

    def _search_target(self):
        from ..system.window_capture import registered_game_target
        # 추적 중이 아니어도 지난번 확인한 창을 먼저 확인(매번 전체 창 나열 대신 — 창이 바뀌었으면 다시 찾는다)
        return registered_game_target(self._live_target or getattr(self, "_last_target", None))

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
        target = getattr(self, "_last_target", None)  # 방금 틱(작업 스레드)이 확인한 대상 — 화면 스레드 조회 없음
        if target is None:
            return
        _, _, x, y, w, h = target
        # A single full-frame job is allowed; no queue or unbounded image allocation.
        if w*h > 16_777_216:
            return
        from .dorcha_search import DorchaSearch
        # 0.38.0: 게임 창 전체 캡처·복사도 탐색 스레드에서(예전엔 화면 스레드 BitBlt — 끊김 0.15~0.24초의 주범 후보)
        if self._own_window_over((x, y, w, h)):
            # 우리 창이 게임 창 위에 있음 — 캡처 순간 제외가 필요해 전체 캡처만 화면 스레드에서(예전 방식).
            # 다시 읽기는 _finish_search가 같은 판단으로 한다.
            frame = self._grab_tracking_rect(x, y, w, h)
            if frame is None:
                return
            worker = DorchaSearch(np.array(frame, copy=True), target, self._search_epoch)
        else:
            worker = DorchaSearch(None, target, self._search_epoch, grab=self._grab_rect,
                                  read=read_dorcha, target_fn=self._search_target,
                                  release=self._close_thread_mss)  # 탐색 하나 = mss 하나, 끝나면 그 스레드에서 닫음
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
                    or not self._cfg["enabled"] or not self._region
                    or not self._watcher.is_game_active()):
                return
            self._next_search = max(self._next_search, monotonic() + worker.elapsed*20)
            if worker.error:
                _log.warning("도르카 재탐색 실패: %s", worker.error)
            self._log_slow("전체 탐색", getattr(worker, "steps", {}))
            if worker.box is None:
                return
            _, _, ox, oy, _, _ = worker.target
            x,y,w,h = worker.box
            box = (x+ox,y+oy,w,h)
            if not self._inside_target(box,worker.target):
                return
            if getattr(worker, "read_done", False):
                self._apply_search_read(worker.target, box, worker.value, worker.read_frame, worker.current_target)
            else:
                # (탐색이 다시 읽기를 하지 않은 경우) 다시 읽기만 작업으로 — 화면 스레드에서 캡처하지 않는다
                target = worker.target
                guarded = self._own_window_over(box)
                grab = self._grab_tracking_rect if guarded else self._grab_rect

                def reread():
                    try:
                        frame = grab(*box)
                        return frame, read_dorcha(frame), self._search_target()
                    except Exception:  # noqa: BLE001
                        _log.warning("도르카 다시 읽기 실패", exc_info=True)
                        return None, None, None
                self._run_job(reread, lambda r: self._apply_search_read(target, box, r[1], r[0], r[2]),
                              slot="_reread_job", inline=guarded)
        finally:
            worker.deleteLater()

    def _apply_search_read(self, target, box, value, frame, current_target):
        """탐색 결과로 찾은 자리를 다시 읽은 값 반영(탐색 때의 옛 화면은 쓰지 않는다)."""
        if (self._shutting_down or self._paused or not self._cfg["enabled"] or not self._region
                or value is None or current_target != target):
            return
        self._search_epoch += 1  # 이 사이 계산 중이던 판독 틱(옛 자리 기준) 결과는 버린다
        self._live_box = box
        self._live_target = target
        self._last_target = target
        self._tracking_lost = False
        self._set_value(value)
        self._show_source(frame)
        self._next_search = 0.0
        self._search_backoff = 2.0

    def _grab_tracking_rect(self, x, y, w, h):
        from ..system import capture_exclusion

        self._restore_capture_windows()
        if not capture_exclusion.available():
            return self._grab_rect(x,y,w,h)
        from PySide6.QtWidgets import QApplication

        widgets = {int(widget.winId()): weakref.ref(widget)
                   for widget in QApplication.topLevelWidgets() if widget.isVisible()}
        pending = []
        try:
            with capture_exclusion.excluding_windows(widgets, (x,y,w,h)) as pending:
                return self._grab_rect(x,y,w,h)
        finally:
            for hwnd, previous in pending:
                self._capture_restore.setdefault(hwnd, (widgets[hwnd], previous))

    def _restore_capture_windows(self):
        if not self._capture_restore:
            return
        from shiboken6 import isValid
        from ..system.capture_exclusion import restore_window

        for hwnd, (reference, previous) in list(self._capture_restore.items()):
            widget = reference()
            # Do not restore an affinity onto a recycled HWND, even in this process.
            if (widget is None or not isValid(widget)
                    or not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created)
                    or int(widget.winId()) != hwnd or restore_window(hwnd, previous)):
                del self._capture_restore[hwnd]

    def _grab_rect(self,x,y,w,h):
        """작업 스레드에서도 부른다 — mss 캡처 객체는 스레드마다 따로 둔다(스레드 사이 공유 불가)."""
        try:
            local = self.__dict__.setdefault("_sct_local", threading.local())
            sct = getattr(local, "sct", None)
            if sct is None:
                import mss
                sct = local.sct = mss.mss()
                if threading.current_thread() is threading.main_thread():
                    self._sct = sct  # 종료 때 닫기(작업 스레드 것은 그 스레드에서 _close_thread_mss)
            shot = sct.grab(dict(left=x,top=y,width=w,height=h))
            frame = np.frombuffer(shot.bgra,np.uint8).reshape(shot.height,shot.width,4)[:,:,:3]
            self._capture_failed = False
            return frame
        except Exception:
            if not self._capture_failed:
                _log.warning("도르카 캡처 실패", exc_info=True)
            self._capture_failed = True
            return None

    def _close_thread_mss(self):
        """지금 스레드의 mss를 닫는다(GDI DC·DIB 반납 — mss는 close()에서만 반납, __del__ 없음)."""
        local = self.__dict__.get("_sct_local")
        sct = getattr(local, "sct", None) if local is not None else None
        if sct is None:
            return
        local.sct = None
        if sct is self._sct:
            self._sct = None
        try:
            sct.close()
        except Exception:  # noqa: BLE001
            _log.warning("도르카 캡처 정리 실패", exc_info=True)

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
                QMessageBox.warning(self,"설정 저장 실패","현재 설정을 저장하지 못했어요. 재실행하면 이전 설정으로 돌아갈 수 있어요.")

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
        self._resize_preview()
        if self._overlay is not None:
            self._overlay.set_scale(value/100)
        self._save()

    def _on_locked(self, checked):
        set_lock_text(self.lock_chk, checked)
        self._cfg["locked"] = checked
        if self._overlay is not None:
            self._overlay.set_locked(checked)
        self._save()

    def _resize_preview(self):
        view = getattr(self,"_view",self)
        width = min(self.preview.width(),max(120,view.width()-48))
        self.preview_scroll.setFixedWidth(width)
        self.preview_scroll.setFixedHeight(self.preview.height()+
            (self.preview_scroll.horizontalScrollBar().sizeHint().height() if self.preview.width()>width else 0))

    def _apply_region(self,x,y,w,h):
        if self._shutting_down:
            return
        region = dict(x=x,y=y,w=w,h=h)
        config.save_dorcha({"box":region})
        self._accept_region(x,y,w,h)

    def _accept_region(self,x,y,w,h):
        region = dict(x=x,y=y,w=w,h=h)
        self._afr.user_set("dorcha")  # 이번 실행 동안 사용자 지정이 이김
        self._cfg["box"] = self._region = region
        self._invalidate_search()
        self._set_value(None)
        self._sync_overlay()
        self._tracking_lost = False
        self._approved_target = self._search_target()
        self._apply_gate()

    def _update_region_label(self):
        self._apply_gate()

    def _region_cleared(self):
        self._afr.user_set("dorcha")
        self._cfg["box"] = self._region = None
        self._invalidate_search()
        self._set_value(None)
        self._show_source(None)
        self._update_region_label()
        self._sync_overlay()

    def _on_region(self):
        if self._shutting_down or self._autofind_busy:
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
        from .region_registration import connect_selection
        connect_selection(self, self._selector, self._on_selected)
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
            QMessageBox.warning(self,"영역 저장 실패","기존 등록 영역을 유지해요.")
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
                              "도르카 영역 확인","원 안의 숫자 0~15가 모두 들어가야 해요.")

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
        executor = self.__dict__.pop("_executor", None)
        if executor is not None:
            executor.submit(self._close_thread_mss)  # 작업 스레드의 mss는 그 스레드에서 닫는다
            executor.shutdown(wait=True)
        self._tick_job = self._reread_job = None
        self._close_thread_mss()
        for widget in (self._overlay,self._selector,self._highlight,self._autofind_highlight):
            if widget is not None:
                widget.close()
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                _log.warning("도르카 캡처 정리 실패",exc_info=True)
            self._sct = None
