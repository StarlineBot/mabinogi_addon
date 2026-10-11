"""디버프 트래커 엔진 (기획서 3.2).

보스 디버프 줄 영역에서 등록 디버프 아이콘을 2D 검색해, **아직 안 걸린(미감지)**
디버프만 등록 순서로 돌려준다. 버프와 반대 로직이다:
- 걸림(감지) → 즉시 숨김(오버레이에서 뺀다).
- 안 걸림(미감지) → 다시 표시는 reappear_sec 연속 미감지일 때만(깜빡임 방지).

지속시간·알림·앵커 없음. 보스가 없으면 전부 미감지 = 전부 표시(의미상 맞음).
결과는 BuffEngine과 같은 TickResult 형태라 BuffController가 그대로 쓸 수 있다.
"""

from __future__ import annotations

import cv2
import numpy as np

from ..detect import match_icon
from .engine import OverlayEntry, TickResult

# 보스 디버프 줄 아이콘의 실제 화면 높이(px). 2560x1440 기준 실측 ≈16.
_ONSCREEN_ICON_PX = 16
# 매칭은 이 높이로 축소해서 한다: 비용↓(영역을 크게 잡아도 됨) + 숫자 겹침 노이즈 완화.
# 너무 작으면(8px) 아이콘이 뭉개져 서로 점수가 겹치므로 10px로.
_MATCH_ICON_PX = 10
# 영역과 템플릿을 같은 비율로 축소 → 화면 아이콘이 _MATCH_ICON_PX가 되게.
_DOWNSCALE = _MATCH_ICON_PX / _ONSCREEN_ICON_PX  # 0.625
# 이력 임계(hysteresis): 실데이터에서 걸린 것 ≥0.70 / 안 걸린 것 ≤0.61.
# 감지 시작은 높게(0.68), 해제는 낮게(0.58) 잡아 경계 점수의 프레임별 요동을 없앤다.
# (주의) 모모만 잡겠다고 이 값을 0.76으로 올렸더니, 라이브에서 0.76 아래로 떨어지는
# '실제' 디버프들이 '없음'으로 누락됐다 → 0.68로 복구. 모모 오탐은 임계 일괄 상향이
# 아니라 '모모만 높은 임계'로 따로 잡는 게 맞다(real 0.93 / 오탐 0.67, 간격이 큼).
DEBUFF_DETECT_THRESHOLD = 0.68
DEBUFF_RELEASE_THRESHOLD = 0.58
DEBUFF_THRESHOLD = DEBUFF_DETECT_THRESHOLD  # 진단 스크립트 표시용

# 보스 HP바 앵커(오탐 게이팅). 영역에 보스 체력바까지 포함해 잡으면, 바가 보일 때만
# 디버프를 탐지해 마을·풀밭 오탐을 없앤다. 바 색은 HP/보스마다 달라(보라·파랑·초록·
# 노랑·빨강) 색으로는 못 가르지만, **바 채움은 가로로 길게 '매끈'(인접 픽셀 거의 동일)**
# 하다 — 풀밭 텍스처·채팅 글자는 매끈한 긴 가로런이 없다. 그 최장 매끈런 비율로 판정.
# 실샘플: 보스 바 0.48~0.53 / 마을·풀밭 ≤0.33 → 0.42로 가른다.
_BAR_SMOOTH_GAP = 6  # 인접 픽셀 밝기차가 이 미만이면 '매끈'
_BAR_SAT_MIN = 60  # 이 미만 채도는 '무채색'(돌바닥 등) — 바 채움에서 제외
_BAR_RUN_RATIO = 0.42  # 한 행의 최장 매끈런 / 영역 폭 이 이상이면 '바다운 행'
_BAR_MIN_ROWS = 6  # 그런 '바다운 행'이 이만큼(세로로 두꺼운 띠) 있어야 바로 인정
# (실샘플: 보스 바 22~45행 / 마을·풀밭 0행 → 우연한 매끈 한 줄엔 안 걸림)
_BAR_GRACE_SEC = 1.0  # 바가 잠깐 안 보여도 이 시간까진 유지(보스로 걸어갈 때 깜빡임 방지)

# 사라짐 경고: 걸렸던 디버프가 '보스 바 보이는 동안' 이만큼(초) 연속 미검출되면
# '떨어짐'으로 확정 → 경고(빨간 테두리+X) 노출 + 소리. 노출은 확정 후 이만큼(초).
# 바가 사라지면(보스 이탈) 확정 대기·경고를 모두 취소해 오탐을 없앤다.
_GONE_CONFIRM_SEC = 3.0
_GONE_SHOW_SEC = 5.0


def _variant(template: np.ndarray, target_h: int) -> np.ndarray:
    h, w = template.shape[:2]
    tw = max(4, round(w * target_h / h))
    return cv2.resize(template, (tw, target_h), interpolation=cv2.INTER_AREA)


