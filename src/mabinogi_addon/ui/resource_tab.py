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
from .widgets import FeatureHeader, checkbox
from .settings_layout import disclosure, DANGER_STYLE


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
        layout.addWidget(FeatureHeader("도르카·투아림", "도르카와 투아림을 오버레이로 표시하고 투아림 충전 상태를 알려줍니다."))
        layout.addWidget(QLabel("판독 영역 · 도르카 / 투아림"))
        self.region_status = QLabel()
        self.region_status.setWordWrap(True)
        layout.addWidget(self.region_status)
        guide = QLabel("원형 자원 UI와 오른쪽 아래 퍼센트를 함께 설정합니다.")
        guide.setWordWrap(True)
        layout.addWidget(guide)
        row = QHBoxLayout()
        for attr,text in (("auto_find_btn","자동 찾기"),("region_btn","직접 지정"),
                          ("view_region_btn","지정 영역 보기"),("clear_region_btn","지정 해제")):
            button = QPushButton(text)
            setattr(self,attr,button)
            if attr == "clear_region_btn": row.addStretch()
            if attr == "clear_region_btn": button.setStyleSheet(DANGER_STYLE)
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
        display = QGroupBox("표시")
        box = QVBoxLayout(display)
        row = QHBoxLayout()
        dorcha.enable.setText("도르카 표시")
        self.percent_chk = checkbox("투아림 % 표시")
        self.percent_chk.setChecked(dorcha._cfg["showTuarim"])
        dorcha.bind_tuarim(tuarim,self.percent_chk)
        for control in (dorcha.enable,self.percent_chk,tuarim.enable): row.addWidget(control)
        row.addStretch()
        box.addLayout(row)
        row = QHBoxLayout()
        for control in (QLabel("표시 배율"),dorcha.scale_spin,dorcha.lock_chk): row.addWidget(control)
        row.addStretch()
        box.addLayout(row)
        box.addWidget(QLabel("표시 미리보기"))
        box.addWidget(dorcha.preview_scroll,0,Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(display)
        tuarim.threshold_box.setTitle("투아림 알림 (% 이상)")
        layout.addWidget(tuarim.threshold_box)
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
                 else "투아림만 등록됨" if regions["tuarim"] else "영역 미등록")
        details = [f"{name} {b['x']},{b['y']} / {b['w']}×{b['h']}"
                   for k,name in (("dorcha","도르카"),("tuarim","투아림")) if (b:=regions[k])]
        self.region_status.setText(state)
        self.region_status.setToolTip("\n".join(details))
        available = (not self._busy and not self._shutting_down
                     and (self._future is None or self._future.done())
                     and not any(c._shutting_down or c._autofind_busy for c in self._controllers().values()))
        self.auto_find_btn.setEnabled(available and self.dorcha._logged_in())
        self.region_btn.setEnabled(available)
        for b in (self.view_region_btn,self.clear_region_btn): b.setEnabled(available and any(regions.values()))

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
        if capture is None and not self.dorcha._logged_in(): return {}
        caller_allowed = allowed
        require_login = capture is None
        allowed = lambda:caller_allowed() and (not require_login or self.dorcha._logged_in())
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
                notice(self,"후보 확인","선택한 대상의 위치를 확인하지 못했습니다. 기존 영역을 유지합니다.")
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
                    registration.warn(self,"영역 변경됨","확인 중 영역이 변경됐습니다. 다시 시도하세요.")
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
                    "화면 또는 영역 위치를 확인하지 못했습니다. 기존 영역은 유지됩니다. 개별 영역 조정을 사용할 수 있습니다.")
        except Exception:
            if registration.editing_allowed(self): registration.warn(self,"공통 영역 설정 실패","기존 영역을 유지합니다. 진단 ZIP을 확인해 주세요.")
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
        self._dialog.setText(title+"\n표시한 영역을 등록할까요? 찾지 못한 쪽의 기존 영역은 유지합니다.")
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
            "두 판독 영역을 지정 해제할까요? 도르카 표시·투아림 표시·투아림 알림이 중단됩니다.\n"
            "표시/알림 선택·위치·배율·잠금·소리 설정은 유지합니다.")
        if answer != QMessageBox.StandardButton.Yes or not registration.editing_allowed(self): return
        latest = config._read_local_config()
        for k in self._region_keys:
            name,field,_ = registration.REGIONS[k]
            if section(latest,name).get(field) != section(before,name).get(field):
                registration.warn(self,"영역 변경됨","확인 중 영역이 변경됐습니다. 다시 시도하세요.")
                return
            latest[name] = dict(section(latest,name))
            latest[name][field] = None
        try:
            config._write_local_config(latest)
        except OSError:
            registration.warn(self,"지정 해제 실패","기존 영역과 동작을 유지합니다.")
            return
        for k,c in self._controllers().items():
            registration.invalidate_region(k)
            if c._selector is not None and isValid(c._selector): c._selector.close()
            c._region_cleared()
        self.refresh_registration()
