"""마비노기 버프·디버프 화면 트래커."""

from __future__ import annotations


def main() -> None:
    """메인 창을 띄운다. (개발 중 실행: `uv run mabinogi-addon`)"""
    import logging
    import os
    import sys

    from PySide6.QtWidgets import QApplication

    # 디버그 로그: 기본 INFO, `MABINOGI_DEBUG=1`이면 DEBUG. 터미널(stderr)로 출력.
    level = logging.DEBUG if os.environ.get("MABINOGI_DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from mabinogi_addon.ui.main_window import MainWindow, app_icon

    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())  # 작업표시줄/트레이 아이콘
    window = MainWindow()
    window.show()
    window.start()  # 파티 폴링 등 백그라운드 작업 시작
    sys.exit(app.exec())
