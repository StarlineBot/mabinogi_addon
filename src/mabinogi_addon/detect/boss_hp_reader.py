"""보스 HP% 판독 (기획서 12).

보스 체력바의 'XXX.XX %' 영역에서 정수 HP%를 읽는다. 바 배경색이 HP에 따라
변하고(초록/노랑/빨강/보라), 바가 **2색(예: 파랑+초록, 금+빨강)**이기도 하다.
그래서 **채도(saturation)**로 이진화한다 — 바 채움은 어떤 색이든 **채도가 높고**,
글자(흰/회/검)는 **채도가 낮다**. 색 개수·명암 극성과 무관하게 글자만 남는다.

숫자는 우측 정렬 monospace라 오른쪽 끝 기준 고정 칸으로 자른다. 다만 영역 박스의
오른쪽 끝이 바 끝과 몇 px만 어긋나도 칸이 밀려 깨지므로, **정렬 오프셋을 조금씩
옮겨 보며 가장 확신(매칭 점수) 높은 판독을 고르는 자동정렬**로 그 민감도를 없앴다.
(기획서 12.3)

입력 region 은 보스 HP바 박스(오른쪽 끝 ≈ 바 오른쪽 끝). 칸 위치·간격은 기준
해상도(2560×1440, 바 높이 36px) 기준이며 박스 높이로 스케일 보정한다.

숫자 템플릿: assets/boss_hp_digits/d{0..9}_{i}.png (색거리 이진화, 자리당 다중 샘플).
"""

from __future__ import annotations

import cv2
import numpy as np

from .. import paths
from ..image_io import imread

_DIGIT_DIR = paths.resource_dir() / "boss_hp_digits"
_SAT_MAX = 110  # 채도가 이 미만이면 글자(흰/회/검). 바 채움은 고채도라 제외됨.
_REF_H = 36.0  # 기준 바 높이(px) — 스케일 기준
_FIRST = 62.0  # 바 오른쪽 끝 → 최우측 정수자리 right edge (기준 해상도)
_PITCH = 11.0  # 정수 자리 간격(기준 해상도)
_YBAND = (0.28, 0.82)  # 숫자 세로 밴드(바 테두리 제외)
_MIN_PX = 8  # 칸에 이 미만이면 빈 칸(자리 없음)
_SEARCH = 8  # 정렬 오프셋 탐색 범위(±, 기준 해상도 px)
_ACCEPT = 0.45  # 최고 정렬의 최저 자리 점수가 이 이상이어야 채택
_STRONG = 0.85  # 자리수를 '확신'으로 셀 최저 자리 점수(이 이상이면 그 자리수를 우선 비교)


