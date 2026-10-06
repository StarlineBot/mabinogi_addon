"""파티 폴링 워커 (백그라운드 스레드).

주기적으로 거뿔 API를 읽어 현황판 리스트와 키워드 알림을 시그널로 내보낸다.
UI 스레드를 막지 않도록 QThread에서 돈다. 네트워크/파싱은 도메인 모듈에 위임.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal

from .alerts import AlertState
from .client import fetch_horn_bugle
from .service import find_alerts


class PartyWorker(QThread):
    updated = Signal(list)  # list[dict] — 거뿔 원본(UI가 제외 적용/재필터)
    alerted = Signal(str, object)  # (keyword, Recruit) — 토스트
    status = Signal(str)  # 상태/오류 문구

    def __init__(
        self,
        get_api_key: Callable[[], str | None],
        get_keywords: Callable[[], list[str]],
        get_excludes: Callable[[], list[str]],
        *,
        poll_sec: int = 5,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._get_api_key = get_api_key
        self._get_keywords = get_keywords
        self._get_excludes = get_excludes
        self._poll_sec = poll_sec
        self._alert_state = AlertState()
        self._running = True
        self._primed = False  # 첫 폴링은 토스트 억제(기존 모집을 '이미 봄'으로 기억)

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

        self.updated.emit(raw)  # UI가 현재 제외 목록으로 즉시 재필터
        self.status.emit("")  # 정상 → 상태 문구 비움

        hits = find_alerts(
            raw, self._get_keywords(), self._get_excludes(), self._alert_state
        )
        # 첫 폴링은 지금 떠 있는 모집을 '이미 봄'으로만 기록하고 토스트는 띄우지 않는다.
        # (앱 켤 때 최근 몇 분치가 한꺼번에 뜨는 것 방지 → 그 뒤 새로 올라온 것만 알림)
        if not self._primed:
            self._primed = True
            return
        for keyword, recruit in hits:
            self.alerted.emit(keyword, recruit)

    def stop(self) -> None:
        self._running = False
