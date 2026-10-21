"""Approval-only flow for Tuarim and skillbar; no settings change on failure."""

from PySide6.QtWidgets import QMessageBox

from ..autofind_diagnostics import perform_autofind
from .dpi import to_logical
from .region_highlight import RegionHighlight
from .screen_grab import capture_for_autofind


def confirm_autofind(tab, feature, label, apply, compatible=None, *, capture=None, allowed=None):
    from .region_registration import generation, editing_allowed
    stamp = generation(tab)
    if tab._autofind_busy or tab._shutting_down:
        return
    tab._autofind_busy = True
    tab.auto_find_btn.setEnabled(False)
    running = tab._timer.isActive()
    tab._timer.stop()
    highlight = None
    def confirm(box, ox, oy):
        nonlocal highlight
        if tab._shutting_down or generation(tab) != stamp:
            return {"status": "cancelled_shutdown"}
        x, y, w, h = box
        logical = to_logical(x + ox, y + oy, w, h)
        if compatible is not None and not compatible(logical):
            QMessageBox.information(tab, "자동 찾기 — 미지원 배치",
                "찾은 원본 크기가 현재 미러 격자와 맞지 않습니다. 기존 앵커는 유지됩니다.")
            return {"status": "unsupported_grid", "region_logical": list(logical)}
        highlight = RegionHighlight()
        tab._autofind_highlight = highlight
        highlight.flash(*logical, "자동 찾기 결과", label, msec=0)
        answer = QMessageBox.question(tab, "자동 찾기 — 확인",
            f"점선 안의 {label} 위치가 맞나요?\n이 영역으로 지정할까요?\n"
            "아니오를 누르면 기존 설정을 유지합니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if (answer == QMessageBox.StandardButton.Yes and editing_allowed(tab) and generation(tab) == stamp
                and (allowed is None or allowed())):
            try:
                apply(*logical)
            except Exception as exc:
                QMessageBox.warning(tab, "자동 찾기 — 저장 실패", "설정 저장에 실패했습니다. 기존 영역을 유지합니다.")
                return {"status": "save_failed", "error": type(exc).__name__}
            return {"status": "applied", "region_logical": list(logical)}
        return {"status": "cancelled", "region_logical": list(logical)}
    try:
        frame, ox, oy, box = perform_autofind(feature, capture or capture_for_autofind, confirm=confirm)
        if tab._shutting_down:
            return
        if frame is None:
            QMessageBox.warning(tab, "자동 찾기", "화면 캡처에 실패했습니다. 다시 시도해 주세요.")
        elif box is None:
            QMessageBox.information(tab, "자동 찾기 — 확인 불가",
                f"{label}의 위치나 구조를 확인하지 못했습니다.\n"
                "대상 UI가 보이도록 한 뒤 다시 시도하거나 수동으로 지정해 주세요.\n"
                "기존 설정은 유지됩니다. 진단 ZIP에서 실패 정보를 확인할 수 있습니다.")
    except Exception:
        if not tab._shutting_down:
            QMessageBox.warning(tab, "자동 찾기", "자동찾기 처리에 실패했습니다. 기존 설정은 유지됩니다.")
    finally:
        if highlight is not None:
            highlight.close()
            highlight.deleteLater()
        tab._autofind_highlight = None
        tab._autofind_busy = False
        if not tab._shutting_down:
            tab.auto_find_btn.setEnabled(True)
        if running and not tab._shutting_down:
            tab._timer.start()
