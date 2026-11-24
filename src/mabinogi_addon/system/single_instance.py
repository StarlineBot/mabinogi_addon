"""단일 인스턴스 가드.

앱이 두 번 떠서 트레이 아이콘이 둘이 되는 걸 막는다(같은 버전 중복 실행 방지).
QSharedMemory(QtCore) 한 조각을 만들어, 두 번째 인스턴스는 생성 실패로 '이미 실행 중'
임을 안다. QtNetwork 없이 QtCore만 쓰므로 배포본 번들 걱정이 없다.

0.55.8(사용자 11-24): 두 번째 실행은 조용히 꺼지지 않고, 같은 조각 첫 바이트에 '보여 줘' 표시를
남긴 뒤 종료한다(request_show). 첫 인스턴스는 0.5초 QTimer로 그 한 바이트만 보고 메인 창을
앞으로 꺼낸다(watch). 업데이트·다시 켜기로 새 exe를 띄우기 직전엔 release()로 자리를 먼저 비운다.

주의: 가드가 **양쪽 다** 있어야 효과가 있다. 가드가 없던 구버전과 새 버전이 동시에
뜨는 경우(옛 자동실행 잔재 등)는 이걸로 못 막는다 — 그건 autostart 잔재 정리로 해결.
"""

from __future__ import annotations

import logging
import time

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
        else:
            self._write(0)
        self._timer = None

    def _write(self, value: int) -> None:
        if self._shm.lock():
            try:
                memoryview(self._shm.data())[0] = value
            finally:
                self._shm.unlock()

    def take_show_request(self) -> bool:
        """두 번째 실행이 남긴 '보여 줘' 표시를 읽고 지운다(있었으면 True)."""
        if self.already_running or not self._shm.isAttached() or not self._shm.lock():
            return False
        try:
            data = memoryview(self._shm.data())
            asked = data[0] != 0
            if asked:
                data[0] = 0
            return asked
        finally:
            self._shm.unlock()

    def watch(self, on_show, interval_ms: int = 500) -> None:
        """'보여 줘' 표시를 interval_ms마다 본다(한 바이트 읽기). 로딩 중 들어온 요청은 시작할 때 한 번 반영."""
        from PySide6.QtCore import QTimer

        def tick() -> None:
            if self.take_show_request():
                _log.info("다시 실행 감지 — 메인 창 앞으로")
                on_show()

        self._timer = QTimer()
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(tick)
        self._timer.start()
        tick()

    def release(self) -> None:
        """자리를 비운다(새 exe를 띄우기 직전 — 새 프로세스가 기다리지 않고 자리를 잡게).

        앱 안 업데이트는 작업 스레드에서 부르므로 타이머는 건드리지 않는다(다른 스레드에서 멈출 수 없음) —
        비운 뒤의 tick은 take_show_request가 바로 False를 돌려 아무것도 안 한다."""
        if self._shm.isAttached():
            self._shm.detach()


_held: SingleInstance | None = None


def release_held() -> None:
    """이 프로세스가 잡은 자리를 비운다(없으면 아무것도 안 함). 업데이트·다시 켜기 재실행 직전에 부른다."""
    global _held
    guard, _held = _held, None
    if guard is not None:
        try:
            guard.release()
        except Exception:  # noqa: BLE001 — 못 비워도 새 프로세스가 RESTART_WAIT 동안 기다린다
            _log.info("단일 인스턴스 자리 비우기 실패(무시)", exc_info=True)


def request_show(key: str = _KEY) -> bool:
    """이미 켜진 인스턴스에 '메인 창 보여 줘'를 남긴다. 남겼으면 True."""
    from PySide6.QtCore import QSharedMemory

    _allow_foreground()
    shm = QSharedMemory(key)
    if not shm.attach():
        return False
    try:
        if not shm.lock():
            return False
        try:
            memoryview(shm.data())[0] = 1
        finally:
            shm.unlock()
        _log.info("이미 실행 중 — 기존 창 앞으로 요청")
        return True
    finally:
        shm.detach()


def _allow_foreground() -> None:
    """Windows는 백그라운드 프로세스의 창 앞으로 가져오기를 막는다. 방금 사용자가 실행한
    이 프로세스가 가진 권한을 아무 프로세스에나 넘겨(ASFW_ANY) 첫 인스턴스가 앞으로 나올 수 있게 한다."""
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except Exception:  # noqa: BLE001 — 실패하면 작업 표시줄 깜빡임으로만 보인다
        _log.info("AllowSetForegroundWindow 실패(무시)", exc_info=True)


def acquire(*, wait: float = 0.0, key: str = _KEY, interval: float = 0.25,
            clock=time.monotonic, sleep=time.sleep) -> SingleInstance | None:
    """단일 인스턴스 자리를 잡는다. 잡으면 그 가드(참조 보관 필요), 못 잡으면 None.

    wait=0(평소 두 번째 실행) → 한 번만 보고 바로 포기. 다시 켜기(설정 초기화·가져오기·불러오기 뒤,
    0.46.0)는 옛 프로세스가 정리하고 끝날 때까지 wait초 동안 다시 시도한다.
    """
    global _held
    deadline = clock() + wait
    while True:
        guard = SingleInstance(key)
        if not guard.already_running:
            _held = guard
            return guard
        if clock() >= deadline:
            return None
        sleep(interval)
