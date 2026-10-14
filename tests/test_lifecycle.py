"""프로세스 수명주기 회귀 — 네이티브 abort(rc=134)가 나지 않는지 '서브프로세스'로 검증.

실행 중인 QThread가 파괴되면 Qt가 프로세스를 통째로 abort시킨다(파이썬 예외가 아님).
인프로세스 테스트로는 pytest까지 같이 죽어 못 잡으므로, 각 시나리오를 **별도 파이썬
프로세스**로 돌려 returncode==0(정상 종료)인지 본다.

핵심: abort는 '컨트롤러를 버린 순간'이 아니라 **막힌 grab이 끝나 워커가 실제로 종료되는
순간**(=실행 중 QThread 파괴 시점)에 난다. 그래서 각 시나리오는 그 시점을 지나도록
막힌 시간보다 길게 이벤트 루프를 돌린 뒤 종료한다 — 그래야 '없어진 버그'가 아니라 '있는
버그'를 잡는다(구버전 buff_controller로 바꾸면 이 테스트들이 abort로 실패함을 확인했다).

시나리오:
1. 재시작 크래시 회귀 — grab이 막혀 stop()이 타임아웃된 워커를 좀비로 보관한 뒤
   컨트롤러를 버리고 gc해도, 막힌 grab이 끝날 때 abort하지 않는다(_ZOMBIES가 참조 유지,
   finished에서 안전 수거).
2. 틱 예외 생존 — engine.tick이 매번 예외를 던져도 워커가 틱을 격리해 앱이 산다.
3. 종료 abort 없음 — 막힌 캡처 워커가 있는 상태로 MainWindow.closeEvent를 실제로 타도
   종료코드 0(정지 신호 후 os._exit로 teardown abort 차단).
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
from PySide6.QtCore import QTimer
from mabinogi_addon.ui.buff_controller import BuffController

app = QApplication([])

def run_loop(ms):  # 이벤트 루프를 ms만큼 돌린다(막힌 워커가 끝나 파괴되는 시점을 지나도록).
    QTimer.singleShot(ms, app.quit)
    app.exec()

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

class BlockSrc:  # grab이 1초 막힘(포커스 아웃 중 dxcam 블록 흉내)
    def grab(self): time.sleep(1.0); return None
    def close(self): pass

class FrameSrc:  # grab이 바로 프레임을 돌려줌
    def grab(self): return np.zeros((20, 20, 3), np.uint8)
    def close(self): pass

def make_ctrl():
    return BuffController(FakeOverlay(), {}, {}, watcher=FakeWatcher())
"""

# MainWindow(실제 종료 경로)용 머리말: config를 임시 파일로 돌려 devdata를 안 건드린다.
_MW_PREAMBLE = """
import os, time, json, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
_tmp = Path(tempfile.mkdtemp()) / "c.json"
_tmp.write_text("{}")
config._read_local_config = lambda path=None: json.loads(_tmp.read_text())
config._write_local_config = (
    lambda data, path=None: _tmp.write_text(json.dumps(data, ensure_ascii=False))
)

app = QApplication([])
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui.buff_controller import BuffController

class _R:
    entries = []; alerts = []; alerts2 = []

class OkEngine:
    def tick(self, region, now, foreground=True, bar_region=None): return _R()

class BlockSrc:
    def grab(self): time.sleep(3); return None
    def close(self): pass

class FakeOverlay:
    locked = True
    def set_items(self, *a): pass
    def show(self): pass
    def hide(self): pass
    def close(self): pass

class FakeWatcher:
    def is_game_active(self): return True
    def is_self_active(self): return False
"""

_SCENARIOS = {
    # 1) 재시작 크래시: 막힌 워커 → stop 타임아웃 → 좀비 → 컨트롤러 버리고 gc → 막힌 grab이
    #    끝나 워커가 파괴되는 시점(약 1초)을 지나도록 루프를 돌려도 abort 없어야.
    "restart_drop": _PREAMBLE + """
ctrl = make_ctrl()
ctrl.start(BlockSrc(), OkEngine(), interval_ms=10)
time.sleep(0.3)                 # 워커가 grab(1초)에 진입
ctrl.stop(timeout_ms=300)       # 타임아웃 → 좀비로 보관
ctrl = None; gc.collect()       # 컨트롤러 버림(구버전은 여기 워커가 컨트롤러에만 매달림)
run_loop(1800)                  # 막힌 grab 종료(≈1초) 시점 통과 — 실행 중 QThread 파괴 순간
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
    # 3) 종료 abort 없음: 막힌 캡처 워커가 있는 채로 '실제 MainWindow.closeEvent'를 탄다.
    #    closeEvent가 정지 신호 후 os._exit(0) → rc 0. stop()이 막힌 워커를 파괴하면 그 전에
    #    abort(rc=134). closeEvent에 도달만 하고 os._exit를 못 부르면 rc 99(드러나게).
    "shutdown_blocked": _MW_PREAMBLE + """
w = MainWindow()
# 막힌 캡처 워커를 가진 컨트롤러를 주입 — closeEvent가 이걸 request_stop/stop 하며 탄다.
# (컨트롤러는 실제 소스가 있어야 생겨 평소 lazy 생성이므로, 종료 경로 검증용으로 직접 주입.)
ctrl = BuffController(FakeOverlay(), {}, {}, watcher=FakeWatcher())
ctrl.start(BlockSrc(), OkEngine(), interval_ms=10)
w.buff_controller = ctrl
time.sleep(0.3)                 # 워커가 grab(막힘)에 진입
w._force_quit = True            # 트레이 최소화 건너뛰고 완전 종료 경로로
w.close()                       # closeEvent → 정지(막힌 워커→좀비) → os._exit(0)
os._exit(99)                    # 여기 오면 os._exit(0)가 안 불린 것 — 실패로 표시
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
    # rc 0 = 정상. rc -6/134 = abort(QThread 파괴 등). rc 99 = 종료 경로 미도달. 스택은 stderr.
    assert proc.returncode == 0, (
        f"[{name}] returncode={proc.returncode}\n--- stderr ---\n{proc.stderr[-2000:]}"
    )
