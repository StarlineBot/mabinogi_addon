"""0.31.1 QA: 숫자 칸이 넓은 스타일(Windows 11 — 가로 화살표)에서도 버프·디버프 탭이 790 창에서 두 칸을 유지한다.

오프스크린(Fusion)에는 Windows 11 스타일이 없어, 숫자 칸 폭만 넓히는 프록시 스타일로 같은 조건을 만든다.
(0.31.0: 세 칸 최소 폭을 가장 넓은 칸 기본 폭의 3배로 걸어 이 조건에서 한 칸으로 접혔다.) 실제 스타일은
tests/test_lock_row_native_width.py(windows_integration)가 Windows에서 확인한다.
"""
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleFactory

from test_navigation import window  # noqa: F401  (픽스처)

EXTRA = 48  # Windows 11 숫자 칸: 위/아래 화살표가 오른쪽에 가로로 두 개(약 +40~50px)


class WideSpinStyle(QProxyStyle):
    def sizeFromContents(self, kind, option, size, widget=None):
        result = super().sizeFromContents(kind, option, size, widget)
        if kind == QStyle.ContentsType.CT_SpinBox:
            result.setWidth(result.width() + EXTRA)
        return result


def test_wide_spin_style_keeps_two_columns(window):
    w, app = window
    old = app.style().name()
    app.setStyle(WideSpinStyle(QStyleFactory.create(old)))
    try:
        for chat in (False, True):
            w.creator_dialogue.set_enabled(chat)
            w.creator_dialogue.refresh()
            for key in ("buff", "debuff"):
                tab = getattr(w, key + "_tab")
                for widget in (tab.scale_spin, tab.opacity_spin):  # 스타일이 바뀐 폭으로 최소 폭을 다시 잡게
                    widget.setMinimumWidth(0)
                from mabinogi_addon.ui.settings_layout import equal_columns, lock_width
                equal_columns(tab.lock_btn, tab.scale_spin, tab.opacity_spin, at_least=lock_width(tab.lock_btn))
                w._open_setup_feature(key)
                for _ in range(4):
                    app.processEvents()
                assert not tab._columns.stacked, (key, chat)
                for widget in (tab.lock_btn, tab.scale_spin, tab.opacity_spin):
                    assert widget.width() >= widget.minimumSizeHint().width()
    finally:
        QApplication.instance().setStyle(QStyleFactory.create(old))
