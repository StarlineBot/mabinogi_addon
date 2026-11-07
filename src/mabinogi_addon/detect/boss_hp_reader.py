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
_UI_H = 37  # 실제 게임 보스바 높이(해상도 무관 고정) — 이보다 높은 박스는 이 배율로 숫자 위치를 본다
_FIRST = 62.0  # 바 오른쪽 끝 → 최우측 정수자리 right edge (기준 해상도)
_PITCH = 11.0  # 정수 자리 간격(기준 해상도)
_YBAND = (0.28, 0.82)  # 숫자 세로 밴드(바 테두리 제외)
_MIN_PX = 8  # 칸에 이 미만이면 빈 칸(자리 없음)
_DIGIT_JITTER = 0.2  # 둘째 자리부터 칸마다 따로 맞출 범위(자리 간격의 비율 — 기준 11px에서 ±2px)
_SEARCH = 8  # 정렬 오프셋 탐색 범위(±, 기준 해상도 px)
_ACCEPT = 0.45  # 최고 정렬의 최저 자리 점수가 이 이상이어야 채택
_STRONG = 0.85  # 자리수를 '확신'으로 셀 최저 자리 점수(이 이상이면 그 자리수를 우선 비교)
# 값으로 쓰는 최저 점수(read_percent 기본 경로). _ACCEPT~이 사이는 '바는 있음'(read_percent_cached·존재 판정)으로만.
VALUE_MIN_SCORE = 0.6


# 4K(3840×2160)에서 굵게 그려진 숫자 샘플(0.30.1: 213520 '76'·214016 '100', 0.31.0: 0055251 '86').
UHD_DIGIT_SAMPLES = frozenset({"d0_12", "d1_1", "d6_5", "d7_4", "d6_6", "d8_3"})


import threading

_LAST = threading.local()  # 스레드별 마지막 판독의 확신 키(보스바 오버레이가 같은 영역을 다시 읽지 않게, QA 6569a44)
NO_KEY = (-1, -2.0)


def _key(val, score) -> tuple[int, float]:
    """(확신 자리수, 최저 자리 점수) — 모든 자리가 강한 점수면 자리수, 아니면 0."""
    if val is None:
        return NO_KEY
    return (len(str(val)) if score >= _STRONG else 0), float(score)


def last_key() -> tuple[int, float]:
    """이 스레드에서 마지막으로 한 read_percent·read_percent_frac·read_percent_scored의 확신 키."""
    return getattr(_LAST, "key", NO_KEY)


