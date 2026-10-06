"""마비노기 버프·디버프 화면 트래커."""

from __future__ import annotations


def main() -> None:
    """메인 창을 띄운다. (개발 중 실행: `uv run mabinogi-addon`)"""
    import sys

    from PySide6.QtWidgets import QApplication

    from mabinogi_addon.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window.start()  # 파티 폴링 등 백그라운드 작업 시작
    sys.exit(app.exec())
