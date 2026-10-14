"""보스 체력바 영역 자동 찾기 (전체 화면에서 위치 검출).

보스바는 채움 색이 HP 단계별로 바뀌고(보라>파랑>노랑>빨강 …) 보스마다 이름·폭이 달라서
'색'으로는 못 잡는다. 대신 **구조**로 구분한다 — 화면 하단 메뉴바 위에 뜨는,
**하나의 연속된 솔리드 가로 바**다. 자동 찾기는 설정 시 1회만, 보스 첫 노출(고HP) 때
쓰므로 그걸로 충분하다.

왜 '채도 덩어리(연결 컴포넌트)'가 아니라 '행(行) 특징'으로 바꿨나 — 보스바 옆에 추가
단축바·채팅창·버프 아이콘이 붙으면, 채도 마스크를 가로로 이어(close) 연결 컴포넌트로
잡는 방식은 그것들이 바와 한 덩어리로 합쳐져 크기 필터에서 탈락한다(제보 화면: 바+단축바가
h=85로 묶여 None). 그래서 **주변 UI 배치와 무관하게** 바 '자체 특징'으로 찾는다:

1. 화면 하단(y > 72%)에서 **행마다 '채도 픽셀의 최장 가로 연속 길이'**를 구한다.
2. 그 길이가 화면폭 18% 이상인 행 = 바의 **가장자리 행**(글자가 없어 한 줄로 쭉 이어짐).
   아이콘·단축바·채팅은 이런 긴 가로 연속이 없어 씨앗이 되지 않는다.
3. 씨앗 행의 좌우 범위 안에서 **채움 비율 ≥ 0.45 인 연속 행**을 위아래로 확장 = 바 높이
   (글자 행도 바 색이 비쳐 ≥0.45라 포함, 아래 다른 바(펠롬 에르그)와는 얇은 경계 행에서 끊김).
4. 그 띠의 가장자리 행들(최장 연속 ≥ 띠 최대의 90%)의 시작/끝 **중앙값**으로 좌우 끝을 정한다
   (글자·채팅이 섞인 행에 휘둘리지 않음).
5. 높이·납작 비율 필터 → 높이 정규화 → make_validator(이름 글자 + % 판독) 검증.

여러 개면 폭 큰 것 우선(같으면 위쪽 = 보스 HP바가 에르그 바 위). 없으면 None.
"""

from __future__ import annotations

import cv2
import numpy as np

_SAT_MIN = 90
_VAL_MIN = 80
_MIN_W_FRAC = 0.18  # 화면 폭 대비 최소 바 폭(= 가장자리 행 '씨앗' 판정의 최장 연속 하한)
_MIN_H_FRAC = 0.014  # 화면 높이 대비 최소 바 높이
_MAX_H_FRAC = 0.06  # 최대(너무 두꺼운 건 바 아님)
_FLAT_RATIO = 6  # w > h * 이것 (납작한 가로 바)
_BOTTOM_FRAC = 0.72  # 이 아래(하단)에서만
_FILL_ROW = 0.45  # 바 높이 확장: 씨앗 좌우 범위 안 '채움 행' 비율 하한(글자 행도 통과)
_EDGE_FRAC = 0.90  # 좌우 끝 확정에 쓸 '가장자리 행' 기준(띠 내 최장 연속의 이 비율 이상)
# 이름 글자(흰색) 판정: 채도 낮고 밝은 픽셀. 바 채움은 고채도라 제외된다.
_NAME_SAT_MAX = 90
_NAME_VAL_MIN = 170
_NAME_COV_MIN = 0.012  # 박스 왼쪽 60%에서 흰 글자 최소 비율(실제 보스 ≥0.027, 여유 둠)


def _has_name_text(sub: np.ndarray) -> bool:
    """보스바 박스 왼쪽에 이름 글자(흰 텍스트)가 있는지 — '누구'인지는 보지 않는다."""
    w = sub.shape[1]
    left = sub[:, : int(w * 0.60)]
    hsv = cv2.cvtColor(left, cv2.COLOR_BGR2HSV)
    glyph = (hsv[:, :, 1] < _NAME_SAT_MAX) & (hsv[:, :, 2] > _NAME_VAL_MIN)
    return float(glyph.mean()) >= _NAME_COV_MIN