def _load_digits(pattern="d*_*.png", exclude=frozenset()) -> dict[str, list[np.ndarray]]:
    out: dict[str, list[np.ndarray]] = {}
    if not _DIGIT_DIR.exists():
        return out
    for p in sorted(_DIGIT_DIR.glob(pattern)):
        if p.stem in exclude:
            continue
        img = imread(p, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        _, b = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
        out.setdefault(p.stem.removeprefix("bright_")[1], []).append(b)
    return out


_DIGITS = _load_digits()
# Bright-only glyphs never compete with normal saturation-mask samples.
_BRIGHT_SAMPLES = _load_digits("bright_d*_*.png")


def _color_mask(region_bgr: np.ndarray) -> np.ndarray:
    """채도가 낮은 픽셀 = 글자. 바 채움(고채도)은 색·개수 무관하게 제외된다
    (2색 바도 OK)."""
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    return (hsv[:, :, 1] < _SAT_MAX).astype(np.uint8) * 255


_GRAY_S = 15            # 빈 바 회색 바탕: 채도 거의 0
_GRAY_V = (45, 85)      # 빈 바 회색 바탕 밝기(실측 50~70) — 글자(흰)·테두리(검정)는 이 밖
# 빈 바(회색, 채도 0·밝기 50~70)는 채도만 보면 글자와 같아 숫자 칸이 통째로 칠해졌다 — 채움 끝이 숫자를 가로지르면
# 경계 오른쪽 숫자가 사라져 '17.48'을 1로 읽음(QA 8067a9c). 그래서 '회색 바탕 그 자체'(채도 거의 0·밝기 45~85)를 뺀 마스크로
# 한 번 더 읽어 **기본 판독을 늘리기만** 한다(_extend): 앞자리만 남은 값(1→17, 10→100)을 더 긴 값으로, 못 읽은 소수를 채우기.
# 기본 판독이 None이면 쓰지 않고(새 오독 없음), 기본 판독과 다른 값으로 바꾸지 않는다 — 이 마스크로 통째로 읽으면
# 저HP·소수가 오히려 나빠졌다(tests/data 비교표, docs/status.md).
USE_TEXT_MASK = True  # 보조 판독(회색 바탕 뺀 마스크) 사용 — 비교표용 스위치
_PREFIX_MIN = 0.80  # 앞자리만 남은 판독 대신 고를 더 긴 판독의 최저 점수
_NUM_LEFT = 0.78    # 숫자 칸(오른쪽) 시작 — 이 안에 회색 바탕이 있을 때만 보조 판독
_GRAY_MIN = 0.05    # 숫자 칸에 회색 바탕과 채움이 둘 다 이만큼 있을 때 = 채움 끝이 숫자 칸 안
_FILL_S = 120


def _text_mask(region_bgr: np.ndarray) -> np.ndarray:
    """보조 판독용: 저채도 마스크에서 회색 빈 바 바탕(채도 ≤15·밝기 45~85)만 뺀다."""
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    gray = (s <= _GRAY_S) & (v > _GRAY_V[0]) & (v <= _GRAY_V[1])
    return ((s < _SAT_MAX) & ~gray).astype(np.uint8) * 255


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
    templates: dict[str, list[np.ndarray]], jitter: int = 0,
) -> tuple[int | None, float, int]:
    """한 정렬에서 오른쪽 끝 기준 고정 칸으로 최대 3자리 읽기. (값, 최저 자리 점수, 자리수).
    jitter > 0이면 둘째 자리부터 칸마다 ±jitter px 따로 맞춘다(_scan의 두 번째 탐색에서만)."""
    digits: list[str] = []
    scores: list[float] = []
    for k in range(1, 4):
        right0 = round(w - first - pitch * (k - 1))
        best: tuple[str | None, float] | None = None
        # 둘째 자리부터는 칸마다 ±jitter px 따로 맞춘다 — 글자 폭이 달라 자리 간격이 고정이 아니다
        # ('46.96 %'에서 6이 맞는 위치와 4가 맞는 위치가 2px 어긋나 두 자리가 동시에 확신을 못 얻고 '4'만 읽혔다, 11-05 수집).
        base_left = round(right0 - pitch)
        if base_left < 0:
            break
        base = band[:, base_left:right0]
        if base.size == 0 or int((base > 127).sum()) < _MIN_PX:
            break  # 기준 위치가 빈 칸 → 정수부 끝(옆으로 옮겨 이웃 글자를 줍지 않는다)
        for dx in ((0,) if k == 1 else range(-jitter, jitter + 1)):
            right = right0 + dx
            left = round(right - pitch)
            if left < 0 or right > band.shape[1]:
                continue
            cell = band[:, left:right]
            if cell.size == 0 or int((cell > 127).sum()) < _MIN_PX:
                continue
            ys = np.where((cell > 127).any(axis=1))[0]
            xs = np.where((cell > 127).any(axis=0))[0]
            d, sc = _classify(cell[ys.min():ys.max() + 1, xs.min():xs.max() + 1], templates)
            if d is not None and (best is None or sc > best[1]):
                best = (d, sc)
        if best is None:
            break  # 빈 칸 → 정수부 끝
        digits.append(best[0])
        scores.append(best[1])
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
    """두 번 탐색: 먼저 고정 간격으로, 그 결과가 '확신 2자리 이상'이 아니면 자리마다 조금씩 따로 맞춰 한 번 더.
    ('46.96 %'에서 6과 4가 맞는 위치가 2px 어긋나 '4'만 확신되던 문제, 11-05 수집. 흔한 프레임은 첫 탐색에서 끝나 비용 그대로.)"""
    shifts = tuple(shifts)
    val, score, shift, key = _scan_once(band, w, scale, pitch, templates, shifts, strong, 0)
    if key[0] < 2:
        jitter = max(1, round(pitch * _DIGIT_JITTER))
        val2, score2, shift2, key2 = _scan_once(band, w, scale, pitch, templates, shifts, strong, jitter)
        if key2 > key:
            return val2, score2, shift2
    return val, score, shift