def _load_digits() -> dict[str, list[np.ndarray]]:
    out: dict[str, list[np.ndarray]] = {}
    if not _DIGIT_DIR.exists():
        return out
    for p in sorted(_DIGIT_DIR.glob("d*_*.png")):
        img = imread(p, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        _, b = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
        out.setdefault(p.name[1], []).append(b)
    return out


_DIGITS = _load_digits()


def _color_mask(region_bgr: np.ndarray) -> np.ndarray:
    """채도가 낮은 픽셀 = 글자. 바 채움(고채도)은 색·개수 무관하게 제외된다
    (2색 바도 OK)."""
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    return (hsv[:, :, 1] < _SAT_MAX).astype(np.uint8) * 255


def _classify(
    glyph: np.ndarray, templates: dict[str, list[np.ndarray]]
) -> tuple[str | None, float]:
    best, best_score = None, -2.0
    for d, samples in templates.items():
        for t in samples:
            g = cv2.resize(glyph, (t.shape[1], t.shape[0]), interpolation=cv2.INTER_NEAREST)
            _, g = cv2.threshold(g, 127, 255, cv2.THRESH_BINARY)
            score = float(cv2.matchTemplate(g, t, cv2.TM_CCOEFF_NORMED).max())
            if score > best_score:
                best, best_score = d, score
    return best, best_score


def _read_at(
    band: np.ndarray, w: int, first: float, pitch: float,
    templates: dict[str, list[np.ndarray]],
) -> tuple[int | None, float, int]:
    """한 정렬에서 오른쪽 끝 기준 고정 칸으로 최대 3자리 읽기. (값, 최저 자리 점수, 자리수)."""
    digits: list[str] = []
    scores: list[float] = []
    for k in range(1, 4):
        right = round(w - first - pitch * (k - 1))
        left = round(right - pitch)
        if left < 0:
            break
        cell = band[:, max(left, 0):right]
        if cell.size == 0 or int((cell > 127).sum()) < _MIN_PX:
            break  # 빈 칸 → 정수부 끝
        ys = np.where((cell > 127).any(axis=1))[0]
        xs = np.where((cell > 127).any(axis=0))[0]
        d, sc = _classify(cell[ys.min():ys.max() + 1, xs.min():xs.max() + 1], templates)
        if d is None:
            return None, -2.0, 0
        digits.append(d)
        scores.append(sc)
    if not digits:
        return None, -2.0, 0
    try:
        value = int("".join(reversed(digits)))
    except ValueError:
        return None, -2.0, 0
    if not 0 <= value <= 100:
        return None, -2.0, 0
    return value, min(scores), len(digits)


def _scan(band, w, scale, pitch, templates, shifts, strong: float = _STRONG):
    """주어진 오프셋 후보들에서 최적 판독을 찾는다. (val, score, shift).

    '확신되는 자리수'가 많은 판독을 우선하고, 동률이면 점수로 고른다. 정렬 창이 왼쪽으로
    밀려 units 자리를 빠뜨린 **1자리 오독**(예: "48.00 %"를 4로)이, 그 1자리 점수가 우연히
    1.00이 나와 정답 2자리(units 점수 0.99)를 이기던 문제를 막는다. 자리수를 '확신될 때만'
    세므로(각 자리 점수 ≥ strong), 실제 1자리 값(예: 4%)에서 이름 글자가 10의 자리로 잘못
    섞이는 것도 막는다(약한 추가 자리는 우선권 없음 → 점수로 폴백).

    strong은 '자리수를 셀' 최저 점수. 기본은 _STRONG(0.85). 저HP 보조 경로는 밝기 마스크라
    템플릿이 덜 맞아 점수가 낮으므로 strong=_ACCEPT로 낮춰(16→'1' 오독 방지) 쓴다."""
    best_key = (-1, -2.0)  # (확신 자리수, 점수)
    best_val: int | None = None
    best_shift: int | None = None
    for shift in shifts:
        val, score, ndig = _read_at(band, w, _FIRST * scale + shift, pitch, templates)
        if val is None:
            continue
        strong_digits = ndig if score >= strong else 0
        key = (strong_digits, score)
        if key > best_key:
            best_key, best_val, best_shift = key, val, shift
    return best_val, best_key[1], best_shift


# 저HP(빨간 바) 보조 경로. 빈 바의 '어두운 회색' 배경은 채도가 낮아 기본 마스크(채도<110)가
# 배경까지 글자로 칠해(flooded) 판독이 None이 된다. 그럴 때만: 숫자 영역이 실제로 flooded
# 인지 확인하고(정상 프레임은 낮음), 밝기까지 보는 보조 마스크로 흰 글자만 남겨 다시 읽는다.
# 템플릿은 그대로라 모양이 덜 맞으므로 약한 기준(_ACCEPT)으로 자리수 우선 선택하고, 빨간 바
# 구간 값(≤_LOW_HP_MAX)일 때만 채택한다(정상 프레임엔 절대 개입하지 않음 = flood 낮음).
_FLOOD_MIN = 0.72  # 숫자 영역 마스크 켜짐 비율이 이 이상이면 flooded(저HP 회색 배경)
_BRIGHT_V = 150  # 보조 마스크: 이 밝기 이상 + 저채도 = 흰 글자
_LOW_HP_MAX = 20  # 보조 경로 결과는 이 이하만 채택(빨간 바 구간 전용)


def _bright_mask(region_bgr: np.ndarray) -> np.ndarray:
    """저채도 + 밝은 픽셀 = 흰 글자. 어두운 회색 배경(저채도지만 어두움)은 제외된다."""
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    return ((hsv[:, :, 1] < _SAT_MAX) & (hsv[:, :, 2] >= _BRIGHT_V)).astype(np.uint8) * 255


def _flooded(band: np.ndarray, w: int) -> bool:
    """숫자 영역(YBAND 행 band × 오른쪽 20% 열)의 저채도 마스크가 꽉 찼는지.

    저HP(빨간 바)에선 빨간 채움이 짧고 숫자 뒤 배경이 회색이라, 숫자 영역이 저채도로
    flooded된다. 정상(고HP) 프레임에선 이 비율이 낮다(개입 안 함)."""
    numcols = band[:, int(w * 0.80):]  # 숫자 영역(오른쪽 20% 열)
    return bool(numcols.size and float((numcols > 127).mean()) >= _FLOOD_MIN)


def number_area_flooded(region_bgr: np.ndarray) -> bool:
    """보스 HP바 박스에서 숫자 영역이 저HP flooded인지(보스 존재 사전 판정 보조).

    저HP 빨간 바는 채움이 짧아 '넓은 가로 연속'이 없지만, 숫자 영역은 회색으로 flooded돼
    있다. 존재 사전 컷에서 has_wide_bar_row가 놓치는 저HP 구간을 이걸로 살린다. 저HP 보조
    판독(_low_hp_value)의 개입 조건과 같은 flood 판정이라, 개입하는 프레임과 정확히 일치한다.
    """
    if region_bgr is None or region_bgr.size == 0 or region_bgr.ndim != 3:
        return False
    h, w = region_bgr.shape[:2]
    band = _color_mask(region_bgr)[int(h * _YBAND[0]):int(h * _YBAND[1])]
    return _flooded(band, w)


def _low_hp_value(region_bgr, templates, band, w, scale, pitch, span) -> int | None:
    """기본 판독이 None일 때의 저HP 보조 판독. 해당 없으면 None(정상 경로 불변)."""
    if not _flooded(band, w):
        return None  # flooded 아님 → 저HP 아님 → 개입 안 함
    h = region_bgr.shape[0]
    bband = _bright_mask(region_bgr)[int(h * _YBAND[0]):int(h * _YBAND[1])]
    val, score, _ = _scan(
        bband, w, scale, pitch, templates, range(-span, span + 1), strong=_ACCEPT
    )
    if val is None or score < _ACCEPT or val > _LOW_HP_MAX:
        return None
    return val


def _prep(region_bgr, templates):
    """공통 전처리. 유효하지 않으면 None."""
    templates = _DIGITS if templates is None else templates
    if region_bgr is None or region_bgr.size == 0 or not templates:
        return None
    if region_bgr.ndim != 3:
        return None
    h, w = region_bgr.shape[:2]
    scale = h / _REF_H
    band = _color_mask(region_bgr)[int(h * _YBAND[0]):int(h * _YBAND[1])]
    pitch = _PITCH * scale
    span = max(1, round(_SEARCH * scale))
    return templates, w, scale, band, pitch, span


def read_percent(
    region_bgr: np.ndarray,
    templates: dict[str, list[np.ndarray]] | None = None,
) -> int | None:
    """보스 HP바 박스(BGR, 오른쪽 끝 ≈ 바 오른쪽 끝)에서 정수 HP%(0~100)를 읽는다.

    못 읽으면 None(틀린 값보다 안전). 정렬 오프셋을 ±탐색해 가장 확신 높은 판독을
    고르므로, 박스가 몇 px 어긋나도 알아서 맞춰 읽는다.
    """
    prep = _prep(region_bgr, templates)
    if prep is None:
        return None
    templates, w, scale, band, pitch, span = prep
    val, score, _ = _scan(band, w, scale, pitch, templates, range(-span, span + 1))
    if val is not None and score >= _ACCEPT:
        return val
    return _low_hp_value(region_bgr, templates, band, w, scale, pitch, span)


def read_percent_cached(
    region_bgr: np.ndarray,
    templates: dict[str, list[np.ndarray]] | None = None,
    hint: int | None = None,
) -> tuple[int | None, int | None]:
    """read_percent와 '있음/없음(None 여부)'은 동일하되 빠른 버전 — (값, 당첨 오프셋).

    바의 오른쪽 끝은 영역 안에서 고정이라 당첨 오프셋이 매 프레임 거의 같다. 그래서
    직전 당첨 오프셋(hint)만 먼저 보고, 실패하면 ±1, 그래도 실패하면 전체 탐색으로
    폴백한다(단계식). 전체 탐색을 항상 포함하므로 '있음/없음' 결과는 read_percent와
    완전히 같고(폴백 보장), 흔한 경우(힌트 적중)만 17배 빨라진다. 디버프 3차 전용 —
    보스패턴알림은 값을 쓰므로 read_percent(전체 탐색)를 그대로 쓴다.
    """
    prep = _prep(region_bgr, templates)
    if prep is None:
        return None, None
    templates, w, scale, band, pitch, span = prep
    # 1) 힌트 1곳  2) 힌트±1  — 적중하면 즉시 반환(대부분 여기서 끝).
    if hint is not None and -span <= hint <= span:
        val, score, shift = _scan(band, w, scale, pitch, templates, (hint,))
        if score >= _ACCEPT:
            return val, shift
        near = [s for s in (hint - 1, hint + 1) if -span <= s <= span]
        val, score, shift = _scan(band, w, scale, pitch, templates, near)
        if score >= _ACCEPT:
            return val, shift
    # 3) 전체 탐색(폴백) — read_percent와 동일 결과.
    val, score, shift = _scan(band, w, scale, pitch, templates, range(-span, span + 1))
    if score >= _ACCEPT:
        return val, shift
    # 4) 저HP 보조 경로(read_percent와 동일 조건). 밝기 마스크라 당첨 오프셋은 재사용 불가(None).
    low = _low_hp_value(region_bgr, templates, band, w, scale, pitch, span)
    return (low, None) if low is not None else (None, None)
