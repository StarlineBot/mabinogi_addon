"""Grouped resource settings with atomic approval of two independent regions."""

from copy import deepcopy
from concurrent.futures import Future
from contextvars import copy_context
from threading import Event,Thread
import weakref
from PySide6.QtCore import Qt,QEventLoop,QTimer
from shiboken6 import isValid
from PySide6.QtWidgets import (QGroupBox,QHBoxLayout,QLabel,QMessageBox,QPushButton,
                              QToolButton,QVBoxLayout,QWidget)
from .. import config
from ..setup_state import section
from ..autofind_diagnostics import perform_autofind
from . import region_registration as registration
from .dpi import to_logical,to_physical
from .region_highlight import RegionHighlight
from .screen_grab import capture_for_autofind
from .widgets import FeatureHeader, checkbox, hint_label
from .settings_layout import disclosure, danger_style


def notice(owner,title,text):
    QMessageBox.information(owner,title,text)


class ResourceTab(QWidget):
    def __init__(self,dorcha,tuarim):
        super().__init__()
        self.dorcha,self.tuarim = dorcha,tuarim
        self._region_keys = ("dorcha","tuarim")
        self._busy,self._selector = False,None
        self._future = None
        self._cancel = Event()
        self._shutting_down = False
        self._highlights = []
        self._dialog = None
        for c in (dorcha,tuarim):
            c.setParent(self)
            c._resource_view = weakref.ref(self)
            c.hide()
        dorcha._view = self
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(10)
        from .feature_copy import resource_help
        from .help_dialog import help_button
        layout.addWidget(FeatureHeader("도르카·투아림", "도르카와 투아림을 오버레이로 표시하고 투아림 충전 상태를 알려줘요.", help_button("도르카·투아림 사용법", lambda: resource_help(self.dorcha._percent_control is not None and self.dorcha._percent_control.isVisibleTo(self)), self)))
        layout.addWidget(QLabel("판독 영역 · 도르카 / 투아림"))
        # 영역 묶음(안내·도움말 명세 11절): 버튼·안내 한 줄·개별 영역 조정·판독 확인은 지정 후 '영역 다시 지정 · 판독 확인 ▸' 안으로
        outer = layout
        region_body = QWidget()
        layout = QVBoxLayout(region_body)
        layout.setContentsMargins(0,0,0,0)
        self.region_status = QLabel()
        self.region_status.setWordWrap(True)
        layout.addWidget(self.region_status)
        guide = hint_label("보라색 원과 오른쪽 아래의 투아림 숫자·%가 함께 들어오도록 지정해 주세요.")  # 안내 = 회색(명세 14.2)
        layout.addWidget(guide)
        row = QHBoxLayout()
        for attr,text in (("auto_find_btn","자동 찾기"),("region_btn","직접 지정"),
                          ("view_region_btn","지정 영역 보기"),("clear_region_btn","지정 해제")):
            button = QPushButton(text)
            setattr(self,attr,button)
            if attr == "clear_region_btn": row.addStretch()
            if attr == "clear_region_btn": button.setStyleSheet(danger_style())
            row.addWidget(button)
        layout.addLayout(row)
        self.auto_find_btn.clicked.connect(self._auto_find)
        self.region_btn.clicked.connect(self._pick_region)
        self.view_region_btn.clicked.connect(self._show_regions)
        self.clear_region_btn.clicked.connect(self._clear_regions)
        individual = QWidget()
        il = QVBoxLayout(individual)
        il.setContentsMargins(0,0,0,0)
        for name,c in (("도르카 숫자",dorcha),("투아림 %",tuarim)):
            il.addWidget(QLabel(name))
            il.addWidget(c.region_label)
            row = QHBoxLayout()
            for button in (c.region_btn,c.view_region_btn,c.clear_region_btn): row.addWidget(button)
            row.addStretch()
            il.addLayout(row)
            c.auto_find_btn.hide()
        self.individual_btn = disclosure("개별 영역 조정",individual,layout)
        self.reading_group = QGroupBox('판독 확인')
        reading_layout = QVBoxLayout(self.reading_group)
        dorcha.source_preview.setFixedSize(56,28)
        tuarim.preview.setFixedSize(72,28)
        for name,preview,value in (("도르카",dorcha.source_preview,dorcha.value_label),
                                   ("투아림",tuarim.preview,tuarim.value_label)):
            row = QHBoxLayout()
            row.addWidget(QLabel(name))
            row.addWidget(preview)
            row.addWidget(value,1)
            reading_layout.addLayout(row)
        layout.addWidget(self.reading_group)
        from .region_section import RegionSection
        self.region_section = RegionSection(region_body, unset_text="지정하면 도르카와 투아림을 보기 편한 위치에 보여줘요",
                                            title="영역 다시 지정 · 판독 확인")
        layout = outer
        layout.addWidget(self.region_section)
        # 화면 표시(명세 11.2): 1줄 표시 체크 + 잠금, 2줄 배율. 표시 미리보기는 없앰.
        display = QGroupBox("화면 표시")
        box = QVBoxLayout(display)
        row = QHBoxLayout()
        dorcha.enable.setText("도르카 표시")
        self.percent_chk = checkbox("투아림 % 표시")
        self.percent_chk.setChecked(dorcha._cfg["showTuarim"])
        dorcha.bind_tuarim(tuarim,self.percent_chk)
        for control in (dorcha.enable,self.percent_chk): row.addWidget(control)
        row.addStretch()
        row.addWidget(dorcha.lock_chk)
        box.addLayout(row)
        row = QHBoxLayout()
        for control in (QLabel("표시 배율"),dorcha.scale_spin): row.addWidget(control)
        row.addStretch()
        box.addLayout(row)
        layout.addWidget(display)
        # 투아림 알림(명세 11.2): 사용 체크(표시 구역에서 옮김) + 첫 알림 %·소리 · 추가 알림 %·소리
        self.tuarim_alert_box = QGroupBox("투아림 알림")
        alert = QVBoxLayout(self.tuarim_alert_box)
        alert.addWidget(tuarim.enable)
        tuarim.threshold_box.setTitle("")
        tuarim.threshold_box.setFlat(True)
        tuarim.threshold_box.setStyleSheet("QGroupBox { border: 0; margin: 0; padding: 0; }")
        tuarim.threshold_box.layout().setContentsMargins(0, 0, 0, 0)  # 옮겨 온 상자의 안쪽 여백 0(명세 13.4: 다른 줄과 같은 들여쓰기)
        alert.addWidget(tuarim.threshold_box)
        layout.addWidget(self.tuarim_alert_box)
        # 지정 후 요약 줄은 보일 때만 1초마다 판독 값을 옮긴다(숨어 있을 때 비용 없음)
        self._summary_timer = QTimer(self)
        self._summary_timer.setInterval(1000)
        self._summary_timer.timeout.connect(self._update_summary)
        self.diagnostics_btn = QToolButton()
        self.diagnostics_btn.setText("진단 · 도르카/투아림 판독 / 수집")
        self.diagnostics_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.diagnostics_btn.setArrowType(Qt.ArrowType.RightArrow)
        self.diagnostics_btn.setCheckable(True)
        tuarim._diagnostics_toggle = self.diagnostics_btn
        layout.addWidget(self.diagnostics_btn)
        layout.addWidget(tuarim._collect_box)
        self.diagnostics_btn.toggled.connect(self._show_diagnostics)
        layout.addStretch()
        self._show_diagnostics(False)
        dorcha._apply_gate()
        self.refresh_registration()

    def _controllers(self):
        return {"dorcha":self.dorcha,"tuarim":self.tuarim}

    def _auto_find(self):
        self.find_regions()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.dorcha._resize_preview()

    def refresh_registration(self):
        if not isValid(self) or not hasattr(self,"clear_region_btn"): return
        regions = {k:c._region for k,c in self._controllers().items()}
        state = ("둘 다 등록됨" if all(regions.values()) else "도르카만 등록됨" if regions["dorcha"]
                 else "투아림만 등록됨" if regions["tuarim"] else "영역 미지정")
        details = [f"{name} {b['x']},{b['y']} / {b['w']}×{b['h']}"
                   for k,name in (("dorcha","도르카"),("tuarim","투아림")) if (b:=regions[k])]
        self.region_status.setText(state)
        self.region_status.setToolTip("\n".join(details))
        section = getattr(self,"region_section",None)
        if section is not None:  # 영역 묶음(명세 11절): 둘 중 하나라도 지정되면 요약 줄 + 접힘, 막 지정했으면 펼침
            registered = any(regions.values())
            section.set_registered(registered, just_set=registered and not section.registered
                                   and getattr(self,"_region_ready",False))
            self.region_status.setVisible(registered)
            self._region_ready = True
            self._update_summary()
        available = (not self._busy and not self._shutting_down
                     and (self._future is None or self._future.done())
                     and not any(c._shutting_down or c._autofind_busy for c in self._controllers().values()))
        self.auto_find_btn.setEnabled(available)
        self.region_btn.setEnabled(available)
        for b in (self.view_region_btn,self.clear_region_btn): b.setEnabled(available and any(regions.values()))

    def _update_summary(self):
        """`✓ 영역 지정됨 · 도르카 12/15 · 투아림 87%` — 판독 확인 줄의 값을 그대로 옮긴다."""
        if not self.region_section.registered: return
        parts = []
        dorcha = self.dorcha.value_label.text().split(": ",1)[-1]
        if self.dorcha._region and dorcha not in ("", "--/15", "—"): parts.append("도르카 " + dorcha)
        tuarim = self.tuarim.value_label.text().split(": ",1)[-1]
        if self.tuarim._region and tuarim.endswith("%"): parts.append("투아림 " + tuarim)
        self.region_section.set_summary("✓ 영역 지정됨 · " + (" · ".join(parts) if parts else "판독 대기"))

    def showEvent(self,event):
        super().showEvent(event)
        self._update_summary()
        self._summary_timer.start()

    def hideEvent(self,event):
        self._summary_timer.stop()
        super().hideEvent(event)

    def _show_diagnostics(self,checked):
        self.diagnostics_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.tuarim._apply_collect_gate()

    def _show_regions(self):
        self._close_highlights()
        for key,c in self._controllers().items():
            if c._region:
                mark = RegionHighlight()
                mark.flash(*(c._region[k] for k in ("x","y","w","h")),"등록 영역",
                           "도르카 숫자" if key == "dorcha" else "투아림 %")
                self._highlights.append(mark)

    def _close_highlights(self):
        for mark in self._highlights:
            if isValid(mark):
                mark.close()
                mark.deleteLater()
        self._highlights.clear()

    def _pick_region(self):
        if self._busy or not registration.editing_allowed(self): return
        from .region_selector import RegionSelector
        if self._selector is not None and isValid(self._selector):
            self._selector.close()
            self._selector.deleteLater()
        self._selector = RegionSelector()
        registration.connect_selection(self,self._selector,self._manual_region)
        self._selector.start()

    def _manual_region(self,x,y,w,h):
        left,top,width,height = to_physical(dict(x=x,y=y,w=w,h=h))
        def capture():
            frame,ox,oy = capture_for_autofind(restore_allowed=lambda:registration.editing_allowed(self))
            if frame is None or left < ox or top < oy or left+width > ox+frame.shape[1] or top+height > oy+frame.shape[0]:
                return None,left,top
            from ..autofind_diagnostics import capture_info
            if (info:=capture_info.get()) is not None:
                info["manual_crop_physical"] = [left,top,width,height]
                info["source_capture_offset"] = [ox,oy]
                info["source_capture_shape"] = [frame.shape[1],frame.shape[0]]
            return frame[top-oy:top-oy+height,left-ox:left-ox+width].copy(),left,top
        keys = ("dorcha","tuarim")
        self.find_regions(keys=keys,capture=capture)

    def find_regions(self,*,keys=("dorcha","tuarim"),capture=None,allowed=lambda:True):
        if (self._busy or not registration.editing_allowed(self)
                or self._future is not None and not self._future.done()
                or any(c._shutting_down or c._autofind_busy for c in self._controllers().values())): return {}
        caller_allowed = allowed
        allowed = caller_allowed
        self._approval_allowed = allowed
        stamp = registration.generation(self)
        before = deepcopy(config._read_local_config())
        applied,trace = {},{}
        self.last_status = "not_found"
        self._cancel.clear()
        running = {k:c._timer.isActive() for k,c in self._controllers().items()}
        self._busy = True
        for c in self._controllers().values():
            c._autofind_busy = True
            c._timer.stop()
        self.refresh_registration()
        def detect(frame,detail,assets):
            from ..detect.resource_pair import locate_resources
            future = Future()
            self._future = future
            cancel = self._cancel
            def work():
                local = {}
                try:
                    box = locate_resources(frame,assets,local,cancelled=cancel.is_set)
                    future.set_result((box,local))
                except Exception as exc:
                    future.set_exception(exc)
            context = copy_context()
            Thread(target=lambda:context.run(work),daemon=True,name="resource-detect").start()
            loop = QEventLoop(self)
            poll = QTimer(self)
            def check():
                if not registration.editing_allowed(self) or not allowed():
                    cancel.set()
                    loop.quit()
                elif future.done():
                    loop.quit()
            poll.timeout.connect(check)
            poll.start(30)
            try:
                loop.exec()
                if cancel.is_set(): return None
                result,local = future.result()
                detail.update(local)
                trace.update(local)
                return result
            finally:
                poll.stop()
                poll.timeout.disconnect()
                poll.deleteLater()
                loop.deleteLater()
        def confirm(_box,ox,oy):
            if not registration.editing_allowed(self) or not allowed() or registration.generation(self) != stamp:
                return {"status":"cancelled_shutdown"}
            regions = {k:to_logical(b[0]+ox,b[1]+oy,b[2],b[3]) for k,b in trace.get("regions",{}).items() if k in keys}
            if not regions:
                notice(self,"후보 확인","선택한 대상의 위치를 확인하지 못했어요. 기존 영역을 유지해요.")
                return {"status":"no_requested_candidate"}
            self._close_highlights()
            names = []
            for k,b in regions.items():
                name = "도르카 숫자" if k == "dorcha" else "투아림 %"
                names.append(name)
                mark = RegionHighlight()
                mark.flash(*b,"공통 영역 확인",name,msec=0)
                self._highlights.append(mark)
            title = " / ".join(names)+(" · 선택한 대상 찾음" if len(keys)==1 else
                                      " 둘 다 찾음" if len(regions)==2 else "만 찾음")
            answer = self._approve(title)
            self.last_status = "cancelled"
            if answer != QMessageBox.StandardButton.Yes or not registration.editing_allowed(self) or not allowed() or registration.generation(self) != stamp:
                return {"status":"cancelled"}
            latest = config._read_local_config()
            for k in keys:
                name,field,_ = registration.REGIONS[k]
                if section(latest,name).get(field) != section(before,name).get(field):
                    registration.warn(self,"영역 변경됨","확인 중 영역이 변경됐어요. 다시 시도하세요.")
                    return {"status":"cancelled"}
            if not registration.save_boxes(self,regions):
                self.last_status = "save_failed"
                return {"status":"save_failed"}
            for k,b in regions.items():
                registration.invalidate_region(k)
                self._controllers()[k]._accept_region(*b)
            applied.update(regions)
            self.last_status = "applied"
            return {"status":"applied","regions_logical":{k:list(b) for k,b in regions.items()}}
        try:
            frame,_,_,box = perform_autofind("resources",capture or (lambda:capture_for_autofind(
                require_game=True,restore_allowed=lambda:registration.editing_allowed(self))),detect=detect,confirm=confirm)
            if registration.editing_allowed(self) and allowed() and (frame is None or box is None):
                notice(self,"공통 영역 확인 불가",
                    "화면 또는 영역 위치를 확인하지 못했어요. 기존 영역은 유지돼요. 개별 영역 조정을 사용할 수 있어요.")
        except Exception:
            if registration.editing_allowed(self): registration.warn(self,"공통 영역 설정 실패","기존 영역을 유지해요. 진단 ZIP을 확인해 주세요.")
        finally:
            self._close_highlights()
            self._busy = False
            for k,c in self._controllers().items():
                c._autofind_busy = False
                if running[k] and not c._shutting_down and not self._shutting_down: c._timer.start()
            self.refresh_registration()
            self._approval_allowed = None
        return applied

    def shutdown(self):
        self._shutting_down = True
        self._cancel.set()
        self._close_highlights()
        if self._dialog is not None:
            self._dialog.reject()
        if self._selector is not None and isValid(self._selector):
            self._selector.close()

    def _approve(self,title):
        self._dialog = QMessageBox(self)
        self._dialog.setWindowTitle("도르카·투아림 · 후보 확인")
        self._dialog.setText(title+"\n표시한 영역을 등록할까요? 찾지 못한 쪽의 기존 영역은 유지해요.")
        self._dialog.setStandardButtons(QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        self._dialog.setDefaultButton(QMessageBox.StandardButton.No)
        poll = QTimer(self._dialog)
        def check():
            if not registration.editing_allowed(self) or (self._approval_allowed is not None and not self._approval_allowed()):
                self._dialog.reject()
        poll.timeout.connect(check)
        poll.start(30)
        try:
            return self._dialog.exec()
        finally:
            poll.stop()
            poll.timeout.disconnect()
            self._dialog.deleteLater()
            self._dialog = None

    def _clear_regions(self):
        if self._busy or not registration.editing_allowed(self): return
        before = config._read_local_config()
        answer = registration.confirm_clear(self,"도르카·투아림 지정 해제",
            "두 판독 영역을 지정 해제할까요? 도르카 표시·투아림 표시·투아림 알림이 중단돼요.\n"
            "표시/알림 선택·위치·배율·잠금·소리 설정은 유지해요.")
        if answer != QMessageBox.StandardButton.Yes or not registration.editing_allowed(self): return
        latest = config._read_local_config()
        for k in self._region_keys:
            name,field,_ = registration.REGIONS[k]
            if section(latest,name).get(field) != section(before,name).get(field):
                registration.warn(self,"영역 변경됨","확인 중 영역이 변경됐어요. 다시 시도하세요.")
                return
            latest[name] = dict(section(latest,name))
            latest[name][field] = None
        try:
            config._write_local_config(latest)
        except OSError:
            registration.warn(self,"지정 해제 실패","기존 영역과 동작을 유지해요.")
            return
        for k,c in self._controllers().items():
            registration.invalidate_region(k)
            if c._selector is not None and isValid(c._selector): c._selector.close()
            c._region_cleared()
        self.refresh_registration()