def _scan_once(band, w, scale, pitch, templates, shifts, strong, jitter):
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
        val, score, ndig = _read_at(band, w, _FIRST * scale + shift, pitch, templates, jitter)
        if val is None:
            continue
        strong_digits = ndig if score >= strong else 0
        key = (strong_digits, score)
        if key > best_key:
            best_key, best_val, best_shift = key, val, shift
    return best_val, best_key[1], best_shift, best_key


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


_HINT_BRIGHT = (0.03, 0.40)  # 숫자 칸의 흰 글자 비율(실측 저HP 0.09~0.13, 회색 풍경은 0 또는 통째로 밝음)
_HINT_RED = 0.01  # 왼쪽 60% 숫자 밴드의 빨간 채움 비율(실측 저HP 0.04~0.70)


def low_hp_bar_hint(region_bgr: np.ndarray) -> bool:
    """보스 존재 사전 판정용 저HP 단서: 숫자 칸 flooded + 흰 숫자 글자 + 왼쪽 빨간 채움.

    number_area_flooded만으로는 보스 없는 회색·어두운 풍경도 숫자 칸이 저채도라 통과했다
    (사용자 app.log 11-04: 게임 화면 조각 1010곳 중 100% 오통과 → 비싼 검증 0.5~150ms가 0.3초마다).
    포인셰 저HP 재생에서 판독되는 프레임은 전부 통과, 풍경 오통과는 2.3%(23/1010)."""
    if not number_area_flooded(region_bgr):
        return False
    h, w = region_bgr.shape[:2]
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    y0, y1 = int(h * _YBAND[0]), int(h * _YBAND[1])
    num = hsv[y0:y1, int(w * 0.80):]
    bright = float(((num[:, :, 1] < _SAT_MAX) & (num[:, :, 2] >= _BRIGHT_V)).mean())
    if not (_HINT_BRIGHT[0] <= bright <= _HINT_BRIGHT[1]):
        return False
    left = hsv[y0:y1, : int(w * 0.60)]
    red = ((left[:, :, 0] < 10) | (left[:, :, 0] > 170)) & (left[:, :, 1] > 100) & (left[:, :, 2] > 80)
    return float(red.mean()) >= _HINT_RED


def _low_hp_value(region_bgr, templates, band, w, scale, pitch, span, bright_samples=None) -> int | None:
    """기본 판독이 None일 때의 저HP 보조 판독. 해당 없으면 None(정상 경로 불변)."""
    h = region_bgr.shape[0]
    if not _flooded(_color_mask(region_bgr)[int(h * _YBAND[0]):int(h * _YBAND[1])], w):
        return None  # flooded 아님 → 저HP 아님 → 개입 안 함(판정은 예전 마스크 그대로)
    bband = _bright_mask(region_bgr)[int(h * _YBAND[0]):int(h * _YBAND[1])]
    val, score, _ = _scan(
        bband, w, scale, pitch, templates, range(-span, span + 1), strong=_ACCEPT
    )
    if val is not None and score >= _ACCEPT and val <= _LOW_HP_MAX:
        return _low_hp_aligned(region_bgr, templates, w, scale, pitch, span, val)
    if bright_samples:
        val, score, _ = _scan(bband, w, scale, pitch, bright_samples,
                             range(-span, span + 1), strong=_STRONG)
        if val is not None and score >= _STRONG and val <= _LOW_HP_MAX:
            return val
    return None


