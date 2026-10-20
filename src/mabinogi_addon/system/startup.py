"""Own the existing bootloader screen; Qt fallback is only for source runs."""

from __future__ import annotations

import logging

_log = logging.getLogger("mabinogi_addon.startup")


class StartupScreen:
    def __init__(self) -> None:
        self._bridge = None
        self._fallback = None
        self._closed = False
        try:
            import pyi_splash

            if pyi_splash.is_alive():
                self._bridge = pyi_splash
        except ImportError:
            pass  # Source run, without a bootloader.
        except Exception:
            _log.info("시작 화면 연결 실패(앱 시작 계속)", exc_info=True)

    def configure(self, *, start_in_tray: bool) -> None:
        if start_in_tray:
            self.close()
            return
        if self._closed or self._bridge is not None or self._fallback is not None:
            return
        from mabinogi_addon import paths

        if paths.is_frozen():
            # Never replace a failed/closed bootloader screen with a second window.
            return
        try:
            from mabinogi_addon.ui.splash import Splash

            self._fallback = Splash()
            self._fallback.center_on_screen()
            self._fallback.show()
        except Exception:
            _log.info("개발용 시작 화면 표시 실패(앱 시작 계속)", exc_info=True)
            if self._fallback is not None:
                try:
                    self._fallback.close()
                except Exception:
                    _log.info("개발용 시작 화면 정리 실패(무시)", exc_info=True)
                self._fallback = None

    def step(self, pct: int, msg: str | None = None) -> None:
        """Keep the existing dialogue on internal stages; statuses are immediate."""
        if self._closed:
            return
        try:
            if self._bridge is not None:
                self._bridge.update_text("@status:" + msg if msg else "@resume")
            elif self._fallback is not None:
                self._fallback.step(pct, msg)
        except Exception:
            _log.info("시작 화면 갱신 실패(앱 시작 계속)", exc_info=True)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for screen in (self._bridge, self._fallback):
            if screen is not None:
                try:
                    screen.close()
                except Exception:
                    _log.info("시작 화면 정리 실패(앱 종료 계속)", exc_info=True)
