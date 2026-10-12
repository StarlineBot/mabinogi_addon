"""디버프 탐지 두 방식 오탐율 비교 벤치.

목적: '보스 없음(빈 바닥·마을)' 영역에서 디버프가 **잘못 걸린 것처럼** 뜨는 오탐을,
      기존 방식(항상 탐지)과 '보스 바 인식(베타)' 방식에서 각각 세어 비교한다.
      → 나중에 예시 이미지가 추가되거나 각 방식이 개선될 때마다 오탐 수를 비교할 수 있다.

라벨(아래 _NO_BOSS_SHOTS / _BOSS_SHOT)은 **실게임 스샷에 디버프가 실제로 안 걸린 장면**을
모은 것이라, 이 영역에서 '걸림'으로 뜨면 전부 오탐이다. 새 이미지를 추가하려면 목록에
파일명만 더하면 된다(실제 보스 체력바가 보이고 디버프가 없는/있는 장면 구분해서).

영역 좌표는 사용자가 쓰는 앵커(보스 체력바 포함, 2560×1440 기준 1017,1210 524×79)를
해상도에 맞춰 스케일한 것(_user_region과 동일 규칙).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from mabinogi_addon.tracker.debuff_engine import DebuffEngine

_SHOTS = Path(__file__).parent / "data"

# 보스 없음(빈 바닥·마을) — 이 영역에서 '걸림'은 전부 오탐. 여기에 이미지만 추가하면 벤치 확장.
_NO_BOSS_SHOTS = [
    "스크린샷 2026-10-06 223724.png",  # 마을
    "스크린샷 2026-10-06 224732.png",  # 풀밭(어두운 녹색)
    "스크린샷 2026-10-12 024008.png",  # 빈 바닥(앱 열린 상태)
    "스크린샷 2026-10-12 024144.png",  # 마을/던전 바닥
]
# 보스 체력바가 보이는 영역(게이팅의 bar_seen 확립용 + 보스일 땐 리셋 안 함 확인용).
_BOSS_SHOT = "스크린샷 2026-10-12 000512.png"


def _real_debuff_templates() -> dict:
    d = Path("src/mabinogi_addon/assets/debuff/icon")
    out = {}
    for name in ("방해 카드", "모모"):
        t = cv2.imread(str(d / f"{name}.png"))
        if t is not None:
            out[name] = t
    return out


def _region(name: str):
    """앵커 영역(보스 체력바 포함)을 해상도에 맞춰 잘라 반환. 파일 없으면 None."""
    im = cv2.imread(str(_SHOTS / name))
    if im is None:
        return None
    h, w = im.shape[:2]
    sx, sy = w / 2560.0, h / 1440.0
    y, x = int(1210 * sy), int(1017 * sx)
    return im[y : y + int(79 * sy), x : x + int(524 * sx)]


def _settle_false_positives(sample, boss, templates, order, *, bar_gating) -> list[str]:
    """'보스 → 바닥' 시나리오를 재현해 바닥에서 '걸림'으로 뜬 디버프(=오탐) 목록.

    실제 상황: 보스전(디버프가 걸려 있을 수 있음) → 보스 이탈/사망(바닥). 두 방식에 **같은
    입력**(보스 프레임 먼저, 그 다음 바닥)을 줘서 공정하게 비교한다(게이팅의 bar_seen도
    이 보스 프레임으로 확립된다).
    """
    eng = DebuffEngine(templates, order, bar_gating=bar_gating)
    now = 0.0
    if boss is not None:
        eng.tick(boss, now=now)  # 보스전(바 인식 + 디버프 걸린 상태 재현)
        now += 0.2
    res = None
    for _ in range(30):  # 디바운스(0.3s)·유예(1.0s)를 넘겨 정착
        res = eng.tick(sample, now=now)
        now += 0.2
    shown = {e.buff_id for e in res.entries}
    return [b for b in order if b not in shown]  # 바닥인데 안 보임 = 걸림 = 오탐


def test_detection_false_positive_benchmark(capsys):
    """두 방식의 '보스 없음' 오탐 수를 재서 비교하고, 새 방식이 더 나쁘지 않음을 보장.

    - 기존(항상 탐지): 바닥 무늬가 템플릿에 매칭되면 그대로 오탐.
    - 보스 바 인식(베타): 확실한 바닥이면 매칭을 멈춰 오탐을 없앤다.
    불변식: 새 방식 오탐 ≤ 기존 오탐(게이팅은 '리셋해 억제'하거나 '유지해 동일'뿐이라
    기존보다 오탐이 늘 수 없다).
    """
    tpl = _real_debuff_templates()
    if len(tpl) < 2:
        pytest.skip("디버프 템플릿 없음")
    order = list(tpl)
    boss = _region(_BOSS_SHOT)
    samples = [(nm, _region(nm)) for nm in _NO_BOSS_SHOTS]
    samples = [(nm, r) for nm, r in samples if r is not None]
    if not samples:
        pytest.skip("보스 없음 샘플 이미지 없음")

    modes = {"기존(항상 탐지)": False, "보스 바 인식(베타)": True}
    totals: dict[str, int] = {}
    lines = ["", "=== 디버프 '보스 없음' 오탐 비교 ==="]
    for mode, gating in modes.items():
        total = 0
        detail = []
        for nm, reg in samples:
            fp = _settle_false_positives(reg, boss, tpl, order, bar_gating=gating)
            total += len(fp)
            detail.append(f"    {nm.split()[-1]:20} 오탐 {len(fp)}개 {fp if fp else ''}")
        totals[mode] = total
        rate = total / (len(samples) * len(order))
        lines.append(f"  [{mode}] 총 오탐 {total}개 / {len(samples)*len(order)} "
                     f"(오탐율 {rate:.0%})")
        lines.extend(detail)
    with capsys.disabled():
        print("\n".join(lines))

    off, on = totals["기존(항상 탐지)"], totals["보스 바 인식(베타)"]
    # 새 방식이 오탐을 늘리지 않는다(핵심 불변식).
    assert on <= off, f"새 방식 오탐({on})이 기존({off})보다 많음"
    # 적어도 하나의 바닥에선 기존 방식이 실제로 오탐을 낸다(벤치가 신호를 갖는지 확인).
    assert off >= 1, "벤치에 오탐 신호가 없음 — 바닥 샘플/템플릿을 점검하세요"
