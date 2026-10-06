"""파티 폴링 워커 (백그라운드 스레드).

주기적으로 거뿔 API를 읽어 현황판 리스트와 키워드 알림을 시그널로 내보낸다.
UI 스레드를 막지 않도록 QThread에서 돈다. 네트워크/파싱은 도메인 모듈에 위임.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal

from .alerts import AlertState
from .client import fetch_horn_bugle
from .service import build_board, find_alerts


class PartyWorker(QThread):
    updated = Signal(list)  # list[Recruit] — 현황판 갱신
    alerted = Signal(str, object)  # (keyword, Recruit) — 토스트
    status = Signal(str)  # 상태/오류 문구

    def __init__(
        self,
        get_api_key: Callable[[], str | None],
        get_keywords: Callable[[], list[str]],
        get_excludes: Callable[[], list[str]],
        *,
        poll_sec: int = 10,
        list_size: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._get_api_key = get_api_key
        self._get_keywords = get_keywords
        self._get_excludes = get_excludes
        self._poll_sec = poll_sec
        self._list_size = list_size
        self._alert_state = AlertState()
        self._running = True

    def run(self) -> None:
        while self._running:
            self._poll_once()
            # poll_sec 동안 대기하되, 중지 요청이 오면 즉시 깬다
            self.msleep(0)
            for _ in range(self._poll_sec * 10):
                if not self._running:
                    break
                self.msleep(100)

    def _poll_once(self) -> None:
        api_key = self._get_api_key()
        if not api_key:
            self.status.emit("넥슨 API 키가 없습니다. .env의 NEXON_API_KEY를 설정하세요.")
            return
        try:
            raw = fetch_horn_bugle(api_key)
        except Exception as error:  # noqa: BLE001 — 폴링은 어떤 오류에도 계속 돈다
            self.status.emit(f"거뿔 조회 실패: {error}")
            return

        excludes = self._get_excludes()
        self.updated.emit(build_board(raw, excludes, self._list_size))
        self.status.emit("")  # 정상 → 상태 문구 비움

        for keyword, recruit in find_alerts(
            raw, self._get_keywords(), excludes, self._alert_state
        ):
            self.alerted.emit(keyword, recruit)

    def stop(self) -> None:
        self._running = False
