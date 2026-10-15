"""기존 진단 파이프라인을 사용하는 순차 탐색·화면 위 영역 승인.

캡처와 모든 Qt/설정 변경은 UI 스레드, 검출만 데몬 워커에서 실행한다.
종료/중단 후 늦게 끝난 검출은 UI나 설정에 접근하지 않는다.
"""

from concurrent.futures import Future
from contextvars import copy_context
from threading import Thread

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QMessageBox

from .. import config
from ..autofind_diagnostics import perform_autofind
from ..autofind_replay import run_detector
from ..setup_state import BY_KEY, pending, section
from .dpi import to_logical
from .screen_grab import capture_for_autofind
from .region_highlight import RegionHighlight
from .top_edge_selector import TopEdgeSelector


class SetupFlow:
    def __init__(self, page, apply):
        self.page = page
        self.apply = apply
        self.closed = False
        self.cancelled = False
        self.loop = None
        self.future = None
        self.choice = False
        self.dialog = None
        self.selector = None
        self._restore_generation = 0  # 캡처용 hide와 사용자가 요청한 창 숨김을 구분
        page.run_requested.connect(self.run)
        page.cancel_requested.connect(self.cancel)

    def decide(self, value):
        self.choice = value
        if self.loop is not None:
            self.loop.quit()

    def cancel(self, *, hide=False):
        if hide:
            self._restore_generation += 1
        self.cancelled = True
        self.decide(False)
        if self.dialog is not None:
            self.dialog.reject()
        if self.selector is not None:
            self.selector.close()

    def shutdown(self):
        self.closed = True
        self.cancel()

    def _detect(self, feature, frame, trace, assets):
        if self.closed or self.cancelled:
            return None
        future = Future()
        self.future = future

        def work():
            local_trace = {}
            try:
                result = run_detector(feature, frame, assets, local_trace)
                future.set_result((result, local_trace))
            except Exception as exc:
                future.set_exception(exc)

        context = copy_context()
        self.loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(30)
        poll.timeout.connect(lambda: self.loop.quit() if future.done() else None)
        Thread(target=lambda: context.run(work), daemon=True, name="setup-detect").start()
        poll.start()
        try:
            self.loop.exec()
            if self.closed or self.cancelled:
                return None
            box, details = future.result()
            trace.update(details)
            return box
        finally:
            poll.stop()
            self.loop = None

    def _approve(self, key, logical):
        feature = BY_KEY[key]
        if key == "buff":
            result = []
            self.loop = QEventLoop()
            self.selector = TopEdgeSelector(logical[0], logical[2], logical[1])
            self.selector.selected.connect(lambda *box: (result.append(box), self.loop.quit()))
            self.selector.cancelled.connect(self.loop.quit)
            try:
                self.selector.start()
                self.loop.exec()
                return result[0] if result and not self.cancelled and not self.closed else None
            finally:
                self.selector.close()
                self.selector.deleteLater()
                self.selector = None
                self.loop = None
        highlight = RegionHighlight()
        self.dialog = QMessageBox(self.page)
        self.dialog.setWindowTitle(feature.name + " · 찾은 영역 확인")
        self.dialog.setText(feature.guidance + "\n이 영역으로 등록할까요?")
        self.dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        self.dialog.setDefaultButton(QMessageBox.StandardButton.No)
        self.dialog.button(QMessageBox.StandardButton.Yes).setText("이 영역으로 등록")
        self.dialog.button(QMessageBox.StandardButton.No).setText("등록하지 않기")
        try:
            highlight.flash(*logical, feature.name, feature.guidance, msec=0)
            answer = self.dialog.exec()
            return logical if answer == QMessageBox.StandardButton.Yes and not self.closed and not self.cancelled else None
        finally:
            highlight.close()
            highlight.deleteLater()
            self.dialog.deleteLater()
            self.dialog = None

    def _notice(self, title, text):
        self.dialog = QMessageBox(self.page)
        self.dialog.setWindowTitle(title)
        self.dialog.setText(text)
        try:
            self.dialog.exec()
        finally:
            self.dialog.deleteLater()
            self.dialog = None

    def run(self):
        page = self.page
        if self.closed or page.busy or (self.future is not None and not self.future.done()):
            return
        if config.load_discord_user() is None:
            page.progress.setText("자동설정은 베타 기능입니다. 설정 > Discord 계정에서 로그인하면 사용할 수 있습니다.")
            return
        if not section(config._read_local_config(), "general").get("gameExe"):
            page.progress.setText("게임창을 먼저 등록한 뒤 자동설정을 실행하세요.")
            return
        keys = pending(automatic_only=True)
        if not keys:
            page.progress.setText("자동으로 찾을 미등록 영역이 없습니다. 직접 지정할 항목은 개별 설정에서 등록하세요.")
            return
        self.cancelled = False
        results = {"등록 완료": [], "등록하지 않음": [], "찾지 못함": [], "저장 실패": []}
        page.set_busy(True)
        try:
            for index, key in enumerate(keys, 1):
                if config.load_discord_user() is None:
                    self.cancel()
                if self.closed or self.cancelled:
                    break
                # 앞선 승인이 공유 영역을 등록했다면 다음 시도에서 건너뛴다.
                if key not in pending(automatic_only=True):
                    continue
                feature = BY_KEY[key]
                page.run_btn.setText(f"{feature.name} 찾는 중… ({index}/{len(keys)})")
                current = {}
                outcome = {"status": "not_offered"}

                def capture():
                    generation = self._restore_generation
                    window = page.window()
                    current["frame"], ox, oy = capture_for_autofind(
                        require_game=True, restore_allowed=lambda: not self.closed,
                        restore_widget_allowed=lambda widget: widget is not window or generation == self._restore_generation)
                    from ..autofind_diagnostics import capture_info
                    current["capture"] = dict(capture_info.get() or {})
                    if self.closed or self.cancelled:
                        return None, ox, oy
                    return current["frame"], ox, oy

                def confirm(box, ox, oy):
                    if config.load_discord_user() is None:
                        self.cancel()
                    if self.closed or self.cancelled:
                        return {"status": "cancelled_shutdown" if self.closed else "cancelled"}
                    logical = to_logical(box[0] + ox, box[1] + oy, box[2], box[3])
                    if key == "skillbar":
                        from .skillbar_mirror import SRC_W, SRC_H
                        if abs(logical[2] - SRC_W) > 1 or abs(logical[3] - SRC_H) > 1:
                            outcome.update(status="unsupported_grid")
                            return dict(outcome)
                    if key == "debuff":
                        x, y, w, h = box
                        strip = max(12, int(h * 1.4))
                        top = max(0, y - strip)
                        logical = to_logical(x + ox, top + oy, w, y + h - top)
                    approved = self._approve(key, logical)
                    if config.load_discord_user() is None:
                        self.cancel()
                    if self.closed or self.cancelled or approved is None:
                        outcome.update(status="cancelled_shutdown" if self.closed else "cancelled")
                    elif key not in pending(automatic_only=True):
                        outcome.update(status="already_registered")
                    else:
                        try:
                            self.apply(key, approved)
                            outcome.update(status="applied", logical_box=list(approved))
                        except Exception as exc:
                            outcome.update(status="save_failed", error=f"{type(exc).__name__}: {exc}")
                    page.refresh()
                    return dict(outcome)

                frame, _, _, box = perform_autofind(key, capture,
                    detect=lambda frame, trace, assets: self._detect(key, frame, trace, assets),
                    confirm=confirm)
                if self.closed or self.cancelled:
                    break
                status = outcome["status"]
                if status in ("applied", "already_registered"):
                    results["등록 완료"].append(feature.name)
                elif status == "cancelled":
                    results["등록하지 않음"].append(feature.name)
                else:
                    reason = ("게임창 미발견 또는 캡처 실패" if frame is None else
                              "저장 실패" if status == "save_failed" else
                              "단축바 크기 미지원" if status == "unsupported_grid" else "현재 화면에서 미발견")
                    if status == "save_failed":
                        reason += ": " + outcome.get("error", "")
                    label = "저장 실패" if status == "save_failed" else "찾지 못함"
                    results[label].append(feature.name + f" ({reason})")
                    self._notice(feature.name + " · 등록하지 못함",
                        reason + "\n" + (
                            "보스 체력바가 보이는 상태에서 다시 시도하세요." if key in ("boss", "debuff") else
                            "대상 UI가 보이는 상태에서 다시 시도하세요.") +
                        "\n기존 설정은 유지됩니다. 실패 입력은 설정에서 진단 ZIP으로 저장할 수 있습니다.")
                if frame is None:
                    # 전체 캡처 실패는 같은 화면의 나머지 항목에 반복하지 않는다.
                    break
        finally:
            if not self.closed:
                page.run_btn.setText("자동설정")
                page.set_busy(False)
                summary = " / ".join(f"{label} {len(names)}" for label, names in results.items())
                details = "\n".join(label + ": " + ", ".join(names) for label, names in results.items() if names)
                page.progress.setText(("중단했습니다. " if self.cancelled else "") + summary + ("\n" + details if details else ""))
