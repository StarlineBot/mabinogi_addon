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

from mabinogi_addon import image_io
from mabinogi_addon.detect.boss_hp_reader import read_percent, read_percent_cached
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

# 보스 체력바가 '보이는' 장면 모음(재현율 측정용). 게이팅은 이들을 전부 '보스'로 인정해야
# 한다 — 하나라도 놓치면(과소인식) 실제 보스전에서 걸린 디버프를 '안 걸림'으로 잘못
# 되돌려 위험하다. 2색 바·HP 다양 포함. 새 보스 스샷은 여기에 파일명만 더하면 된다.
_BOSS_SHOTS = [
    "스크린샷 2026-10-12 000512.png",
    "스크린샷 2026-10-09 190901.png",
    "스크린샷 2026-10-09 190905.png",
    "스크린샷 2026-10-09 190909.png",
    "스크린샷 2026-10-09 190911.png",
    "스크린샷 2026-10-09 190915.png",
    "스크린샷 2026-10-09 190926.png",
    "스크린샷 2026-10-09 191035.png",
    "스크린샷 2026-10-09 195115.png",
]


def _real_debuff_templates() -> dict:
    d = Path("src/mabinogi_addon/assets/debuff/icon")
    out = {}
    for name in ("방해 카드", "모모"):
        t = image_io.imread(d / f"{name}.png")
        if t is not None:
            out[name] = t
    return out


def _region(name: str):
    """앵커 영역(보스 체력바 포함)을 해상도에 맞춰 잘라 반환. 파일 없으면 None."""
    im = image_io.imread(_SHOTS / name)
    if im is None:
        return None
    h, w = im.shape[:2]
    sx, sy = w / 2560.0, h / 1440.0
    y, x = int(1210 * sy), int(1017 * sx)
    return im[y : y + int(79 * sy), x : x + int(524 * sx)]


def _bar_box(region):
    """앵커 영역에서 '보스 바'에 해당하는 아래쪽 절반을 잘라 3차용 바 영역으로 쓴다.

    실앱에선 사용자가 정렬된 바 영역을 따로 지정하지만, 벤치에선 앵커(위=아이콘/아래=바)
    구조를 이용해 하단 ~절반을 바 박스로 근사한다(read_percent가 이 박스에서 % 판독).
    """
    if region is None:
        return None
    h = region.shape[0]
    return region[int(h * 0.52):, :]


def _settle_false_positives(sample, boss, templates, order, *, gate_mode) -> list[str]:
    """'보스 → 바닥' 시나리오를 재현해 바닥에서 '걸림'으로 뜬 디버프(=오탐) 목록.

    실제 상황: 보스전(디버프가 걸려 있을 수 있음) → 보스 이탈/사망(바닥). 세 방식에 **같은
    입력**(보스 프레임 먼저, 그 다음 바닥)을 줘서 공정하게 비교한다. 3차(percent)에는
    정렬된 바 영역(_bar_box)을 함께 넘긴다.
    """
    eng = DebuffEngine(templates, order, gate_mode=gate_mode)
    now = 0.0
    if boss is not None:
        eng.tick(boss, now=now, bar_region=_bar_box(boss))  # 보스전(바 인식 + 디버프 재현)
        now += 0.2
    res = None
    for _ in range(30):  # 디바운스(0.3s)·유예(1.0s)를 넘겨 정착
        res = eng.tick(sample, now=now, bar_region=_bar_box(sample))
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

    # 1차/2차/3차 비교.
    modes = [
        ("1차 기존(항상 탐지)", "off"),
        ("2차 보스 바 인식(띠)", "band"),
        ("3차 read_percent(바)", "percent"),
    ]
    totals: dict[str, int] = {}
    lines = ["", "=== 디버프 '보스 없음' 오탐 비교 (1차/2차/3차) ==="]
    for label, mode in modes:
        total = 0
        detail = []
        for nm, reg in samples:
            fp = _settle_false_positives(reg, boss, tpl, order, gate_mode=mode)
            total += len(fp)
            detail.append(f"    {nm.split()[-1]:20} 오탐 {len(fp)}개 {fp if fp else ''}")
        totals[label] = total
        rate = total / (len(samples) * len(order))
        lines.append(f"  [{label}] 총 오탐 {total}개 / {len(samples)*len(order)} "
                     f"(오탐율 {rate:.0%})")
        lines.extend(detail)
    with capsys.disabled():
        print("\n".join(lines))

    off = totals["1차 기존(항상 탐지)"]
    # 게이팅(2·3차)이 기존(1차)보다 오탐을 늘리지 않는다(핵심 불변식).
    for label in ("2차 보스 바 인식(띠)", "3차 read_percent(바)"):
        assert totals[label] <= off, f"{label} 오탐({totals[label]})이 1차({off})보다 많음"
    # 적어도 하나의 바닥에선 1차가 실제로 오탐을 낸다(벤치가 신호를 갖는지 확인).
    assert off >= 1, "벤치에 오탐 신호가 없음 — 바닥 샘플/템플릿을 점검하세요"


