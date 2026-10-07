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
    # 문의 '버그 신고' 첨부용: 최근 로그를 메모리에 함께 쌓는다(터미널과 별개).
    from mabinogi_addon import logbuffer

    logbuffer.install()

    from mabinogi_addon import config
    from mabinogi_addon.ui.main_window import MainWindow, app_icon

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    # setApplicationDisplayName은 쓰지 않는다 — 설정하면 Qt가 모든 창 제목 뒤에
    # " - <이름>"을 자동으로 붙여, 창 제목에 이름이 두 번 나온다(중복).
    app.setWindowIcon(app_icon())  # 작업표시줄/트레이 아이콘
    # 트레이 최소화를 위해, 창을 숨겨도(마지막 창 닫혀도) 앱이 종료되지 않게 한다.
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    if not config.load_general_flag("startInTray", False):
        window.show()  # '트레이로 시작'이면 창 없이 트레이만
    window.start()  # 파티 폴링 등 백그라운드 작업 시작
    sys.exit(app.exec())