def make_validator(*, templates=None, diagnostics: dict | None = None):
    """박스가 진짜 보스바인지 검증하는 콜백 — HP% 판독이 되고(오른쪽에 'XXX.XX%'),
    왼쪽에 **이름 글자가 있을 때**만 True. (지난 커밋은 등록된 5개 보스만 식별(identify)해
    통과시켜, 글라스 기브넨 등 미등록 보스에선 자동 찾기가 안 됐다. 디버프 트래커는 모든
    보스에서 써야 하므로, '누구인지'가 아니라 '이름 글자 + %가 있는 바'인지로 바꾼다.)

    이걸로 거르는 것: 펠롬 2단 바 등 % 판독 실패(read_percent None), 글자 없는 솔리드 밴드.
    """
    from .boss_hp_reader import read_percent

    def validate(sub: np.ndarray) -> bool:
        if sub is None or sub.size == 0 or sub.shape[1] < 20:
            return False
        percent = read_percent(sub, templates)
        if percent is None:
            if diagnostics is not None:
                diagnostics.setdefault("validation", []).append({"percent": None, "rejection": "percent_unreadable"})
            return False
        has_name = _has_name_text(sub)
        if diagnostics is not None:
            diagnostics.setdefault("validation", []).append({"percent": percent, "rejection": None if has_name else "name_text_missing"})
        return has_name

    return validate


