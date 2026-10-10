"""단일 인스턴스 가드.

앱이 두 번 떠서 트레이 아이콘이 둘이 되는 걸 막는다(같은 버전 중복 실행 방지).
QSharedMemory(QtCore) 한 조각을 만들어, 두 번째 인스턴스는 생성 실패로 '이미 실행 중'
임을 알고 조용히 종료한다. QtNetwork 없이 QtCore만 쓰므로 배포본 번들 걱정이 없다.

주의: 가드가 **양쪽 다** 있어야 효과가 있다. 가드가 없던 구버전과 새 버전이 동시에
뜨는 경우(옛 자동실행 잔재 등)는 이걸로 못 막는다 — 그건 autostart 잔재 정리로 해결.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("mabinogi_addon.single")
_KEY = "StarlineMabinogiAddon.singleton"


class SingleInstance:
    """QSharedMemory 기반 단일 인스턴스 판정. 인스턴스를 살려 두는 동안만 유효하므로
    (가비지 컬렉션되면 세그먼트가 풀린다) 호출 측이 참조를 보관해야 한다."""

    def __init__(self, key: str = _KEY) -> None:
        from PySide6.QtCore import QSharedMemory

        self._shm = QSharedMemory(key)
        # 비정상 종료로 세그먼트가 남았을 수 있다(주로 비-Windows). attach가 되면
        # 떼었다가 create로 '진짜 실행 중'인지 판정한다. Windows는 소유 프로세스가
        # 죽으면 세그먼트가 자동 해제돼 이 과정이 사실상 불필요하지만 무해하다.
        if self._shm.attach():
            self._shm.detach()
        self.already_running = not self._shm.create(1)
        if self.already_running:
            _log.info("이미 실행 중인 인스턴스 감지 → 이 인스턴스는 종료")
