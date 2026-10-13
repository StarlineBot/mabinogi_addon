"""상태목록창(버프 리스트) 자동 위치 검출 (영역 자동 찾기).

상태목록창은 사용자가 화면 어디로든 **옮길 수 있다**. 그래서 고정 위치를 가정하지 않고,
'반드시 떠 있어야 하는' 앵커 버프(프리미엄 배틀 멤버십)의 작은 리스트 아이콘을 **전체
화면에서 멀티스케일 템플릿 매칭**으로 찾는다. 해상도·UI 배율이 달라 아이콘 픽셀 크기가
변해도 여러 크기를 시도해 흡수한다(=유기적).

여기서는 '앵커를 정확히 어디서 찾는가'까지만 담당한다(순수 함수, 맥에서도 테스트 가능).
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
) -> AnchorHit | None:
    """전체 화면에서 앵커 아이콘을 멀티스케일로 찾아 위치를 돌려준다(없으면 None).

    상태목록창이 어디로 옮겨졌든 찾도록 프레임 전체를 탐색한다. 임계 미만(앵커가 화면에
    없거나 리스트가 접힘)이면 None → 호출 측은 수동 지정으로 폴백한다.
    """
    if frame is None or template is None or frame.size == 0 or template.size == 0:
        return None
    fh, fw = frame.shape[:2]
    best: AnchorHit | None = None
    for s in scales:
        if fh <= s or fw <= s:
            continue
        t = cv2.resize(template, (s, s), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(frame, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, ml = cv2.minMaxLoc(res)
        if best is None or mx > best.score:
            best = AnchorHit(float(mx), int(ml[0]), int(ml[1]), s)
    if best is None or best.score < threshold:
        return None
    return best


def locate_status_region(
    frame: np.ndarray,
    template: np.ndarray,
    *,
    threshold: float = _THRESHOLD,
) -> tuple[int, int, int, int] | None:
    """상태목록창 전체 영역 (x,y,w,h)를 앵커 기준으로 유도한다(없으면 None).

    앵커(아이콘 열)를 찾은 뒤: 왼쪽=아이콘 열, 폭=리스트 폭 추정, 위로는 버프들이 쌓인
    만큼 넉넉히, 아래는 '버프가 더 걸리면 아래로 길어지므로' 화면 끝까지 잡는다. 정확한
    패널 경계(반투명 박스 상단)는 배경을 타서 어려우므로, 넉넉히 잡고 사용자가 미리보기로
    확인/조정하는 전제(베타). 앵커가 없으면 None.
    """
    hit = find_anchor(frame, template, threshold=threshold)
    if hit is None:
        return None
    H, W = frame.shape[:2]
    s = hit.size
    left = max(0, hit.x - int(s * 0.3))
    width = min(int(s * 26), W - left)  # 아이콘 + 이름 + 남은시간 포함 추정 폭
    top = max(0, hit.y - int(s * 40))  # 앵커 위 버프들(넉넉히; 왼쪽 위는 보통 게임 월드)
    height = H - top  # 아래로 길어지는 리스트를 다 덮게 화면 끝까지
    return (left, top, width, height)
