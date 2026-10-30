"""시간 판독 (기획서 4.3).

시간 글자 영역을 이진화한 뒤, 숫자(0~9)·단위(일/시간/분/초) 템플릿을 matchTemplate으로
찾아 x 순서로 정렬 → 토큰 파싱 → 총 초로 환산한다. 한글 음절 자모 간격 때문에 열 분할
대신 글자별 템플릿 매칭을 쓴다(간격 무관).
"""

from __future__ import annotations

import itertools

import cv2
import numpy as np

from .. import paths
from ..image_io import imread
from .binarize import binarize

_TEMPLATE_DIR = paths.detect_templates_dir() / "time"

# 단위 라벨 → 초. 숫자 라벨은 "0".."9".
_UNIT_SECONDS = {"day": 86400, "hour": 3600, "bun": 60, "cho": 1}

# 글자 매칭 임계. 이진 템플릿이라 정답은 ~1.0, 오답은 낮다.
GLYPH_THRESHOLD = 0.7
# 세트별 평균 점수 하한. 4K 세트(uhd)는 그 화면에서 그대로 뜬 글자라 맞으면 0.9+이고,
# 다른 렌더링에 겨우 맞으면 0.7대로 틀린 값을 낸다(213520의 '2분 10초'를 8px 글자로 120) → 못 읽음으로.
# 기본·scaled 세트는 빨간 시간(임박)이 0.7대로 맞게 읽히므로 하한을 두지 않는다.
MIN_CONFIDENCE = {"uhd": 0.9}


def _label(key: str) -> str:
    """템플릿 키 → 글자 라벨. 같은 글자의 다른 모양(변형)은 '2~2.png'처럼 '~' 뒤를 붙여 둔다(4K 세트)."""
    return key.split("~", 1)[0]


def _load_templates(d: object | None = None) -> dict[str, np.ndarray]:
    """디렉터리의 *.png 를 {키: 이미지}로. 기본은 time 루트(개발자 세트). 키의 라벨은 _label."""
    folder = _TEMPLATE_DIR if d is None else d
    return {
        path.stem: imread(path, cv2.IMREAD_GRAYSCALE)
        for path in sorted(folder.glob("*.png"))
    }


def _load_sets() -> dict[str, dict[str, np.ndarray]]:
    """여러 템플릿 '세트'를 로드한다.

    time 루트의 느슨한 *.png = 기본 세트("default", 개발자 네이티브 렌더링).
    time/<이름>/*.png 하위폴더 = 추가 세트(다른 해상도·스케일링 렌더링).
    게임 UI 글자(7px)는 모니터·스케일링에 따라 픽셀 패턴이 달라 한 세트로는 전부
    못 맞춘다. 실행 중 세트별로 읽어보고 가장 잘 맞는 세트를 고른다(engine).
    - scaled: 울트라와이드 레터박스 스케일링(테스터 화면)
    - uhd(0.30.1): 4K에서 시간 글자만 늘어나 그려진 화면(8px, 9px 굵게 뭉침 — 한 장 안에서도 섞임).
      리샘플링 위상·굵기·글자색(빨간 시간)에 따라 같은 숫자도 모양이 달라 변형(~2 …)을 한 세트에 모은다
      (8px·9px를 세트로 나누면 고정된 쪽만 읽혀서). 4K 자료(image55·mabinogi_2026_10_30_*)에서 떴다.
      자료에 없던 숫자(8)나 모양은 못 읽고 None — 틀린 값 대신(_unexplained_ink).
    """
    sets: dict[str, dict[str, np.ndarray]] = {}
    base = _load_templates(_TEMPLATE_DIR)
    if base:
        sets["default"] = base
    for sub in sorted(p for p in _TEMPLATE_DIR.iterdir() if p.is_dir()):
        s = _load_templates(sub)
        if s:
            sets[sub.name] = s
    return sets


_SETS = _load_sets()
_TEMPLATES = _SETS.get("default", {})  # 하위호환: 기존 참조/테스트용 기본 세트


def set_names() -> list[str]:
    """로드된 템플릿 세트 이름들(기본 세트 포함)."""
    return list(_SETS)


