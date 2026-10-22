"""0.11.4 RSS '재연결 후 확인' 경로 재현: 저장값과 실행값이 분리된 NIC 모형.

실행: uv run python -m scripts.qa_0114_rss_prepared_restore
- 정상 흐름(적용 → 재연결 → 원복 → 재연결)은 한 번에 원본 복귀해야 한다.
- 재연결 전 원복(적용 직후 재연결이 보류·중단된 경우): 실행값은 아직 원본이라 restore()가 원본을
  다시 쓰지 않고 'restored'로 표시하면, 재연결 때 저장값(적용값)이 반영돼 원복 확인이 실패한다.
  한 번의 원복으로 원본 복귀하지 못하면 REPRODUCED, 종료 코드 1.
Windows 장치 없이 앱의 실제 Recovery와 rss_plan·validate만 사용한다(NIC 반영 규칙은 모형).
"""
import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from mabinogi_addon.optimization.session import Core, Recovery, Topology  # noqa: E402
from mabinogi_addon.system.optimization import WindowsOptimization  # noqa: E402

GUID = '12345678-1234-1234-1234-123456789abc'
ORIGINAL = dict(Enabled=True, BaseProcessorGroup=0, BaseProcessorNumber=0, MaxProcessorGroup=0,
                MaxProcessorNumber=14, MaxProcessors=8, NumberOfReceiveQueues=8, Profile='NUMAStatic')


class NoRestartNic(WindowsOptimization):
    """-NoRestart 쓰기는 저장값만 바꾸고, 조회는 실행값을 돌려준다. 재시작해야 저장값이 실행값이 된다."""

    def __init__(self):
        super().__init__()
        self.stored = copy.deepcopy(ORIGINAL)
        self.running = copy.deepcopy(ORIGINAL)

    def read(self, kind, target):
        assert kind == 'rss'
        return copy.deepcopy(self.running)

    def write(self, kind, target, value, *, guard=None):
        self.validate(kind, target, value)
        self.stored = copy.deepcopy(value)

    def restart_network(self, target, *, guard=None):
        self.running = copy.deepcopy(self.stored)


def _plan(nic):
    topology = Topology('AMD Ryzen 7 9800X3D', tuple(Core(i, (i * 2, i * 2 + 1)) for i in range(8)))
    return nic.rss_plan(GUID, topology.plan(7)['background_cores'])


def _restore_once(recovery):
    errors = recovery.restore(network=True)
    try:
        recovery.flush_network(verify_restored=True)
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    return errors


def normal_flow():
    nic = NoRestartNic()
    with tempfile.TemporaryDirectory() as folder:
        recovery = Recovery(Path(folder) / 'recovery.json', nic, lambda: True)
        result = recovery.apply('rss', GUID, _plan(nic))
        recovery.flush_network()
        state = recovery.items[0]['state']
        errors = _restore_once(recovery)
    ok = result == 'written' and state == 'applied' and not errors and nic.stored == nic.running == ORIGINAL
    print(f'[정상] apply={result} 재연결 후 상태={state} 원복 오류={errors or "없음"} 원본 복귀={nic.running == ORIGINAL}')
    return not ok


def restore_before_restart():
    nic = NoRestartNic()
    with tempfile.TemporaryDirectory() as folder:
        recovery = Recovery(Path(folder) / 'recovery.json', nic, lambda: True)
        recovery.apply('rss', GUID, _plan(nic))  # 재연결 전에 세션이 끝난 경우(보류·중단·앱 종료)
        first = _restore_once(recovery)
        after_first = nic.running == ORIGINAL and nic.stored == ORIGINAL
        second = _restore_once(recovery) if not after_first else []
        after_second = nic.running == ORIGINAL and nic.stored == ORIGINAL
    print(f'[재연결 전 원복] 1회차 오류={first or "없음"} / 1회차 원본 복귀={after_first}')
    if not after_first:
        print(f'[재연결 전 원복] 2회차 오류={second or "없음"} / 2회차 원본 복귀={after_second}')
    reproduced = not after_first
    print('[재연결 전 원복]', 'REPRODUCED: 1회 원복으로 원본에 돌아가지 못함(실행값만 보고 쓰기 생략)'
          if reproduced else 'not reproduced')
    return reproduced


if __name__ == '__main__':
    results = [normal_flow(), restore_before_restart()]
    sys.exit(1 if any(results) else 0)
