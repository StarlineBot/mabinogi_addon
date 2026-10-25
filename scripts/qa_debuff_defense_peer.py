"""디버프 오인 재현: '물리 방어력 보호 감소'가 걸렸는데 '마법 방어력 보호 감소'도 걸린 것처럼(오버레이에서 사라짐) 보임(사용자 2026-10-25).

실행: uv run python -m scripts.qa_debuff_defense_peer
두 아이콘은 테두리·보라 배경·파란 아래 화살표가 같고 검/지팡이만 다르다. 16px로 줄이면 서로의 점수가 감지 임계(0.68) 근처·위로 올라간다.
- 실제 화면(tests/data 2026-10-15 스크린샷)의 마법 아이콘: 마법 0.94 / 물리 0.66(감지 0.68 바로 아래, 해제 0.58 위 = 이력 유지 구간).
- 물리 아이콘 모형(원본 28px → 16px 축소, 실제 화면 표본 없음): 물리 1.0 / 마법 0.77 → 마법도 '걸림'.
- 같은 무늬 쌍 구분(_IDENTITY_PEERS, 프라가라흐 물리/마법에 이미 쓰는 방식)을 이 쌍에 넣으면 해소되는지 비교한다.
재현되면 REPRODUCED, 종료 코드 1.
"""
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from mabinogi_addon import image_io  # noqa: E402
from mabinogi_addon.tracker import debuff_engine as module  # noqa: E402

P, M = '물리 방어력 보호 감소', '마법 방어력 보호 감소'
ICONS = ROOT / 'src/mabinogi_addon/assets/debuff/icon'
BOX = (1016, 1195, 521, 88)


def patches(templates):
    out = {}
    for key in (P, M):
        small = module._variant(templates[key], module._MATCH_ICON_PX)
        out[f'{key} 모형'] = cv2.copyMakeBorder(small, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=(20, 20, 20))
    frame = image_io.imread(ROOT / 'tests/data/스크린샷 2026-10-15 213313.png')
    x, y = BOX[0] + 7, BOX[1] + 17
    out[f'{M} 실제 화면'] = frame[y:y + 16, x:x + 16]
    return out


def judge(label, templates):
    wrong = []
    for name, region in patches(templates).items():
        engine = module.DebuffEngine(templates, [P, M])  # 패치마다 새 엔진(이력 임계 상태가 섞이지 않게)
        detected = {key: engine._detect(region, key) for key in (P, M)}
        truth = P if name.startswith(P) else M
        bad = [key for key, on in detected.items() if on and key != truth] + [truth] * (not detected[truth])
        print(f'[{label}] {name}: 점수 {dict((k, round(v, 3)) for k, v in engine.best_scores(region).items())} '
              f'· 걸림 판정 {[k for k, on in detected.items() if on]}' + (f' · 오판 {bad}' if bad else ''))
        wrong += bad
    return wrong


if __name__ == '__main__':
    templates = {key: image_io.imread(ICONS / f'{key}.png') for key in (P, M)}
    now = judge('현재', templates)
    peers = dict(module._IDENTITY_PEERS)
    module._IDENTITY_PEERS.update({P: M, M: P})
    after = judge('쌍 구분 추가', templates)
    module._IDENTITY_PEERS.clear(); module._IDENTITY_PEERS.update(peers)
    print('REPRODUCED: 물리 아이콘에 마법도 걸림으로 판정' if now else 'not reproduced',
          '· 쌍 구분 추가 시', '해소' if not after else f'남음 {after}')
    sys.exit(1 if now else 0)