def _low_hp_aligned(region_bgr, templates, w, scale, pitch, span, val):
    """저HP 판독을 글자가 실제로 있는 줄에 맞춰 한 번 더 — 늘리기만(1 → 15·13).
    등록 영역이 바보다 몇 px 위로 어긋나면(두 줄 구간 5px 등) 고정 세로 띠(28~82%)가 숫자 아랫부분을 잘라 '15.00'을 1로 읽었다
    (사용자 11-07 '20% 아래가 가끔 1', unknown_hpxxx_show001_upper_197.zip). 정상 위치면 추가 판독 없음."""
    if not USE_TEXT_MASK:
        return val
    h = region_bgr.shape[0]
    bright = _bright_mask(region_bgr)
    rows = np.where((bright[:, int(w * _NUM_LEFT):] > 0).sum(axis=1) >= 3)[0]
    if rows.size == 0:
        return val
    top, bottom = int(rows.min()), int(rows.max())
    y0, y1 = int(h * _YBAND[0]), int(h * _YBAND[1])
    if top >= y0 - 1 and bottom <= y1:
        return val  # 글자가 기본 띠 안 — 그대로
    band = bright[max(0, top - 1):bottom + 2]
    head, best = str(val), None
    for shift in range(-span, span + 1):
        v, sc, _nd = _read_at(band, w, _FIRST * scale + shift, pitch, templates, 0)
        if v is None or v > _LOW_HP_MAX or sc < _ACCEPT:
            continue
        sv = str(v)
        if len(sv) > len(head) and sv.startswith(head) and (best is None or sc > best[1]):
            best = (v, sc)
    return best[0] if best is not None else val


def _prep(region_bgr, templates):
    """공통 전처리. 유효하지 않으면 None."""
    templates = _DIGITS if templates is None else templates
    if region_bgr is None or region_bgr.size == 0 or not templates:
        return None
    if region_bgr.ndim != 3:
        return None
    h, w = region_bgr.shape[:2]
    # 숫자 위치·간격 배율. 게임 보스바는 해상도와 무관하게 37px라, 바보다 높게 잡은 박스(예 40px)에서 h/36으로 키우면
    # 칸 위치가 약 5px 왼쪽으로 예측돼 맞는 정렬이 탐색 범위 밖으로 밀렸다(포인세 46.78·46.86을 4로, 10-13 수집).
    # 그래서 37px보다 높은 박스는 37px 배율로 본다(37px 이하는 예전 그대로). 세로 띠(_YBAND)는 박스 높이 기준 그대로.
    scale = min(h, _UI_H) / _REF_H
    band = _color_mask(region_bgr)[int(h * _YBAND[0]):int(h * _YBAND[1])]
    pitch = _PITCH * scale
    span = max(1, round(_SEARCH * scale))
    return templates, w, scale, band, pitch, span


def _extend(region_bgr, prep, val, frac, want_frac: bool):
    """기본 판독(val, frac)을 회색 바탕 뺀 마스크로 늘리기만 한다 — (val, frac). 바꾸지 않을 땐 그대로."""
    if not USE_TEXT_MASK or val is None or (len(str(val)) >= 3 and (frac is not None or not want_frac)):
        return val, frac
    templates, w, scale, _band, pitch, span = prep
    h = region_bgr.shape[0]
    numbers = (cv2.cvtColor(np.ascontiguousarray(region_bgr[int(h * _YBAND[0]):int(h * _YBAND[1]), int(w * _NUM_LEFT):]),
                            cv2.COLOR_BGR2HSV))
    gray = (numbers[:, :, 1] <= _GRAY_S) & (numbers[:, :, 2] > _GRAY_V[0]) & (numbers[:, :, 2] <= _GRAY_V[1])
    fill = numbers[:, :, 1] >= _FILL_S
    if float(gray.mean()) < _GRAY_MIN or float(fill.mean()) < _GRAY_MIN:
        return val, frac  # 채움 끝이 숫자 칸 안에 없음(대부분 — 수집 867프레임 중 25) — 기본 판독 그대로, 추가 판독 없음
    band = _text_mask(region_bgr)[int(h * _YBAND[0]):int(h * _YBAND[1])]
    shifts = range(-span, span + 1)
    head = str(val)
    best = None
    for shift in shifts:
        v, sc, _nd = _read_at(band, w, _FIRST * scale + shift, pitch, templates, 0)
        if v is None:
            continue
        sv = str(v)
        if (len(sv) > len(head) and sv.startswith(head) and sc >= _PREFIX_MIN) or (sv == head and sc >= _ACCEPT):
            if best is None or (len(sv), sc) > (len(str(best[0])), best[1]):
                best = (v, sc, shift)
    if best is None:
        return val, frac
    v, sc, shift = best
    if v != val:  # 앞자리만 남은 값 → 더 긴 값(정수가 바뀌면 소수도 그 정렬에서)
        return v, (_fraction(band, w, scale, pitch, templates, shift) if want_frac else None)
    if want_frac and frac is None:
        frac = _fraction(band, w, scale, pitch, templates, shift)  # 같은 정수 — 못 읽은 소수만 채움(두 칸 모두 강한 점수일 때만)
    return val, frac