def _recognized_band(region) -> bool:
    """2차(띠): 밝은 바가 보이거나 확실한 바닥이 아니면(HOLD) 보스로 인정."""
    return DebuffEngine._bar_present(region) or not DebuffEngine._is_background(region)


def _recognized_percent(region) -> bool:
    """3차(percent): 정렬된 바 영역에서 read_percent가 숫자를 읽으면 보스로 인정."""
    return read_percent(_bar_box(region)) is not None


def test_boss_recognition_recall(capsys):
    """보스 체력바가 '보이는' 장면에서 게이팅이 전부 보스로 인정하는지(재현율) 측정.

    과거 회귀(24ca487): 바 탐지에 'hue 단색' 조건을 AND로 더했더니 2색 보스 바가
    과소인식돼(바 아님) 디버프가 잘못 가려졌고, 결국 롤백됐다. 그 함정을 막기 위해
    재현율을 고정한다 — 탐지 방식을 바꿀 때 오탐(FP)뿐 아니라 이 재현율도 함께 봐야 한다.
    """
    samples = [(nm, _region(nm)) for nm in _BOSS_SHOTS]
    samples = [(nm, r) for nm, r in samples if r is not None]
    if not samples:
        pytest.skip("보스 스샷 없음")
    recognizers = [("2차 보스 바 인식(띠)", _recognized_band),
                   ("3차 read_percent(바)", _recognized_percent)]
    lines = ["", "=== 보스 인식 재현율(게이팅) ==="]
    miss_band: list[str] = []
    for label, fn in recognizers:
        miss = [nm.split()[-1] for nm, r in samples if not fn(r)]
        ok = len(samples) - len(miss)
        lines.append(f"  [{label}] {ok}/{len(samples)} ({ok/len(samples):.0%})"
                     + (f"  놓침: {miss}" if miss else "  (전부 인식)"))
        if label.startswith("2차"):
            miss_band = miss
    with capsys.disabled():
        print("\n".join(lines))
    miss = miss_band  # 2차 재현율을 회귀 가드로 고정(3차는 수치만 비교, 바 영역 근사라 참고)
    # 보스전에서의 과소인식은 위험하므로 재현율 100%를 요구한다.
    assert not miss, f"보스 과소인식(게이팅이 바닥으로 오판): {miss}"


def _box_variants(region):
    """바 박스 변형(기본/오른쪽 -px/위아래 확장)으로 정렬 민감도까지 커버."""
    if region is None:
        return []
    h, w = region.shape[:2]
    y0 = int(h * 0.52)
    return [
        region[y0:, :],            # 기본
        region[y0:, : w - 6],      # 오른쪽 끝 -6px
        region[int(h * 0.45):, :],  # 위아래 확장
    ]


def test_cached_matches_original_presence():
    """read_percent_cached의 '있음/없음(None 여부)'이 원본 read_percent와 항상 같은지.

    3차 게이팅은 present/absent만 쓰므로, 캐시 경로가 이 판정을 바꾸지 않음을 라벨 스샷 ×
    박스 변형 × 여러 힌트로 고정한다(캐시는 항상 전체 탐색으로 폴백 → 결과 동일 보장).
    read_percent가 느려(수십 ms) 전체 스샷 대신 라벨 셋(보스+바닥)만 본다.
    """
    names = list(dict.fromkeys(_BOSS_SHOTS + _NO_BOSS_SHOTS))  # 중복 제거
    regions = [_region(nm) for nm in names]
    regions = [r for r in regions if r is not None]
    if not regions:
        pytest.skip("라벨 스샷 없음")
    hints = (None, 0, 99)  # 없음 / 맞는값 / 범위밖(무시) — 모두 원본과 같아야
    checked = 0
    for reg in regions:
        for box in _box_variants(reg):
            if box.size == 0:
                continue
            orig = read_percent(box) is not None
            for hint in hints:
                cached = read_percent_cached(box, hint=hint)[0] is not None
                assert cached == orig, (
                    f"box{box.shape} hint={hint}: cached={cached} orig={orig}"
                )
                checked += 1
    assert checked > 0
