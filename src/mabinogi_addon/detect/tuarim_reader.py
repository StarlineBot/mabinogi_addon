"""투아림 % 숫자 판독 (NCC 최근접 이웃).

투아림 % 숫자는 **밝은 게이지(분홍빛) 위**에 얹혀 있어 글자·배경 모두 밝다(저대비).
게다가 전투 이펙트로 프레임마다 배경 밝기가 변한다. 그래서 "밝기 임계 이진화 +
평균 템플릿 1개" 방식은 두 자리(특히 90%대)에서 무너진다.

대신 실게임 캡처로 만든 **레퍼런스 뱅크**(숫자별 여러 장)에 대해 정규화 상관(NCC)
최근접 이웃으로 각 자리 숫자를 고른다. 대비 정규화(평균 빼고 표준편차로 나눔) 덕에
배경 밝기가 변해도 글자 모양만 비교된다.

- 입력 영역은 높이를 13px로 맞춰(해상도 차 흡수) V=max(B,G,R) 채널로 본다.
- 숫자는 오른쪽 정렬이고 맨 오른쪽이 '%'. '%' 오른쪽 끝(R)을 기준으로 일/십의 자리
  칸을 고정 오프셋으로 자른다(실측값).
- 레퍼런스: detect/templates/tuarim/refs.npz (Ro/Lo=일의 자리, Rt/Lt=십의 자리).
  `tests/data/tuarim_shots`의 실캡처로 scripts로 재생성한다(라벨은 0→100 단조 순서).
"""

from __future__ import annotations

import cv2
import numpy as np

from .. import paths

_REFS_PATH = paths.detect_templates_dir() / "tuarim" / "refs.npz"

CH, CW = 13, 8  # 셀 표준 크기(높이 13 정규화)
# '%' 오른쪽 끝(R) 기준 자리 칸 오프셋(실측). ones=일의 자리, tens=십의 자리.
_ONES = (-17, -9)
_TENS = (-25, -17)
_TENS_INK_MIN = 5  # 십의 자리 칸에 이만큼 잉크가 있어야 '두 자리'로 본다
NCC_MIN = 0.30  # 최근접 상관이 이보다 낮으면 판독 포기(None)
# 십의 자리는 '두 자리냐'를 가르는 자리라 더 엄격히 본다. 실게임 재측정: 진짜 십의
# 자리는 NCC≈1.0, 한 자리 값(예 5%)에 게이지·배경 잡음이 십의 자리 칸에 끼어 가짜로
# 분류되는 경우는 ≤0.49. 그 사이로 임계를 올려 '5%→95%' 같은 가짜 두 자리(→거짓 알림)를
# 막는다. (일의 자리는 NCC_MIN 유지)
_TENS_NCC_MIN = 0.6
# R(‘%’ 끝) 자동정렬 스캔 폭(px, 정규화 폭 기준). 관측된 밀림은 ~3px이고, 자리 피치(~8px)
# 보다 작아야 옆 자리로 건너뛰지 않는다.
_R_SCAN = 4


def _load_refs():
    if not _REFS_PATH.exists():
        return None
    try:
        d = np.load(_REFS_PATH)
        return (
            d["Ro"].astype(np.float32),
            d["Lo"].astype(np.int64),
            d["Rt"].astype(np.float32),
            d["Lt"].astype(np.int64),
        )
    except Exception:  # noqa: BLE001 — 레퍼런스 손상 시 판독 비활성(None)
        return None


_REFS = _load_refs()


def _binarize(v: np.ndarray) -> np.ndarray:
    """프레임별 적응형: 밝은 글자 속칠만 남긴다(배경 밝기 무관하게 R 위치 찾기용)."""
    t = int(np.percentile(v, 98) * 0.85)
    _, b = cv2.threshold(v.astype(np.uint8), t, 255, cv2.THRESH_BINARY)
    return b


def _prep(region_bgr: np.ndarray) -> np.ndarray | None:
    if region_bgr is None or region_bgr.size == 0:
        return None
    h, w = region_bgr.shape[:2]
    if h < 2 or w < 2:
        return None
    nw = max(2, round(w * CH / h))
    im = cv2.resize(region_bgr, (nw, CH))
    return im.max(axis=2).astype(np.float32)


