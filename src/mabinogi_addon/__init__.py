"""마비노기 버프·디버프 화면 트래커."""

from __future__ import annotations


def main() -> None:
    """메인 창을 띄운다. (개발 중 실행: `uv run mabinogi-addon`)"""
    from mabinogi_addon.system.startup import StartupScreen

    startup = StartupScreen()
    try:
        _main(startup)
    finally:
        # Includes import/configuration errors, duplicate launch and update relaunch.
        startup.close()


def _main(startup) -> None:
    import logging
    import os
    import sys

    from PySide6.QtWidgets import QApplication

    # 콘솔(stderr)은 기본 INFO(디버그 켜면 DEBUG). 단 루트는 DEBUG로 두고 핸들러별로
    # 레벨을 제어해, 버그 신고 첨부용 링버퍼는 '항상 DEBUG까지' 담는다(배포본에서도
    # 깊은 단서가 남게). 콘솔은 그대로 조용.
    console_level = logging.DEBUG if os.environ.get("MABINOGI_DEBUG") else logging.INFO
    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s", "%H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(fmt)
    root.addHandler(console)

    # 문의 '버그 신고' 첨부용: 최근 로그를 메모리에 함께 쌓는다(DEBUG까지, 터미널과 별개).
    from mabinogi_addon import logbuffer

    logbuffer.install()

    # 파일 로그: 앱이 꺼진 뒤에도(크래시 등) 원인이 남게 user_data_dir/logs/app.log에 기록한다.
    # 메모리 링버퍼는 프로세스가 죽으면 사라지므로, 크래시 진단엔 파일이 필요하다(회전 보관).
    try:
        from logging.handlers import RotatingFileHandler

        from mabinogi_addon import paths

        log_dir = paths.user_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_fmt = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
        )
        fileh = RotatingFileHandler(
            log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fileh.setLevel(logging.DEBUG)
        fileh.setFormatter(file_fmt)
        root.addHandler(fileh)
        # 네이티브 abort·접근 위반(파이썬 예외가 아닌 크래시 — 예: 실행 중 QThread 파괴)은
        # 로깅으로 안 남는다. faulthandler가 그 순간 '모든 스레드 스택'을 crash.log에 덤프해
        # 원인을 남긴다. 파일은 append로 열어 두고 닫지 않는다(크래시 시점에 써야 하므로).
        import faulthandler

        _crash_fp = open(log_dir / "crash.log", "a", buffering=1, encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(_crash_fp, all_threads=True)
    except Exception:  # noqa: BLE001 — 파일 로그 실패해도 앱은 돈다
        logging.getLogger("mabinogi_addon").info("파일 로그 설정 실패(무시)", exc_info=True)

    # 처리되지 않은 예외도 로그에 남겨, 버그 신고 로그·파일에서 크래시 원인이 보이게 한다.
    # 같은 예외가 타이머마다 반복되면 처음 1회만 traceback, 이후 100회마다 요약(로그 폭주 방지, 0.15.0).
    from mabinogi_addon.log_throttle import ExceptionThrottle

    throttle = ExceptionThrottle()

    def _excepthook(exc_type, exc, tb) -> None:
        if throttle.log(logging.getLogger("mabinogi_addon"), "처리되지 않은 예외", (exc_type, exc, tb)) == "full":
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    # 스레드(워커)에서 올라온 미처리 예외도 파일에 남긴다(프로세스 abort 전 원인 포착).
    import threading

    def _thread_excepthook(args) -> None:
        throttle.log(
            logging.getLogger("mabinogi_addon"),
            "처리되지 않은 스레드 예외(%s)",
            (args.exc_type, args.exc_value, args.exc_traceback),
            getattr(args.thread, "name", "?"),
        )

    threading.excepthook = _thread_excepthook

    from mabinogi_addon import config
    from mabinogi_addon.system import updater
    from mabinogi_addon.ui.main_window import MainWindow, app_icon

    updater.cleanup_old()  # 지난 업데이트 교체 후 남은 <exe>.old 정리(배포본만)

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    # 저장된 테마(시스템/라이트/다크) 적용
    from mabinogi_addon.ui.theme import apply_theme

    apply_theme(config.load_theme())
    # setApplicationDisplayName은 쓰지 않는다 — 설정하면 Qt가 모든 창 제목 뒤에
    # " - <이름>"을 자동으로 붙여, 창 제목에 이름이 두 번 나온다(중복).
    app.setWindowIcon(app_icon())  # 작업표시줄/트레이 아이콘
    # 트레이 최소화를 위해, 창을 숨겨도(마지막 창 닫혀도) 앱이 종료되지 않게 한다.
    app.setQuitOnLastWindowClosed(False)

    start_in_tray = config.load_general_flag("startInTray", False)
    # Keep the bootloader's actual window through Python initialization. Source
    # runs use the same-design Qt fallback; tray startup opens no follow-up screen.
    startup.configure(start_in_tray=start_in_tray)
    splash = None if start_in_tray else startup

    # 실행 전 업데이트 선적용: 새 버전이 있으면 스플래시에서 받아 교체·재실행한다.
    # (옛 버전 창을 먼저 보여준 뒤 배너로 안내하던 흐름을 대체)
    if _apply_update_before_launch(splash):
        return  # 교체 + 새 exe 재실행됨 → 이 프로세스는 조용히 종료

    # 단일 인스턴스 가드: 이미 떠 있으면 두 번째는 조용히 종료(트레이 아이콘 둘 방지).
    # 업데이트 자가-재실행 '이후'에 둬서, 재실행 과도기의 세그먼트 경합을 피한다.
    from mabinogi_addon.system.single_instance import SingleInstance

    single = SingleInstance()
    if single.already_running:
        if splash is not None:
            splash.close()
        return

    if splash is not None:
        splash.step(45)
    window = MainWindow()  # 가장 무거운 단계(카탈로그·엔진·오버레이 구성)
    if splash is not None:
        splash.step(95)
    window.start()  # 파티 폴링 등 백그라운드 작업 시작
    if splash is not None:
        splash.step(100)
        splash.close()  # 창을 띄우기 '전'에 닫는다(뒤에 흰 빈 창이 비치지 않게)
    if not start_in_tray:
        window.show()  # '트레이로 시작'이면 창 없이 트레이만
    sys.exit(app.exec())


def _apply_update_before_launch(splash) -> bool:
    """새 버전이 있으면 스플래시에서 받아 교체·재실행한다. 적용했으면 True.

    네트워크·다운로드·교체 실패는 전부 삼키고 False(현재 버전으로 계속 실행) — 업데이트는
    부가 기능이라 앱 실행을 막지 않는다. 스플래시가 없으면(트레이 시작) 건너뛴다.
    """
    import logging

    from mabinogi_addon.system import updater

    if splash is None or not updater.can_update():
        return False
    try:
        splash.step(12, "업데이트 확인 중")
        info = updater.check_latest()
        if not info:
            return False
        ver = str(info.get("version", "?"))
        splash.step(15, f"새 버전 v{ver} 받는 중")
        new_path = updater.download(
            info,
            progress_cb=lambda p: splash.step(
                15 + int(p * 0.7), f"새 버전 v{ver} 받는 중 {p}%"
            ),
        )
        splash.step(92, "업데이트 적용 중")
        updater.apply_update(new_path)  # 교체 + 새 exe 재실행
        return True
    except updater.RelaunchError as exc:
        # 설치는 끝났다(디스크 exe가 새 버전). 이 옛 프로세스로 계속 띄우지 않고 다시 실행을 안내한다.
        logging.getLogger("mabinogi_addon").warning("업데이트 후 재실행 실패: %s", exc)
        from PySide6.QtWidgets import QMessageBox

        splash.close()
        QMessageBox.information(None, "업데이트 설치 완료", f"새 버전을 설치했어요. {exc}\n앱을 다시 실행해 주세요.")
        return True
    except Exception:
        logging.getLogger("mabinogi_addon").info(
            "실행 전 업데이트 생략(실패/무시)", exc_info=True
        )
        return False
