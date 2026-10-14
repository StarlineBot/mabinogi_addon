"""프로세스 수명주기 회귀 — 네이티브 abort(rc=134)가 나지 않는지 '서브프로세스'로 검증.

실행 중인 QThread 파괴·슬롯 예외 전파 등은 파이썬 예외가 아니라 프로세스를 통째로
abort시킨다. 인프로세스 테스트로는 pytest까지 같이 죽어 못 잡으므로, 각 시나리오를
**별도 파이썬 프로세스**로 돌려 returncode==0(정상 종료)인지 본다.

시나리오:
1. 재시작 크래시 회귀 — grab이 막혀 stop()이 타임아웃된 워커를 좀비로 보관한 뒤
   컨트롤러를 버리고 gc해도 abort하지 않는다(모듈 전역 _ZOMBIES가 참조 유지).
2. 틱 예외 생존 — engine.tick이 매번 예외를 던져도 워커가 틱을 격리해 앱이 산다.
3. 종료 abort 없음 — grab이 막힌 워커가 있어도 종료(정지 시도 후 os._exit)가 rc 0.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

# 서브프로세스 스크립트 공통 머리말: Qt + 가짜 의존(오버레이·엔진·소스)으로 BuffController를
# 최소 구성한다. 가짜는 BuffController/_TrackWorker가 실제로 부르는 메서드만 둔다.
_PREAMBLE = """
import os, time, gc, numpy as np
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from mabinogi_addon.ui.buff_controller import BuffController

app = QApplication([])

class FakeOverlay:
    locked = True
    def set_items(self, *a): pass
    def show(self): pass
    def hide(self): pass

class FakeWatcher:
    def is_game_active(self): return True
    def is_self_active(self): return False

class _R:
    entries = []; alerts = []; alerts2 = []

class OkEngine:
    def tick(self, region, now, foreground=True, bar_region=None): return _R()

class ThrowEngine:
    def tick(self, *a, **k): raise RuntimeError("boom in tick")

class BlockSrc:  # grab이 3초 막힘(포커스 아웃 중 dxcam 블록 흉내)
    def grab(self): time.sleep(3); return None
    def close(self): pass

class FrameSrc:  # grab이 바로 프레임을 돌려줌
    def grab(self): return np.zeros((20, 20, 3), np.uint8)
    def close(self): pass

def make_ctrl():
    return BuffController(FakeOverlay(), {}, {}, watcher=FakeWatcher())
"""

_SCENARIOS = {
    # 1) 재시작 크래시: 막힌 워커 → stop 타임아웃 → 좀비 → 컨트롤러 버리고 gc → abort 없어야.
    "restart_drop": _PREAMBLE + """
ctrl = make_ctrl()
ctrl.start(BlockSrc(), OkEngine(), interval_ms=10)
time.sleep(0.3)                 # 워커가 grab(3초)에 진입
ctrl.stop(timeout_ms=300)       # 타임아웃 → 좀비로 보관
ctrl = None; gc.collect()       # 컨트롤러 버림 — 여기서 실행 중 QThread가 파괴되면 abort
print("SURVIVED")
os._exit(0)
""",
    # 2) 틱 예외 생존: tick이 매 틱 예외를 던져도 워커가 격리 → 앱 생존.
    "tick_throws": _PREAMBLE + """
ctrl = make_ctrl()
ctrl.start(FrameSrc(), ThrowEngine(), interval_ms=5)
time.sleep(0.4)                 # 수십 틱 — 전부 예외(격리 안 되면 여기서 abort)
ctrl.stop(timeout_ms=1000)      # grab이 빨라 깨끗이 정지
print("SURVIVED")
os._exit(0)
""",
    # 3) 종료 abort 없음: 막힌 워커가 있어도 '정지 시도 후 os._exit(0)'면 rc 0.
    "shutdown_blocked": _PREAMBLE + """
import logging
ctrl = make_ctrl()
ctrl.start(BlockSrc(), OkEngine(), interval_ms=10)
time.sleep(0.3)                 # 워커가 grab(3초)에 막힘
ctrl.stop(timeout_ms=200)       # 짧게 시도(앱 종료 흉내) → 좀비
logging.shutdown()
os._exit(0)                     # 정리 없이 즉시 종료 — teardown abort 원천 차단
""",
}


@pytest.mark.parametrize("name", list(_SCENARIOS))
def test_no_native_abort(name: str):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_SCENARIOS[name])],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # rc 0 = 정상. rc -6/134 = abort(QThread 파괴 등). 스택은 stderr로.
    assert proc.returncode == 0, (
        f"[{name}] returncode={proc.returncode}\n--- stderr ---\n{proc.stderr[-2000:]}"
    )