def _occurrences(strip: np.ndarray, label: str, template: np.ndarray, threshold: float):
    """strip에서 template이 threshold 이상인 위치들을 (x, score, label, width)로.

    같은 글자가 여러 번(예: '22') 나오므로, 찾을 때마다 주변을 눌러 반복 검출.
    """
    if template.shape[0] > strip.shape[0] or template.shape[1] > strip.shape[1]:
        return []
    result = cv2.matchTemplate(strip, template, cv2.TM_CCOEFF_NORMED)
    h, w = template.shape[:2]
    found = []
    while True:
        _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(result)
        if max_v < threshold:
            break
        x, y = max_l
        found.append((x, float(max_v), _label(label), w))
        x0, y0 = max(0, x - w // 2), max(0, y - h // 2)
        result[y0 : y + h // 2 + 1, x0 : x + w // 2 + 1] = -1.0  # 주변 억제
    return found


def _nms(hits):
    """같은 위치에 겹친 서로 다른 글자 후보 중 점수 높은 것만 남긴다."""
    hits.sort(key=lambda o: -o[1])
    kept: list[tuple[int, float, str, int]] = []
    for x, score, label, w in hits:
        center = x + w / 2
        if any(abs(center - (kx + kw / 2)) < max(w, kw) * 0.5 for kx, _, _, kw in kept):
            continue
        kept.append((x, score, label, w))
    kept.sort(key=lambda o: o[0])  # x 오름차순
    return kept


def _parse(labels: list[str]) -> int | None:
    """['3','day','2','2','hour','1','bun'] → 초. 단위 앞의 숫자들을 모아 곱한다.

    단위 앞에 숫자가 없으면(숫자를 못 읽고 '분'·'초'만 맞음) 그 줄은 읽지 못한 것(None)이다.
    예전엔 0으로 더해 '0초'가 되어, 시간 있는 버프가 곧 끝나는 것처럼 알림이 반복됐다(0.30.1 QA, image55).
    """
    total = 0
    number: int | None = None
    for label in labels:
        if label.isdigit():
            number = (number or 0) * 10 + int(label)
        elif label in _UNIT_SECONDS:
            if number is None:
                return None
            total += number * _UNIT_SECONDS[label]
            number = None
    return total


# 이 이상 x가 벌어지면 '다른 덩어리'로 본다(버프 이름과 시간 사이의 공백).
_CLUSTER_GAP = 14


def _time_entries(kept: list) -> list:
    """글자들을 x간격으로 덩어리로 묶고, '단위(분/초/시간/일)를 포함한 덩어리'만 남긴다.

    시간은 오른쪽 정렬이라 숫자+단위가 한 덩어리로 뭉쳐 있다. 반면 버프 이름이 길어
    시간 영역(time_x0 오른쪽)까지 넘어오면, 이름 끝 획이 '1' 등으로 오인돼 실제 분
    앞에 붙는다(예: 2분 → 12분, +10분). 단위가 없는 고립 덩어리(=이름 획)를 버려
    이를 막는다. kept는 (x, score, label, w)의 x오름차순 리스트. 반환은 유지된 항목들.
    """
    if not kept:
        return []
    clusters: list[list] = [[kept[0]]]
    for prev, cur in itertools.pairwise(kept):
        if cur[0] - (prev[0] + prev[3]) > _CLUSTER_GAP:
            clusters.append([cur])
        else:
            clusters[-1].append(cur)
    out: list = []
    for c in clusters:
        if any(lab in _UNIT_SECONDS for _x, _s, lab, _w in c):
            out.extend(c)
    return out


def _time_labels(kept: list) -> list[str]:
    return [lab for _x, _s, lab, _w in _time_entries(kept)]


def _read(strip: np.ndarray, templates: dict, threshold: float, min_conf: float = 0.0):
    """이진화된 strip을 주어진 세트로 읽어 (초값|None, 신뢰도)를 돌려준다.

    신뢰도 = 시간에 기여한 글자들의 평균 매칭 점수. 세트가 렌더링과 맞으면 ~0.9+,
    안 맞으면 보통 파싱 실패(None, 0.0)라 세트 자동선택의 신호로 쓴다.
    """
    hits: list = []
    for label, template in templates.items():
        hits.extend(_occurrences(strip, label, template, threshold))
    if not hits:
        return None, 0.0
    ents = _time_entries(_nms(hits))
    units = [i for i, e in enumerate(ents) if e[2] in _UNIT_SECONDS]
    ents = ents[:units[-1] + 1] if units else []  # 마지막 단위 뒤(패널 테두리 세로선이 '1'로 잡히는 등)는 시간이 아님
    if not ents or _unexplained_ink(strip, ents):
        return None, 0.0
    value = _parse([e[2] for e in ents])
    if value is None:
        return None, 0.0
    conf = sum(e[1] for e in ents) / len(ents)
    if conf < min_conf:
        return None, 0.0  # 렌더링과 안 맞는 세트로 겨우 맞춘 값(예: '2분 10초'를 120으로) — 틀리게 읽느니 못 읽음
    return value, conf


# 시간 덩어리 왼쪽에서 못 읽은 글자를 찾는 거리 = 덩어리를 나누는 간격과 같게(이보다 가까우면 같은 시간 글자).
_LEFT_REACH = _CLUSTER_GAP
# 오른쪽은 단위 뒤 다음 글자까지 간격(약 5px)만 본다 — 더 가면 패널 테두리 세로선에 닿는다(4K 줄에서 +14px).
_RIGHT_REACH = 8


def _unexplained_ink(strip: np.ndarray, ents: list) -> bool:
    """시간 덩어리 안(과 바로 왼쪽)에 어느 글자 템플릿도 설명하지 못한 잉크 열이 있으면 True.

    세트에 없는 숫자(예: '18분'의 8)를 건너뛰면 '1분'처럼 틀린 값이 나오므로, 그런 줄은 읽지 못한 것으로 둔다.
    맞은 글자들의 세로 범위만 본다(위아래 구분선·이름 획 아래 잡티 제외).
    """
    x0 = max(0, ents[0][0] - _LEFT_REACH)
    end = max(x + w for x, _s, _l, w in ents)
    x1 = min(strip.shape[1], end + _RIGHT_REACH)  # 마지막 단위 뒤에 붙은 못 읽은 글자('4분 49초'의 49초)
    covered = np.zeros(x1 - x0, bool)
    for x, _s, _l, w in ents:
        covered[x - x0:x + w - x0] = True
    ink = strip[:, x0:x1].max(axis=0) > 0
    # 왼쪽 끝에서 잉크가 이름까지 이어진 경우는 이름(덩어리 간격 미만으로 붙은 이름 획)이라 보지 않는다
    left = ink[:ents[0][0] - x0]
    if left.any():
        gap = np.where(left)[0]
        if gap[0] == 0:  # 범위 시작부터 잉크 = 이름이 계속됨 → 마지막 빈 열 뒤만 본다
            blank = np.where(~left)[0]
            ink[:blank[-1] + 1 if blank.size else len(left)] = False
    # 굵게 뭉친 4K 글자(9px)는 템플릿 옆으로 1~2열 삐져나와 이웃 글자와 붙는다(번짐).
    # 못 읽은 글자 = 3열 이상이거나, 맞은 글자와 떨어져 홀로 선 2열 이상(가장 좁은 숫자 '1'이 2열).
    held = ink & covered
    loose = np.concatenate(([False], ink & ~covered, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(loose))
    for a, b in zip(edges[::2], edges[1::2]):
        attached = (a > 0 and held[a - 1]) or (b < len(held) and held[b])
        if b - a >= 3 or (b - a >= 2 and not attached):
            return True
    return False


def read_time(
    time_bgr: np.ndarray,
    threshold: float = GLYPH_THRESHOLD,
    set_name: str | None = None,
) -> int | None:
    """시간 영역(BGR)에서 남은 시간을 초로. 글자를 못 찾으면 None.

    set_name으로 특정 템플릿 세트를 지정할 수 있다(기본은 'default'=개발자 세트).
    """
    templates = _SETS.get(set_name, _TEMPLATES) if set_name else _TEMPLATES
    if not templates:
        return None
    return _read(binarize(time_bgr), templates, threshold, MIN_CONFIDENCE.get(set_name or "default", 0.0))[0]


def score_sets(time_bgr: np.ndarray, threshold: float = GLYPH_THRESHOLD) -> dict:
    """모든 세트로 읽어 {세트이름: (초값|None, 신뢰도)}. 세트 자동선택용."""
    strip = binarize(time_bgr)
    return {name: _read(strip, tm, threshold, MIN_CONFIDENCE.get(name, 0.0)) for name, tm in _SETS.items()}
