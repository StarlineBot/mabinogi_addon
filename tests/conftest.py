"""테스트 공통 설정 + 누수 QThread 사전 검출.

앱이 종료·재시작할 때 '실행 중인 QThread'가 남아 파괴되면 Qt가 프로세스를 abort(rc=134)시킨다.
테스트도 똑같이 — 워커를 정리하지 않고 끝내면 프로세스 teardown에서 같은 abort가 난다
(pytest는 'passed'를 찍은 뒤 rc=134로 죽어, CI·릴리즈 게이트에서야 드러난다).

그래서 **각 테스트가 끝날 때 실행 중인 QThread가 있으면 그 테스트를 실패**시켜, 워커 정리
누락을 그 자리에서 잡는다(앱의 실제 종료 크래시와 같은 뿌리). 테스트는 끝에 컨트롤러.stop()
/ stop_polling() / 창.close() 등으로 워커를 정리해야 한다.
"""

from __future__ import annotations

import gc

import pytest


def _running_qthreads() -> list[str]:
    try:
        from PySide6.QtCore import QThread
    except Exception:  # noqa: BLE001 — Qt 없으면 검사 불가(그냥 통과)
        return []
    gc.collect()
    names: list[str] = []
    for obj in gc.get_objects():
        if isinstance(obj, QThread):
            try:
                if obj.isRunning():
                    names.append(type(obj).__name__)
            except Exception:  # noqa: BLE001 — 이미 파괴된 래퍼 등은 건너뜀
                pass
    return names


@pytest.fixture(autouse=True)
def _no_leaked_qthreads():
    """테스트 종료 시 실행 중인 QThread가 남아 있으면 실패(이름 표시)."""
    yield
    leaked = _running_qthreads()
    assert not leaked, (
        f"테스트가 실행 중인 QThread를 정리하지 않았습니다: {leaked} "
        "(끝에서 워커를 stop()/close() 하세요 — 안 하면 종료 시 abort rc=134)"
    )
