"""상태목록창(버프 리스트) 자동 위치 검출 (영역 자동 찾기).

상태목록창은 사용자가 화면 어디로든 **옮길 수 있다**. 그래서 고정 위치를 가정하지 않고,
앵커 버프(프리미엄 배틀 멤버십)의 작은 리스트 아이콘을 **전체
화면에서 멀티스케일 템플릿 매칭**으로 찾는다. 해상도·UI 배율이 달라 아이콘 픽셀 크기가
변해도 여러 크기를 시도해 흡수한다(=유기적).

여기서는 '앵커를 정확히 어디서 찾는가'까지만 담당한다(순수 함수, 맥에서도 테스트 가능).
멤버십 아이콘이 없으면 같은 열·행 간격의 서로 다른 버프 아이콘 3개를 확인한다.
패널 경계(반투명 검은 박스) 바운딩·영역 설정은 호출 측(UI)에서 이 위치를 기준으로 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# 앵커 아이콘 한 변(px) 후보. 게임 UI 배율·해상도에 따라 리스트 아이콘 크기가 달라지므로
# 여러 크기를 시도한다(현재 수집 스샷은 16px에서 매칭). 범위는 필요 시 넓힌다.
_SCALES: tuple[int, ...] = (12, 14, 16, 18, 20, 22, 24)
# 매칭 신뢰 임계. 실제 앵커는 1.0 근처로 잡히고 노이즈 최고점은 0.6 미만이라 여유가 크다.
_THRESHOLD = 0.85


def anchor_template() -> np.ndarray | None:
    """앵커(프리미엄 배틀 멤버십) 아이콘 템플릿을 로드한다(없으면 None)."""
    from ..catalog import DEFAULT_ICON_DIR

    return cv2.imread(str(DEFAULT_ICON_DIR / "premium_battle.png"))


@dataclass(frozen=True)
class AnchorHit:
    score: float  # 매칭 점수(0~1)
    x: int  # 매칭 영역 좌상단 x
    y: int  # 매칭 영역 좌상단 y
    size: int  # 매칭에 쓰인 아이콘 한 변(px)

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.size // 2, self.y + self.size // 2)


def find_anchor(
    frame: np.ndarray,
    template: np.ndarray,
    *,
    threshold: float = _THRESHOLD,
    scales: tuple[int, ...] = _SCALES,
    diagnostics: dict | None = None,
) -> AnchorHit | None:
    """전체 화면에서 앵커 아이콘을 멀티스케일로 찾아 위치를 돌려준다(없으면 None).

    상태목록창이 어디로 옮겨졌든 찾도록 프레임 전체를 탐색한다. 임계 미만(앵커가 화면에
    없거나 리스트가 접힘)이면 None → 호출 측은 수동 지정으로 폴백한다.
    """
    if frame is None or template is None or frame.size == 0 or template.size == 0:
        return None
    # 성능: 전체 컬러 프레임에 멀티스케일 매칭은 ~3초(UI 멈춤)다. 앵커는 '빨간 아이콘'이라
    # 색 정보가 핵심(흑백은 매칭이 약해짐) → 색은 유지한 채 반해상도로 1차 탐색하고, 그
    # 주변만 원해상도로 정밀 재탐색한다(수백 ms). 결과 좌표계는 원해상도 그대로.
    fh, fw = frame.shape[:2]
    if diagnostics is not None:
        diagnostics.update(threshold=threshold, scales=list(scales),
                           search_region=[0, 0, fw, fh],
                           transforms=["BGR resize 1/2 INTER_AREA", "local full-resolution TM_CCOEFF_NORMED"])
    small = cv2.resize(frame, (fw // 2, fh // 2), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    coarse = (-1.0, 0, 0, scales[0])  # (score, x, y, size) — 반해상도 좌표
    for s in scales:
        hs = max(4, s // 2)
        if sh <= hs or sw <= hs:
            continue
        t = cv2.resize(template, (hs, hs), interpolation=cv2.INTER_AREA)
        _, mx, _, ml = cv2.minMaxLoc(cv2.matchTemplate(small, t, cv2.TM_CCOEFF_NORMED))
        if mx > coarse[0]:
            coarse = (float(mx), int(ml[0]), int(ml[1]), s)
    if coarse[0] < threshold * 0.8:  # 1차에서 확실히 없음(반해상도라 임계 약간 완화)
        if diagnostics is not None:
            diagnostics.update(coarse=list(coarse), coarse_threshold=threshold * 0.8,
                               rejection="coarse_score_below_threshold")
        return None
    # 2차: 원해상도에서 1차 위치 주변 작은 창만 정밀 매칭.
    cx, cy, coarse_size = coarse[1] * 2, coarse[2] * 2, coarse[3]
    # 1차는 반해상도라 크기 추정이 ±2px 어긋난다(예: 4K에서 1차=14px인데 실제 최적=16px).
    # 그래서 2차에서는 코어스 크기 주변 정수 크기(±3)를 모두 시도해 최고점을 고른다. 창이
    # 작아 비용은 미미하다. (지난 커밋은 코어스 크기 하나만 재시도해 4K에서 놓쳤다.)
    pad = coarse_size * 2
    x0, y0 = max(0, cx - pad), max(0, cy - pad)
    best: AnchorHit | None = None
    for size in range(max(8, coarse_size - 3), coarse_size + 4):
        x1, y1 = min(fw, cx + size + pad), min(fh, cy + size + pad)
        win = frame[y0:y1, x0:x1]
        if win.shape[0] <= size or win.shape[1] <= size:
            continue
        t = cv2.resize(template, (size, size), interpolation=cv2.INTER_AREA)
        _, mx, _, ml = cv2.minMaxLoc(cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED))
        if best is None or mx > best.score:
            best = AnchorHit(float(mx), x0 + int(ml[0]), y0 + int(ml[1]), size)
    if best is None or best.score < threshold:
        if diagnostics is not None:
            diagnostics.update(coarse=list(coarse), best=None if best is None else vars(best),
                               rejection="fine_score_below_threshold")
        return None
    if diagnostics is not None:
        diagnostics.update(coarse=list(coarse), best=vars(best), rejection=None)
    return best


def locate_status_region(
    frame: np.ndarray,
    template: np.ndarray,
    *,
    threshold: float = _THRESHOLD,
    diagnostics: dict | None = None,
    fallback_templates: dict | None = None,
) -> tuple[int, int, int, int] | None:
    """상태목록창 전체 영역 (x,y,w,h)를 앵커 기준으로 유도한다(없으면 None).

    앵커(아이콘 열)를 찾은 뒤: 왼쪽=아이콘 열, 폭=리스트 폭 추정, 위로는 버프들이 쌓인
    만큼 넉넉히, 아래는 '버프가 더 걸리면 아래로 길어지므로' 화면 끝까지 잡는다. 정확한
    패널 경계(반투명 박스 상단)는 배경을 타서 어려우므로, 넉넉히 잡고 사용자가 미리보기로
    확인/조정하는 전제(베타). 앵커가 없으면 복수 아이콘 열을 확인하고, 둘 다 없으면 None.
    """
    hit = find_anchor(frame, template, threshold=threshold, diagnostics=diagnostics)
    if hit is None:
        return locate_icon_column(frame, fallback_templates, diagnostics)
    H, W = frame.shape[:2]
    s = hit.size
    left = max(0, hit.x - int(s * 0.3))
    # 폭은 실측 패널 폭(≈ s*19; s=16이면 ~304px, 실제 스샷 패널 ~290~305px)에 맞춘다.
    # 지난 커밋의 s*26(416px)은 과하게 넓어 캡처 비용이 늘고 우측 채팅/배경을 포함할 위험이
    # 있었다. s 상대라 인게임 UI 배율이 바뀌어 아이콘이 커져도 폭이 함께 변한다(=유기적).
    # (반투명 패널의 '정확한' 좌우 경계를 프레임에서 직접 재는 건 배경을 타서 불안정하므로,
    #  s 기준 보정값 + 베타 미리보기/확인으로 둔다.)
    width = min(int(s * 19), W - left)
    # 앵커(프리미엄 배틀)는 보통 리스트 하단부라 위로 넉넉히(약 34줄) 잡는다. 아래는 '버프가
    # 더 걸리면 아래로 길어지므로' 화면 끝까지 잡는다(상한 없음). 상한을 두면 버프가 늘어
    # 앵커가 영역 밖으로 밀려 트래커가 조용히 멈출 수 있다.
    top = max(0, hit.y - int(s * 34))
    return (left, top, width, max(1, H - top))


def fallback_assets():
    from ..catalog import DEFAULT_ICON_DIR
    from ..image_io import imread
    return {name: image for name in ('speed','music_boost','magic_attack','overture_of_the_battlefield','march')
            if (image := imread(DEFAULT_ICON_DIR / (name + '.png'))) is not None}


def locate_icon_column(frame, templates=None, diagnostics=None):
    """Without membership: require three distinct list icons in one 24px-spaced column.

    Large shortcut icons and a single matching effect cannot establish a list.
    Multiple plausible columns are rejected instead of choosing a score winner.
    """
    if frame is None or not frame.size:
        return None
    templates = fallback_assets() if templates is None else templates
    hits = []
    for name, template in templates.items():
        if min(frame.shape[:2]) < max(template.shape[:2]):
            continue
        scores = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        # Bounded peaks; nearby repeated correlation maxima count only once.
        for _ in range(6):
            _, score, _, (x,y) = cv2.minMaxLoc(scores)
            if score < .9:
                break
            hits.append((name,x,y))
            scores[max(0,y-8):y+9,max(0,x-8):x+9] = -1
    columns = {}
    for _,x,y in hits:
        aligned = [(name,hy) for name,hx,hy in hits if abs(hx-x)<=1 and
                   min(abs(hy-y)%24,24-abs(hy-y)%24)<=1]
        if len({name for name,_ in aligned}) >= 3 and len({hy for _,hy in aligned})>=3:
            columns[x] = sorted({hy for _,hy in aligned})
    if not columns or max(columns)-min(columns)>2:
        return None
    x = min(columns)
    top = max(0,min(columns[x])-16*34)
    left = max(0,x-4)
    result = left,top,min(304,frame.shape[1]-left),frame.shape[0]-top
    if diagnostics is not None:
        diagnostics.update(rejection=None, fallback='aligned_distinct_buff_icons', column=x, rows=columns[x])
    return result