class DebuffEngine:
    def __init__(
        self,
        templates: dict[str, np.ndarray],
        order: list[str],
        *,
        detect_threshold: float = DEBUFF_DETECT_THRESHOLD,
        release_threshold: float = DEBUFF_RELEASE_THRESHOLD,
        reappear_sec: float = 0.4,
    ) -> None:
        self._templates = templates
        self._order = list(order)
        self._detect_thr = detect_threshold
        self._release_thr = release_threshold
        self._reappear = reappear_sec
        # 템플릿을 매칭 크기(축소 후 화면 아이콘 크기)로 미리 맞춘다.
        self._variants = {
            bid: [_variant(t, _MATCH_ICON_PX)] for bid, t in templates.items()
        }
        # shown=True면 '안 걸림' → 오버레이 표시. 초기엔 전부 표시(보스 전 상태).
        self._shown = {bid: True for bid in templates}
        self._matched = {bid: False for bid in templates}  # 이력 임계용 직전 판정
        self._absent_since: dict[str, float | None] = {bid: None for bid in templates}
        # 보스 HP바 앵커: 영역에서 바를 한 번이라도 본 뒤부터 게이팅(버프 앵커와 동일).
        # 한 번도 못 봤으면(= 바를 안 넣은 기존 영역) 게이팅 안 함 → 기존처럼 항상 탐지.
        self._bar_seen = False
        self._bar_gone_since: float | None = None  # 바 사라진 시각(유예 판정용)
        self._bar_last = False  # 직전 틱 바 인식 여부(탭 상태 표시용)
        # 사라짐 경고 상태(디버프가 보스에서 떨어짐)
        self._warn_gone_ids: set[str] = set()  # '사라짐 경고' 켠 디버프
        self._applied_prev = {bid: False for bid in templates}  # 직전 틱 '걸림' 여부
        self._fell_since: dict[str, float] = {}  # 떨어지기 시작한 시각(확정 대기)
        self._warn_until: dict[str, float] = {}  # 확정 → 경고 노출 종료 시각

    @property
    def bar_seen(self) -> bool:
        """영역에서 보스 체력바를 한 번이라도 인식했는지(사라짐 경고 가능 영역인지)."""
        return self._bar_seen

    @property
    def bar_present(self) -> bool:
        """직전 틱에 보스 체력바가 보였는지(현재 보스 존재 추정)."""
        return self._bar_last

    def set_warn_gone_ids(self, ids: set[str]) -> None:
        """'사라짐 경고' 켠 디버프 집합 갱신."""
        self._warn_gone_ids = set(ids)

    def set_order(self, order: list[str]) -> None:
        self._order = list(order)

    @staticmethod
    def _scale(region: np.ndarray) -> np.ndarray:
        """영역을 _DOWNSCALE로 축소 — 화면 아이콘이 _MATCH_ICON_PX가 되도록."""
        if region.shape[0] == 0 or region.shape[1] == 0:
            return region
        return cv2.resize(
            region,
            (
                max(1, round(region.shape[1] * _DOWNSCALE)),
                max(1, round(region.shape[0] * _DOWNSCALE)),
            ),
            interpolation=cv2.INTER_AREA,
        )

    def best_scores(self, region: np.ndarray) -> dict[str, float]:
        """각 디버프의 최고 매칭 점수(진단용). 임계 판정 없이 점수만."""
        small = self._scale(region)
        out: dict[str, float] = {}
        for bid in self._variants:
            out[bid] = self._best(small, bid)
        return out

    def _best(self, small: np.ndarray, bid: str) -> float:
        best = -1.0
        for variant in self._variants.get(bid, ()):
            if (
                variant.shape[0] <= small.shape[0]
                and variant.shape[1] <= small.shape[1]
            ):
                best = max(best, match_icon(small, variant).score)
        return best

    def _detect(self, small: np.ndarray, bid: str) -> bool:
        """이력 임계: 시작은 detect_thr 이상, 해제는 release_thr 미만. 그 사이는 유지."""
        score = self._best(small, bid)
        if score >= self._detect_thr:
            matched = True
        elif score < self._release_thr:
            matched = False
        else:
            matched = self._matched.get(bid, False)  # 경계 구간 → 직전 판정 유지
        self._matched[bid] = matched
        return matched

    @staticmethod
    def _bar_present(region: np.ndarray) -> bool:
        """영역 안에 보스 HP바(길게 매끈하고 '색이 있는' 가로 띠)가 보이는가.

        바 채움은 **채도 높은 색(보라·파랑·초록·노랑·빨강…) + 가로로 매끈**하다. 각
        행에서 '매끈(인접차<gap)하며 채도도 높은' 픽셀의 최장 연속 길이를 재, 영역 폭의
        _BAR_RUN_RATIO 이상인 행이 _BAR_MIN_ROWS개 이상이면 바로 본다.
        - 매끈하지만 **채도 낮은 돌바닥**은 제외(매끈만으로는 바닥을 오인했던 버그 수정).
        - 채도 높지만 **매끈하지 않은 풀밭·채팅·아이콘**도 제외.
        """
        if region is None or region.shape[0] < 3 or region.shape[1] < 20:
            return False
        g = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.int16)
        sat = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)[:, :, 1]
        smooth = np.abs(np.diff(g, axis=1)) < _BAR_SMOOTH_GAP  # (h, w-1)
        colored = sat[:, :-1] > _BAR_SAT_MIN  # 왼쪽 픽셀 채도(바 채움=유채색)
        ok = smooth & colored
        need = int(region.shape[1] * _BAR_RUN_RATIO)
        bar_rows = 0
        for row in ok:
            run = longest = 0
            for v in row:
                run = run + 1 if v else 0
                longest = max(longest, run)
            if longest >= need:
                bar_rows += 1
                if bar_rows >= _BAR_MIN_ROWS:
                    return True
        return False

    def tick(
        self, region: np.ndarray, now: float, foreground: bool = True
    ) -> TickResult:
        # foreground: 사라짐 경고(소리)는 게임이 포그라운드일 때만 낸다. 디버프 탐지·표시는
        # 계속하되, '떨어짐' 판정·알림은 포커스+화면 확정 시로 제한한다(안 볼 때의 거짓
        # 사라짐 방지). 비포커스 중엔 대기/노출 상태를 비워, 복귀 시 다시 깨끗이 판정한다.
        if not foreground:
            self._fell_since.clear()
            self._warn_until.clear()
            self._applied_prev = {bid: False for bid in self._templates}
        # 보스 HP바 앵커 게이팅: 바를 본 적 있으면(영역에 바 포함), 바가 안 보이는
        # 프레임엔 탐지를 멈춰(= 보스 없음) 마을·풀밭 오탐을 없앤다. 바를 한 번도 못 본
        # 영역(기존 사용자)은 게이팅하지 않아 지금과 동일하게 동작한다(하위호환).
        bar = self._bar_present(region)
        self._bar_last = bar
        if bar:
            self._bar_seen = True
            self._bar_gone_since = None
        elif self._bar_seen:
            # 바가 잠깐 안 보임: 보스로 걸어가는 중엔 바가 간헐적으로만 잡혀 매 틱
            # 켜졌다 꺼지면 오버레이가 깜빡인다. _BAR_GRACE_SEC 동안 연속으로 없을
            # 때만 '보스 없음'으로 확정해 숨긴다(그 전엔 직전처럼 탐지 유지).
            if self._bar_gone_since is None:
                self._bar_gone_since = now
            if now - self._bar_gone_since >= _BAR_GRACE_SEC:
                # 보스 없음 확정 → 사라짐 경고 상태 전부 리셋(보스 이탈 오탐 방지).
                self._applied_prev = {bid: False for bid in self._templates}
                self._fell_since.clear()
                self._warn_until.clear()
                return TickResult(entries=[], alerts=[], frame_valid=True)  # 보스 없음

        small = self._scale(region)
        for bid in self._templates:
            detected = self._detect(small, bid)
            if detected:
                self._shown[bid] = False  # 걸림 → 즉시 숨김
                self._absent_since[bid] = None
            elif not self._shown[bid]:
                # 미감지 + 현재 숨김 상태: reappear_sec 연속되면 다시 표시
                if self._absent_since[bid] is None:
                    self._absent_since[bid] = now
                elif now - self._absent_since[bid] >= self._reappear:
                    self._shown[bid] = True
                    self._absent_since[bid] = None
            # 이미 표시 중(shown)이면 그대로 유지

            # --- 사라짐 경고(바가 보이고 + 포그라운드일 때만) ---
            if bar and foreground and bid in self._warn_gone_ids:
                if detected:  # 다시 걸림 → 확정 대기·경고 취소
                    self._fell_since.pop(bid, None)
                    self._warn_until.pop(bid, None)
                elif (
                    self._applied_prev.get(bid)  # 직전엔 걸려 있었는데 이번에 떨어짐
                    and bid not in self._fell_since
                    and bid not in self._warn_until
                ):
                    self._fell_since[bid] = now  # 확정 대기 시작
            # 다음 틱 비교용 '걸림' 기록. 바 안 보이거나 비포커스면 비교 의미 없어 False.
            self._applied_prev[bid] = detected if (bar and foreground) else False

        # 확정: 바 보이고 포그라운드일 때 _GONE_CONFIRM_SEC 연속 미검출 → '떨어짐' 확정.
        alerts: list[str] = []
        if bar and foreground:
            for bid, since in list(self._fell_since.items()):
                if now - since >= _GONE_CONFIRM_SEC:
                    self._warn_until[bid] = now + _GONE_SHOW_SEC
                    del self._fell_since[bid]
                    alerts.append(bid)
        # 노출 시간 지난 경고 정리
        self._warn_until = {b: t for b, t in self._warn_until.items() if now < t}

        entries = []
        for bid in self._order:
            gone = bid in self._warn_until  # 사라짐 경고 노출 중
            if self._shown.get(bid, False) or gone:
                entries.append(OverlayEntry(bid, None, False, gone=gone))
        return TickResult(entries=entries, alerts=alerts, frame_valid=True)
