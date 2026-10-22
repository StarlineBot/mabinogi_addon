"""0.11.1 라이브 제보 재현: RSS 복구 잠김, 블랙박스 1440p 입력 중단, 단축키 표시.

실행: uv run python -m scripts.qa_live_0111_rss_blackbox
예상(미수정 상태): 세 항목 모두 'REPRODUCED'를 출력하고 종료 코드 1.
Windows 장치/게임 없이 앱의 실제 Recovery·rss_plan·제품 설정·표시 형식만 사용한다.
RSS 정규화 모형은 사용자 화면의 값(원본 MaxProcessorNumber 14/MaxProcessors 8,
현재 14/1, 적용 15/2)에 맞춘 가설이다: Windows RSS가 SMT 형제(홀수 논리 CPU)를 쓰지 않는다.
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from mabinogi_addon.optimization.session import Core, Recovery, Topology  # noqa: E402
from mabinogi_addon.system.optimization import WindowsOptimization  # noqa: E402

GUID = '12345678-1234-1234-1234-123456789abc'
ORIGINAL = dict(Enabled=True, BaseProcessorGroup=0, BaseProcessorNumber=0, MaxProcessorGroup=0,
                MaxProcessorNumber=14, MaxProcessors=8, NumberOfReceiveQueues=8, Profile='NUMAStatic')


class SmtNormalizingNic(WindowsOptimization):
    """쓰기 직후 조회는 쓴 값 그대로, 어댑터 재시작 후에는 짝수 논리 CPU만 남는 장치 모형."""

    def __init__(self):
        super().__init__()
        self.value = copy.deepcopy(ORIGINAL)

    def read(self, kind, target):
        assert kind == 'rss'
        return copy.deepcopy(self.value)

    def write(self, kind, target, value, *, guard=None):
        self.validate(kind, target, value)
        self.value = copy.deepcopy(value)

    def restart_network(self, target, *, guard=None):
        v = self.value
        evens = [n for n in range(v['BaseProcessorNumber'], v['MaxProcessorNumber'] + 1) if n % 2 == 0]
        v['MaxProcessorNumber'] = max(evens)
        v['MaxProcessors'] = min(v['MaxProcessors'], len(evens))


def _locked(nic, plan, folder, *, legacy=False):
    """적용 → 재시작(정규화) → 원복 시도. 사용자가 풀 수 없는 잠김이면 True."""
    recovery = Recovery(Path(folder) / 'recovery.json', nic, lambda: True)
    recovery.apply('rss', GUID, plan)
    recovery.flush_network()
    # Engine.restore_network와 같은 순서: 원복 → 재연결 후 원본 확인.
    errors = recovery.restore(network=True)
    recovery.flush_network(verify_restored=True)
    if recovery.pending and recovery.normalized_review:
        # 앱이 제공하는 해소 경로: 사용자 확인 후 원본 재기록 → 재연결 후 원본 확인.
        errors = recovery.restore(network=True, accept_normalized=True)
        recovery.flush_network(verify_restored=True)
    try:
        recovery.finish()
        start_blocked = False
    except RuntimeError:
        start_blocked = True
    restored = nic.value == ORIGINAL
    tag = '기존 기록(15/2)' if legacy else '현재 계획'
    print(f'[RSS] {tag} 원복 결과:', errors or '정상', '/ 원본 복귀:', restored, '/ 시작 차단:', start_blocked)
    return start_blocked or not restored


def rss_deadlock():
    # 엔진과 같은 경로: 9800X3D 7+1 → 백그라운드 물리 코어 7(논리 14,15) 묶음으로 계획.
    topology = Topology('AMD Ryzen 7 9800X3D', tuple(Core(i, (i * 2, i * 2 + 1)) for i in range(8)))
    cores = topology.plan(7)['background_cores']
    nic = SmtNormalizingNic()
    plan = nic.rss_plan(GUID, cores)
    print('[RSS] 적용 계획:', {k: plan[k] for k in ('BaseProcessorNumber', 'MaxProcessorNumber', 'MaxProcessors')})
    with tempfile.TemporaryDirectory() as folder:
        current = _locked(nic, plan, folder)
    # 0.11.1 사용자에게 이미 남은 기록: SMT 형제 포함 14~15/2개를 쓴 뒤 장치가 14/1로 줄인 상태.
    nic = SmtNormalizingNic()
    legacy_plan = dict(nic.read('rss', GUID), Enabled=True, BaseProcessorNumber=14, MaxProcessorNumber=15,
                       MaxProcessors=2, Profile='ClosestStatic')
    with tempfile.TemporaryDirectory() as folder:
        legacy = _locked(nic, legacy_plan, folder, legacy=True)
    reproduced = current or legacy
    print('[RSS]', 'REPRODUCED: 원복 보류 + 새 시작 차단(사용자 해소 경로 없음)' if reproduced else 'not reproduced')
    return reproduced


def blackbox_input_limit():
    product = json.loads((Path(__file__).resolve().parents[1] / 'packaging' / 'blackbox-product.json')
                         .read_text(encoding='utf-8'))
    limit = product['producer']['max_frame_bytes']
    need = 2560 * 1440 * 4  # 기획서 12.1 실측 게임창
    reproduced = need > limit
    print(f'[블랙박스] 2560×1440 프레임 {need} bytes, 제품 한도 {limit} bytes '
          f"(max {product['producer']['max_width']}×{product['producer']['max_height']})")
    print('[블랙박스]', 'REPRODUCED: 사용자 해상도에서 녹화 시작 즉시 중단' if reproduced else 'not reproduced')
    return reproduced


def hotkey_label():
    product = json.loads((Path(__file__).resolve().parents[1] / 'packaging' / 'blackbox-product.json')
                         .read_text(encoding='utf-8'))
    from mabinogi_addon.ui.blackbox_controller import hotkey_text  # 제품 화면 표시 함수
    label = hotkey_text(product['hotkey_modifiers'], product['hotkey_vk'])
    reproduced = label.startswith('VK ') or '0x' in label
    print(f"[단축키] 설정 vk={product['hotkey_vk']}(F10) → 화면 표시 '{label}'")
    print('[단축키]', 'REPRODUCED: 키 코드로 표시돼 사용자가 실제 키를 알 수 없음' if reproduced else 'not reproduced')
    return reproduced


if __name__ == '__main__':
    results = [rss_deadlock(), blackbox_input_limit(), hotkey_label()]
    sys.exit(1 if any(results) else 0)