def _cell(v: np.ndarray, r: int, span: tuple[int, int]) -> np.ndarray:
    a = max(0, r + span[0])
    b = min(v.shape[1], r + span[1])
    seg = v[:, a:b] if b > a else v[:, :0]
    out = np.zeros((CH, CW), np.float32)
    if seg.shape[1]:
        out[:, : min(CW, seg.shape[1])] = seg[:, :CW]
    return out


def _norm(cell: np.ndarray) -> np.ndarray:
    c = cell - cell.mean()
    s = c.std()
    return (c / s if s > 1e-5 else c).ravel().astype(np.float32)


def _classify(vec: np.ndarray, refs: np.ndarray, labels: np.ndarray):
    """정규화 상관 최근접 이웃. (라벨, 점수) 또는 (None, score)."""
    if refs.size == 0:
        return None, -1.0
    scores = refs @ vec / vec.size  # 정규화돼 있어 내적/표본수 ≈ 상관계수
    k = int(scores.argmax())
    return int(labels[k]), float(scores[k])


def read_percent(
    region_bgr: np.ndarray,
    templates: dict[str, np.ndarray] | None = None,  # 하위호환(무시)
    threshold: float = NCC_MIN,
) -> int | None:
    """리더 박스 영역에서 % 정수(0~100)를 읽는다. 못 읽으면 None.

    `templates`는 과거 시그니처 호환용으로 남겨뒀고 더는 쓰지 않는다(레퍼런스 뱅크 사용).
    """
    if _REFS is None:
        return None
    v = _prep(region_bgr)
    if v is None:
        return None
    b = _binarize(v)
    cols = np.where((b > 0).any(axis=0))[0]
    if len(cols) == 0:
        return None
    rmax = int(cols[-1])  # '%' 오른쪽 끝(가장 오른쪽 밝은 열) — 후보 시작점
    Ro, Lo, Rt, Lt = _REFS

    # R 자동정렬: 전투 이펙트로 배경이 밝아지면 '가장 오른쪽 밝은 열'이 진짜 '%' 끝이 아니라
    # 크롭 가장자리로 몇 px 밀려(관측 3px), 자리 칸이 통째로 어긋나 98을 3으로 오독한다.
    # rmax에서 좌로 조금(자리 피치보다 작게) 훑어 '일의 자리 NCC가 가장 높은' 열을 R로 쓴다.
    # 올바른 R은 일의 자리가 또렷해 고점수(≈0.9), 밀린 R은 엉뚱한 칸이라 저점수(≈0.45)다.
    r, ones_d, ones_s = rmax, None, -1.0
    for rr in range(rmax, max(rmax - _R_SCAN, 1), -1):
        od, os_ = _classify(_norm(_cell(v, rr, _ONES)), Ro, Lo)
        if od is not None and os_ > ones_s:
            r, ones_d, ones_s = rr, od, os_
    if ones_d is None or ones_s < threshold:
        return None

    tens_ink = int((b[:, max(0, r + _TENS[0]) : max(0, r + _TENS[1])] > 0).sum())
    if tens_ink >= _TENS_INK_MIN:
        tens_cell = _norm(_cell(v, r, _TENS))
        # 십의 자리가 '0' 글자면 100%가 영역에 '1'이 잘려 "00"으로 보이는 것이다('0X%'인 실제
        # 값은 없다). 십의 자리 뱅크엔 0이 없어 이 '0'을 8/9로 오분류하므로(→80/90 거짓 알림),
        # 0이 포함된 '일의 자리 뱅크'로 한 번 더 대조해 '0'이면 100으로 본다(실제 80/90은
        # 십의 자리가 8/9라 여기 안 걸린다).
        z_d, z_s = _classify(tens_cell, Ro, Lo)
        if z_d == 0 and z_s >= _TENS_NCC_MIN:
            return 100
        tens_d, tens_s = _classify(tens_cell, Rt, Lt)
        if tens_d is not None and tens_s >= max(threshold, _TENS_NCC_MIN):
            value = tens_d * 10 + ones_d
            return value if 0 <= value <= 100 else None
    return ones_d