def read_percent(
    region_bgr: np.ndarray,
    templates: dict[str, list[np.ndarray]] | None = None,
    *, bright_samples: dict[str, list[np.ndarray]] | None = None,
) -> int | None:
    """보스 HP바 박스(BGR, 오른쪽 끝 ≈ 바 오른쪽 끝)에서 정수 HP%(0~100)를 읽는다.

    못 읽으면 None(틀린 값보다 안전). 정렬 오프셋을 ±탐색해 가장 확신 높은 판독을
    고르므로, 박스가 몇 px 어긋나도 알아서 맞춰 읽는다.
    """
    bright_samples = (_BRIGHT_SAMPLES if templates is None else {}) if bright_samples is None else bright_samples
    prep = _prep(region_bgr, templates)
    if prep is None:
        return None
    templates, w, scale, band, pitch, span = prep
    val, score, _ = _scan(band, w, scale, pitch, templates, range(-span, span + 1))
    if val is not None and score >= _ACCEPT:
        # 0.31.0: 겨우 맞춘 판독(0.45~0.6)은 값을 쓰지 않는다 — 4K '86.15%'를 '8'(0.59)로 읽어 패턴 알림이
        # 거짓으로 울릴 뻔했다. 틀린 값 대신 못 읽음(자동 찾기 검증과 같은 하한).
        _LAST.key = _key(val, score) if score >= VALUE_MIN_SCORE else NO_KEY
        if score < VALUE_MIN_SCORE:
            return None
        return _extend(region_bgr, prep, val, None, False)[0]
    low = _low_hp_value(region_bgr, templates, band, w, scale, pitch, span, bright_samples)
    _LAST.key = (0, 0.0) if low is not None else NO_KEY
    return low


def read_percent_scored(region_bgr: np.ndarray, templates=None) -> tuple[int | None, tuple[int, float]]:
    """read_percent와 같은 판독 + 확신 키(확신 자리수, 최저 자리 점수) — 세로 위치 후보 중 고를 때 쓴다(보스바 오버레이 두 줄 구간)."""
    val = read_percent(region_bgr, templates)  # 같은 판독(저HP 보조 포함) — 확신 키는 그 판독이 남긴 것
    return val, last_key()


# 소수 두 자리(보스바 오버레이 표시용, 사용자 확정 11-05) — 정수 판독 경로·결과는 그대로, 같은 글꼴·같은 숫자 샘플.
# 'XX.YY %'에서 정수 일의 자리 오른쪽 끝 + '.'(약 4px) 뒤 두 칸. 칸 위치가 프레임마다 2~6px 흔들려 첫 칸은 1~7px, 둘째 칸은 첫 칸 기준 ±3px로 맞춘다.
# 두 칸 모두 _STRONG(0.85) 이상일 때만 — 하나라도 낮으면 None(틀린 소수 대신 정수만). 저HP(빨간 바, 밝기 마스크 경로)는 샘플이 맞지 않아 소수 없음.
_FRAC_GAP = range(1, 8)
_FRAC_JITTER = 3


def _cell_digit(band, right, pitch, templates):
    left, right = round(right - pitch), round(right)
    if left < 0 or right > band.shape[1]:
        return None
    cell = band[:, left:right]
    if int((cell > 127).sum()) < _MIN_PX:
        return None
    ys = np.where((cell > 127).any(axis=1))[0]
    xs = np.where((cell > 127).any(axis=0))[0]
    d, sc = _classify(cell[ys.min():ys.max() + 1, xs.min():xs.max() + 1], templates)
    return None if d is None else (d, sc)


