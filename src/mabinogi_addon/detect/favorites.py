"""상태목록창 즐겨찾기 칸 읽기 (기획서 3.1.1).

상태목록창 위쪽, 얇은 가로 구분선 위가 즐겨찾기 칸이다. 즐겨찾기한 버프는 아래 목록에서 빠져
위 칸에 고정되고, 꺼지면 줄이 남은 채 회색(이름 글자가 회색)이 된다.

- 경계는 **구분선 자체**로만 정한다. 줄 밝기로 즐겨찾기 끝을 추정하면 목록 맨 위 버프가
  30초 이하에서 점멸·반투명일 때 흐린 즐겨찾기 줄로 오인한다(사용자 지적).
- 구분선 위치는 기억하고, 그 자리에서 선이 안 보일 때만 다시 찾는다. 새 위치로 옮기는 것은
  여러 프레임 연속 같은 위치가 보일 때만(맵 이동·이펙트로 화면이 순간 까매지거나 하얘지는 프레임 대비).
- 즐겨찾기 줄 → 버프는 처음 한 번 아이콘으로 맞춰 기억하고, 매 판독은 그 줄의 켜짐/꺼짐만 본다.
  줄 아이콘이 기억과 맞지 않으면(게임에서 순서를 바꿈) 자동으로 다시 맞춘다.
- 켜짐/꺼짐은 이름 글자색으로 본다: 켜짐 = 흰 글자(255), 꺼짐 = 회색 글자(최대 127). 반투명 배경이
  밝아도(사막) 회색 글자는 127을 넘지 않아 아이콘 밝기보다 안정적이다(tests/data 실측).

모두 순수 함수/클래스(맥에서 테스트 가능). 이미지 처리는 numpy 벡터 연산만 쓴다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from .icon_matcher import match_icon

_log = logging.getLogger("mabinogi_addon.favorites")

# 구분선: 위·아래 배경보다 어두운(약 40%) 1~2px 가로선이 영역 너비 대부분을 가로지른다.
_LINE_RATIO = 0.75  # 선 밝기 ≤ 주변 × 이 값
_LINE_MIN_DIFF = 1.5  # 아주 어두운 장면의 잡음 배제(가로 평균 후 밝기 차)
_LINE_MIN_FRAC = 0.8  # 가운데 너비 중 이 비율 이상이 어두워야 선
_LINE_SPAN = (0.08, 0.92)  # 선을 보는 가로 범위(영역 양끝 여백 제외)
_VISIBLE_BG = 20.0  # 주변이 이보다 밝은데 선이 없으면 '선이 정말 없음'(그보다 어두우면 판단 보류)

FAV_MATCH_THRESHOLD = 0.7  # 꺼진(회색) 아이콘도 켜진 템플릿과 0.79~1.0으로 맞음(실측) → 목록보다 낮게
VERIFY_THRESHOLD = 0.6  # 기억한 줄 아이콘이 이 아래면 순서가 바뀐 것으로 보고 다시 맞춤
_ON_LEVEL = 200  # 이름 글자 최대 채널이 이 이상인 픽셀 = 흰 글자
_ON_MIN_PIXELS = 6
_TEXT_WIDTH = 100  # 아이콘 오른쪽 이름 영역 너비(오른쪽 남은 시간 숫자는 제외)


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def _line_scores(gray: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """행 ys마다 (선 판정 비율, 주변 밝기 중앙값). ys는 4 ≤ y < h-6 범위."""
    g = cv2.blur(gray.astype(np.float32), (9, 1))
    w = g.shape[1]
    c = g[:, int(w * _LINE_SPAN[0]):max(int(w * _LINE_SPAN[0]) + 1, int(w * _LINE_SPAN[1]))]
    line = np.minimum(c[ys], (c[ys] + c[ys + 1]) / 2)  # 1px·2px 선 모두
    above = (c[ys - 4] + c[ys - 3] + c[ys - 2]) / 3
    below = (c[ys + 3] + c[ys + 4] + c[ys + 5]) / 3
    nb = np.minimum(above, below)
    dark = (line <= nb * _LINE_RATIO) & (nb - line >= _LINE_MIN_DIFF)
    return dark.mean(axis=1), np.median(nb, axis=1)


def find_separators(gray: np.ndarray) -> list[int]:
    """구분선 후보의 y(선 윗줄) 목록, 위에서부터. 붙은 행은 하나로 묶는다."""
    gray = _gray(gray)
    h = gray.shape[0]
    if h < 12 or gray.shape[1] < 20:
        return []
    ys = np.arange(4, h - 6)
    frac, _ = _line_scores(gray, ys)
    hits = ys[frac >= _LINE_MIN_FRAC]
    if hits.size == 0:
        return []
    out: list[int] = []
    group = [int(hits[0])]
    for y in hits[1:]:
        if y - group[-1] <= 2:
            group.append(int(y))
        else:
            out.append(_best(group, frac, ys))
            group = [int(y)]
    out.append(_best(group, frac, ys))
    return out


def _best(group: list[int], frac: np.ndarray, ys: np.ndarray) -> int:
    return max(group, key=lambda y: (frac[y - ys[0]], -y))


def line_state(gray: np.ndarray, y: int) -> bool | None:
    """기억한 y(±1)에 선이 보이면 True, 주변이 밝은데 선이 없으면 False, 너무 어두워 모르면 None."""
    gray = _gray(gray)
    h = gray.shape[0]
    ys = np.array([v for v in (y - 1, y, y + 1) if 4 <= v < h - 6])
    if ys.size == 0:
        return False
    top = int(ys[0]) - 4  # 가로 평균만 쓰므로 선 주변 몇 줄만 잘라 계산(매 프레임 비용 최소)
    frac, nb = _line_scores(gray[top:int(ys[-1]) + 7], ys - top)
    if float(frac.max()) >= _LINE_MIN_FRAC:
        return True
    return False if float(nb.max()) >= _VISIBLE_BG else None


MAX_ROWS = 16  # 즐겨찾기 칸 최대 줄 수(테두리 탐색 범위)


def panel_top(gray: np.ndarray, bottom: int, pitch: int = 24) -> int | None:
    """구분선(bottom) 위 MAX_ROWS줄 안에서 상태목록창 위 테두리(위는 밝고 아래는 어두워지는 가로 경계) y.
    안 보이면 None(어두운 맵에서 멀리 있는 다른 경계를 테두리로 잡지 않게 범위를 제한)."""
    gray = _gray(gray)
    if bottom < 8 or gray.shape[1] < 20:
        return None
    g = cv2.blur(gray[:bottom].astype(np.float32), (9, 1))
    w = g.shape[1]
    c = g[:, int(w * _LINE_SPAN[0]):int(w * _LINE_SPAN[1])]
    ys = np.arange(max(4, bottom - MAX_ROWS * pitch - 4), bottom - 4)
    if ys.size == 0:
        return None
    above = (c[ys - 4] + c[ys - 3] + c[ys - 2]) / 3
    below = (c[ys + 1] + c[ys + 2] + c[ys + 3]) / 3
    frac = ((below <= above * 0.8) & (above - below >= 3)).mean(axis=1)
    hits = ys[frac >= 0.8]
    return int(hits[-1]) if hits.size else None


def count_rows(gray: np.ndarray, bottom: int, rows: dict, pitch: int) -> int | None:
    """즐겨찾기 칸 줄 수. 창 위 테두리가 보이면 (구분선 − 테두리) ÷ 줄 간격, 안 보이면 기억한 맨 윗줄까지.
    둘 다 없으면 None(너무 어두워 모름)."""
    top = panel_top(gray, bottom, pitch)
    # 0.31.1: 기억한 즐겨찾기 줄이 '테두리'보다 위에 있으면 그건 테두리가 아니다(창 모드 wireweb_3: 칸 안 바닥 금을
    # 테두리로 잡아 1줄) — 줄 기준으로 센다.
    if top is not None and not any(row.y < top for row in rows.values()):
        return max(0, (bottom - top) // pitch)
    if rows:
        return max(round((bottom - row.y) / pitch) for row in rows.values())
    return None


def row_is_on(region: np.ndarray, x: int, y: int, size: int) -> bool:
    """아이콘(x,y,크기) 오른쪽 이름 글자가 흰색이면 켜짐."""
    if region.ndim != 3:
        return False
    text = region[max(0, y):y + size, x + size + 2:x + size + 2 + _TEXT_WIDTH]
    if text.size == 0:
        return False
    return int(np.count_nonzero(text.max(axis=2) >= _ON_LEVEL)) >= _ON_MIN_PIXELS


@dataclass(frozen=True)
class FavoriteRow:
    buff_id: str
    x: int
    y: int
    size: int


def map_rows(gray: np.ndarray, templates: dict[str, np.ndarray], icon_column: tuple[int, int],
             bottom: int, threshold: float = FAV_MATCH_THRESHOLD) -> dict[str, FavoriteRow]:
    """구분선 위(0~bottom) 줄을 등록 버프 아이콘과 맞춘다. 등록 안 된 줄은 무시, 한 줄에 버프 하나."""
    gray = _gray(gray)
    x0, x1 = icon_column
    strip = gray[:max(0, bottom), x0:x1]
    found: list[tuple[float, str, int, int, int]] = []
    for bid, template in templates.items():
        t = _gray(template)
        result = match_icon(strip, t)
        if result.score >= threshold:
            found.append((result.score, bid, x0 + result.x, result.y, t.shape[0]))
    rows: dict[str, FavoriteRow] = {}
    for score, bid, x, y, size in sorted(found, reverse=True):
        if all(abs(row.y - y) >= size // 2 for row in rows.values()):
            rows[bid] = FavoriteRow(bid, x, y, size)
    return rows


class FavoritesReader:
    """매 프레임: 구분선 위치 유지 → 선 위 줄의 켜짐/꺼짐. 선이 없으면 즐겨찾기 없음(전체가 목록)."""

    CONFIRM_FRAMES = 4  # 새 선 위치를 받아들이기 전 연속 확인 프레임
    FORGET_FRAMES = 40  # 밝은 배경에서 기억한 자리에 선이 이만큼 연속으로 없으면 잊음(즐겨찾기 모두 해제)
    SCAN_EVERY = 5  # 기억한 선이 안 보일 때 전체 탐색 간격(프레임)

    def __init__(self, templates: dict[str, np.ndarray], icon_column: tuple[int, int],
                 separator: int | None = None) -> None:
        self._templates = templates
        self._icon_column = icon_column
        # separator: 지난 실행에서 확인해 영역 기준으로 저장한 구분선 y(0.33.0). 첫 프레임부터 쓴다 —
        # 아주 어두운 맵에서 켜면 선을 못 찾아 전체를 목록으로 읽고 꺼진 즐겨찾기를 '있음'으로 보던 한계 대비.
        # 그 자리에 선이 계속 안 보이면 평소처럼 잊는다(FORGET_FRAMES).
        self.separator: int | None = separator
        self.rows: dict[str, FavoriteRow] = {}
        self.on: dict[str, bool] = {}
        self.row_count: int | None = 0
        self._pending: int | None = None
        self._pending_count = 0
        self._gone = 0
        self._frame = 0

    @property
    def boundary(self) -> int | None:
        """목록을 나눌 y: 확정된 선, 없으면 확인 중인 선(확정 전 몇 프레임 동안 회색 즐겨찾기를 켜진 목록 버프로 잡지 않게)."""
        return self.separator if self.separator is not None else self._pending

    @property
    def lost(self) -> bool:
        """선은 있는데 위에 즐겨찾기 줄이 하나도 안 보임 → 영역을 다시 지정해야 함."""
        return self.separator is not None and self.row_count == 0

    def update(self, region: np.ndarray, list_ys: list[int]) -> int | None:
        """list_ys: 이번 프레임 목록에서 찾은 등록 버프 아이콘 y. 선은 그 아래 목록이 있을 때만 받아들인다
        (영역 아래 게임 화면의 가로선 오인 방지)."""
        gray = _gray(region)
        self._frame += 1
        before = self.separator
        self._track(gray, list_ys)
        if self.separator is None:
            self.rows, self.on, self.row_count = {}, {}, 0
            return None
        remapped = (self.separator != before or self._needs_remap(gray)
                    or (not self.rows and self._frame % self.SCAN_EVERY == 0))
        if remapped:
            self._remap(gray, reason="구분선 이동" if before is not None and self.separator != before else "줄 확인")
        if remapped or self._frame % (self.SCAN_EVERY * 4) == 0:
            self.row_count = count_rows(gray, self.separator, self.rows, self._pitch())
        self.on = {bid: row_is_on(region, row.x, row.y, row.size) for bid, row in self.rows.items()}
        return self.separator

    def _track(self, gray: np.ndarray, list_ys: list[int]) -> None:
        state = None
        if self.separator is not None:
            state = line_state(gray, self.separator)
            if state:
                self._pending, self._pending_count, self._gone = None, 0, 0
                return
            if state is False:
                self._gone += 1
                if self._gone >= self.FORGET_FRAMES:
                    _log.info("즐겨찾기 구분선이 사라져 잊음(y=%s)", self.separator)
                    self.separator, self._gone = None, 0
        if self.separator is None and self._pending is None and (self._frame - 1) % self.SCAN_EVERY:
            return  # 즐겨찾기를 안 쓰는 경우 전체 탐색은 가끔만
        # 목록에 가장 가까운(아래쪽) 선: 영역을 창 위 게임 화면부터 잡아도 그쪽 가로선을 고르지 않게
        separators = find_separators(gray)
        candidates = [y for y in separators if any(ly > y for ly in list_ys)]
        if not candidates:
            # 0.31.1: 선 아래 목록이 모두 미등록 버프면(창 모드 wireweb_1) 위 근거로 — 선 바로 위 한 줄에 등록 버프
            # 아이콘(즐겨찾기 줄)이 있으면 구분선. 영역 아래 게임 바닥선은 바로 위가 아이콘 줄이 아니라 걸리지 않는다.
            candidates = next(([y] for y in reversed(separators) if self._favorite_row_above(gray, y)), [])
        new = candidates[-1] if candidates else None
        if new is None:
            self._pending, self._pending_count = None, 0
            return
        if self._pending is not None and abs(new - self._pending) <= 1:
            self._pending_count += 1
        else:
            self._pending, self._pending_count = new, 1
        if self._pending_count >= self.CONFIRM_FRAMES:
            if self.separator != new:
                _log.info("즐겨찾기 구분선 %s → %s", self.separator, new)
            self.separator, self._pending, self._pending_count, self._gone = new, None, 0, 0

    def _favorite_row_above(self, gray: np.ndarray, y: int) -> bool:
        """구분선 후보 y 바로 위 한 줄(줄 간격 안)에 등록 버프 아이콘이 있는지. 그 띠만 봐서 가볍다(전체 줄 맞춤의 약 1/40)."""
        x0, x1 = self._icon_column
        for template in self._templates.values():
            t = _gray(template)
            size = t.shape[0]
            band = gray[max(0, y - round(size * 1.5) - 4):y, x0:x1]
            if band.shape[0] < size or band.shape[1] < t.shape[1]:
                continue
            if match_icon(band, t).score >= FAV_MATCH_THRESHOLD:
                return True
        return False

    def _pitch(self) -> int:
        size = next((row.size for row in self.rows.values()), 16)
        return max(8, round(size * 1.5))  # 16px 아이콘 = 24px 줄 간격(실측)

    def _needs_remap(self, gray: np.ndarray) -> bool:
        for bid, row in self.rows.items():
            t = _gray(self._templates[bid])
            win = gray[max(0, row.y - 3):row.y + row.size + 3, max(0, row.x - 3):row.x + row.size + 3]
            if match_icon(win, t).score < VERIFY_THRESHOLD:
                return True
        return False

    def _remap(self, gray: np.ndarray, *, reason: str) -> None:
        rows = map_rows(gray, self._templates, self._icon_column, self.separator)
        if set(rows) != set(self.rows) or any(rows[b].y != self.rows[b].y for b in rows):
            _log.info("즐겨찾기 줄 다시 맞춤(%s): %s", reason,
                      ", ".join(f"{b}@{r.y}" for b, r in sorted(rows.items(), key=lambda i: i[1].y)) or "등록 버프 없음")
        self.rows = rows


def widen_to_favorites(frame: np.ndarray, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """버프 자동 찾기 영역(프레임 좌표)의 위쪽을 즐겨찾기 칸 맨 위까지 넓힌다(0.33.0 전체 공개 — 탭 자동 찾기·첫 안내 자동설정 공용).
    즐겨찾기 칸이 없거나 기준 버프를 못 찾으면 그대로."""
    from .status_panel import anchor_template, find_anchor
    x, y, w, h = box
    hit = find_anchor(frame, anchor_template())
    top = favorites_top(frame, box, hit.y) if hit is not None else None
    if top is None:
        return box
    return (x, top, w, h + (y - top))


def favorites_top(frame: np.ndarray, box: tuple[int, int, int, int], anchor_y: int) -> int | None:
    """버프 자동 찾기 영역(box, 프레임 좌표)의 위쪽을 즐겨찾기 칸 맨 위까지 넓힐 y. 넓힐 필요가 없거나 모르면 None.
    기준 버프 바로 위의 구분선 → 그 위 상태목록창 테두리를 찾는다(기준 버프가 즐겨찾기에 있으면 선이 아래라 그대로 둠)."""
    x, y, w, _h = box
    strip = _gray(frame[:max(0, anchor_y), x:x + w])
    candidates = find_separators(strip)
    if not candidates:
        return None
    sep = candidates[-1]  # 기준 버프에 가장 가까운(아래쪽) 선
    top = panel_top(strip, sep)
    if top is None or top >= y:
        return None
    return max(0, top - 6)  # 테두리 몇 줄 위부터(즐겨찾기 칸 줄 수 계산에 테두리가 보이게)