def _row_longest_runs(
    mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """각 행의 '1(채도) 픽셀 최장 가로 연속'의 (길이, 시작x, 끝x)를 돌려준다.

    픽셀 반복문을 쓰지 않도록 **열 단위로만 루프**(W회)하고, 매 열에서 모든 행을 동시에
    갱신한다. run[y]=현재 열에서 끝나는 연속 길이(0에서 리셋), best/끝을 최댓값으로 추적.
    """
    r, w = mask.shape
    run = np.zeros(r, np.int32)  # 지금 열에서 끝나는 연속 길이
    best = np.zeros(r, np.int32)  # 최장 길이
    best_end = np.full(r, -1, np.int32)  # 최장 연속이 끝나는 열 x
    for col in range(w):
        on = mask[:, col]
        run = np.where(on, run + 1, 0)
        upd = run > best
        best = np.where(upd, run, best)
        best_end = np.where(upd, col, best_end)
    best_start = best_end - best + 1
    return best, best_start, best_end


def has_wide_bar_row(frame: np.ndarray, frac: float = 0.70) -> bool:
    """프레임에 '채도 픽셀 최장 가로 연속 ≥ 폭×frac'인 행이 하나라도 있는지(값싼 사전 판정).

    보스바가 떠 있으면 가장자리 행이 바 폭만큼 쭉 이어진다. 보스바가 없으면(길바닥·UI)
    이런 긴 가로 연속이 없어 즉시 걸러진다. 보스 존재 판정에서 **비싼 make_validator
    (read_percent 포함, ~36ms)를 부르기 전** 이 ~1ms 컷으로 평상시 프레임을 빠르게 거른다.
    """
    if frame is None or frame.size == 0 or frame.shape[1] < 2:
        return False
    _, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    sat = (hsv[:, :, 1] > _SAT_MIN) & (hsv[:, :, 2] > _VAL_MIN)
    best, _, _ = _row_longest_runs(sat)
    return bool(best.size and int(best.max()) >= w * frac)


def locate_boss_bar(
    frame: np.ndarray, validate=None, *, diagnostics: dict | None = None
) -> tuple[int, int, int, int] | None:
    """전체 화면에서 보스 체력바 영역 (x,y,w,h)를 찾는다(없으면 None).

    주변 UI(단축바·채팅·버프 아이콘) 배치와 무관하게, 바 '자체 특징'(긴 가로 연속을 갖는
    가장자리 행 → 채움 행 확장)으로 찾는다(모듈 상단 설명 1~5). 보스바가 안 보이면 None.
    validate(sub_bgr)->bool 을 주면, 그 박스 안에서 검증(퍼센트·이름 판독)이 통과한 후보만
    채택한다(이름 없는 솔리드 밴드·% 판독 실패 등을 거른다).
    """
    if frame is None or frame.size == 0 or frame.shape[0] < 40 or frame.shape[1] < 80:
        return None
    H, W = frame.shape[:2]
    if diagnostics is not None:
        diagnostics.update(transforms=["BGR to HSV", "saturation mask", "row longest run", "height normalization"],
                           search_region=[0, int(H * _BOTTOM_FRAC), W, H - int(H * _BOTTOM_FRAC)],
                           thresholds={"saturation_min": _SAT_MIN, "value_min": _VAL_MIN,
                                       "min_width_fraction": _MIN_W_FRAC, "fill_row": _FILL_ROW,
                                       "min_height_fraction": _MIN_H_FRAC, "max_height_fraction": _MAX_H_FRAC,
                                       "flat_ratio": _FLAT_RATIO, "edge_fraction": _EDGE_FRAC},
                           candidates=[], rejection="no_geometric_candidate")
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    sat = (hsv[:, :, 1] > _SAT_MIN) & (hsv[:, :, 2] > _VAL_MIN)
    y_off = int(H * _BOTTOM_FRAC)  # 하단 영역에서만 (바는 메뉴바 위)
    band = sat[y_off:, :]  # (R, W) bool — 하단
    R = band.shape[0]
    best, bstart, bend = _row_longest_runs(band)
    min_run = int(W * _MIN_W_FRAC)
    min_h, max_h = int(H * _MIN_H_FRAC), int(H * _MAX_H_FRAC)
    seeds = np.flatnonzero(best >= min_run)  # 가장자리 행(긴 가로 연속) — 위→아래
    cands: list[tuple[int, int, int, int]] = []
    consumed = np.zeros(R, bool)  # 한 띠로 쓴 행은 다른 씨앗이 재사용하지 않게
    for r in seeds:
        if consumed[r]:
            continue
        x0, x1 = int(bstart[r]), int(bend[r])  # 씨앗 행의 바 좌우 범위
        row_fill = band[:, x0 : x1 + 1].mean(axis=1)  # 그 범위 안 행별 채움 비율
        top = r
        while top - 1 >= 0 and row_fill[top - 1] >= _FILL_ROW:
            top -= 1
        bot = r
        while bot + 1 < R and row_fill[bot + 1] >= _FILL_ROW:
            bot += 1
        consumed[top : bot + 1] = True
        # 띠의 '가장자리 행'(최장 연속 ≥ 띠 최대의 90%)들의 시작/끝 중앙값 = 좌우 끝.
        band_best = best[top : bot + 1]
        edge = np.flatnonzero(band_best >= _EDGE_FRAC * int(band_best.max()))
        left = int(np.median(bstart[top : bot + 1][edge]))
        right = int(np.median(bend[top : bot + 1][edge]))
        h = bot - top + 1
        w = right - left + 1
        if not (w >= min_run and min_h <= h <= max_h and w > h * _FLAT_RATIO):
            if diagnostics is not None:
                diagnostics["candidates"].append({"box": [left, y_off + int(top), w, int(h)], "rejection": "geometry_filter"})
            continue
        cands.append(normalize_box_height((left, y_off + top, w, h), H))
    cands.sort(key=lambda b: (-b[2], b[1]))  # 폭 큰 것 우선, 같으면 위쪽(HP바가 에르그 위)
    if validate is not None:
        for bx, by, bw, bh in cands:
            accepted = validate(frame[by : by + bh, bx : bx + bw])
            if diagnostics is not None:
                diagnostics["candidates"].append({"box": [bx, by, bw, bh], "rejection": None if accepted else "percent_or_name_validation"})
                diagnostics["rejection"] = None if accepted else "all_candidates_failed_validation"
            if accepted:
                return (bx, by, bw, bh)
        return None  # 판독 검증을 통과한 후보가 없음
    return cands[0] if cands else None


# 보스바 높이는 보스마다 다르지만(레넨 37px, 글라스 기브넨 45px) **세로 중심과 이름·% 글자
# 크기·위치는 같다**. read_percent는 박스 높이(h/36)로 글자 크기를 스케일하므로, 높이가 큰
# 박스를 '공유 보스바 영역'에 저장하면 **다른 보스 HP가 1/10로 읽혀** 패턴 알림이 오작동한다.
# 그래서 찾은 바의 세로 중심만 쓰고 높이는 고정 비율로 정규화한다. (기준 2560×1440 → 37px.
# 비율이라 4K도 비례하나, 4K 보스 스샷이 없어 미검증 — 확보 시 확인할 것.)
# 자동 찾기뿐 아니라 **손으로 잡은 박스도 판독 직전 이 함수로 정규화**한다(예: 40px로 잡아
# 46%가 4로 읽히던 것). 화면 내용이 아니라 H(화면/프레임 높이) 기반 고정 계산이라 프레임마다
# 결과가 같다 → 판독이 흔들리지 않는다(매 프레임 채움행 트림은 흔들려서 안 쓴다).
_HEIGHT_FRAC = 0.0257


def normalize_box_height(
    box: tuple[int, int, int, int], H: int
) -> tuple[int, int, int, int]:
    """박스의 세로 중심은 유지하고 높이를 고정 비율(H×_HEIGHT_FRAC)로 맞춘다. x·w는 그대로.

    H는 box와 같은 좌표계의 화면/프레임 높이(자동 찾기는 물리 프레임 높이, 런타임 수동 박스
    정규화는 논리 화면 높이 — 비율이 같아 어느 쪽이든 같은 바 높이로 수렴)."""
    x, y, w, h = box
    cy = y + h / 2
    nh = round(H * _HEIGHT_FRAC)
    ny = round(cy - nh / 2)
    ny = max(0, min(ny, H - nh))
    return (int(x), int(ny), int(w), int(nh))