def _fraction(band, w, scale, pitch, templates, shift) -> str | None:
    units_right = w - (_FIRST * scale + shift)
    first = None
    for gap in _FRAC_GAP:
        right = units_right + gap * scale + pitch
        got = _cell_digit(band, right, pitch, templates)
        if got is not None and (first is None or got[1] > first[1]):
            first = (got[0], got[1], right)
    if first is None or first[1] < _STRONG:
        return None
    second = None
    for dj in range(-_FRAC_JITTER, _FRAC_JITTER + 1):
        got = _cell_digit(band, first[2] + pitch + dj, pitch, templates)
        if got is not None and (second is None or got[1] > second[1]):
            second = got
    if second is None or second[1] < _STRONG:
        return None
    return first[0] + second[0]


def read_percent_frac(
    region_bgr: np.ndarray,
    templates: dict[str, list[np.ndarray]] | None = None,
    *, bright_samples: dict[str, list[np.ndarray]] | None = None,
) -> tuple[int | None, str | None]:
    """(read_percent와 같은 정수, 소수 두 자리 글자 또는 None). 소수는 보스바 오버레이 표시용 — 경고 판정은 정수만 쓴다."""
    bright_samples = (_BRIGHT_SAMPLES if templates is None else {}) if bright_samples is None else bright_samples
    prep = _prep(region_bgr, templates)
    if prep is None:
        return None, None
    templates, w, scale, band, pitch, span = prep
    val, score, shift = _scan(band, w, scale, pitch, templates, range(-span, span + 1))
    if val is not None and score >= _ACCEPT:
        if score < VALUE_MIN_SCORE:
            _LAST.key = NO_KEY
            return None, None
        _LAST.key = _key(val, score)
        return _extend(region_bgr, prep, val, _fraction(band, w, scale, pitch, templates, shift), True)
    low = _low_hp_value(region_bgr, templates, band, w, scale, pitch, span, bright_samples)
    _LAST.key = (0, 0.0) if low is not None else NO_KEY
    return low, None


def main_path_score(
    region_bgr: np.ndarray, templates: dict[str, list[np.ndarray]] | None = None,
) -> float | None:
    """read_percent 기본 경로(채도 마스크)의 최고 정렬 점수. 기본 경로로 못 읽으면 None(저HP 보조 경로 등).

    자동 찾기 검증용: _ACCEPT(0.45)는 실행 중 판독용으로 낮게 둔 값이라, 글자 위치·모양이 기준과
    다른 화면(0.30.1 4K 자료 10-11 123333: 100.00%를 30으로, 점수 0.48)을 보스바로 확정하지 않게 한다."""
    prep = _prep(region_bgr, templates)
    if prep is None:
        return None
    templates, w, scale, band, pitch, span = prep
    val, score, _ = _scan(band, w, scale, pitch, templates, range(-span, span + 1))
    return score if val is not None and score >= _ACCEPT else None


def read_percent_cached(
    region_bgr: np.ndarray,
    templates: dict[str, list[np.ndarray]] | None = None,
    hint: int | None = None,
    *, bright_samples: dict[str, list[np.ndarray]] | None = None,
) -> tuple[int | None, int | None]:
    """read_percent와 '있음/없음(None 여부)'은 동일하되 빠른 버전 — (값, 당첨 오프셋).

    바의 오른쪽 끝은 영역 안에서 고정이라 당첨 오프셋이 매 프레임 거의 같다. 그래서
    직전 당첨 오프셋(hint)만 먼저 보고, 실패하면 ±1, 그래도 실패하면 전체 탐색으로
    폴백한다(단계식). 전체 탐색을 항상 포함하므로 '있음/없음' 결과는 read_percent와
    완전히 같고(폴백 보장), 흔한 경우(힌트 적중)만 17배 빨라진다. 디버프 3차 전용 —
    보스패턴알림은 값을 쓰므로 read_percent(전체 탐색)를 그대로 쓴다.
    """
    bright_samples = (_BRIGHT_SAMPLES if templates is None else {}) if bright_samples is None else bright_samples
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
    low = _low_hp_value(region_bgr, templates, band, w, scale, pitch, span, bright_samples)
    return (low, None) if low is not None else (None, None)
