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
from ..detect.boss_hp_reader import read_percent_cached
from .engine import OverlayEntry, TickResult

# 디버프 탐지 방식(게이팅). 사용자가 1차/2차/3차로 따로 골라 비교·테스트할 수 있다.
GATE_OFF = "off"  # 1차: 게이팅 없음 — 항상 탐지(기존). 바닥 오탐 가능하나 바 인식 비의존.
GATE_BAND = "band"  # 2차: 디버프 영역 안의 '평평한 띠'로 보스 유무 판정(베타).
GATE_PERCENT = "percent"  # 3차: 정렬된 '보스 바 영역'에서 read_percent로 판정(베타).
_GATE_MODES = (GATE_OFF, GATE_BAND, GATE_PERCENT)

# 보스 디버프 줄 아이콘의 실제 화면 높이(px). 2560x1440 기준 실측 ≈16.
_ONSCREEN_ICON_PX = 16
# 캡처는 재샘플링하지 않는다. 영역 경계에 따라 아이콘 픽셀이 바뀌는 것을 막는다.
_MATCH_ICON_PX = _ONSCREEN_ICON_PX
_CANDIDATES = 4
# 이력 임계(hysteresis): 실데이터에서 걸린 것 ≥0.70 / 안 걸린 것 ≤0.61.
# 감지 시작은 높게(0.68), 해제는 낮게(0.58) 잡아 경계 점수의 프레임별 요동을 없앤다.
# (주의) 모모만 잡겠다고 이 값을 0.76으로 올렸더니, 라이브에서 0.76 아래로 떨어지는
# '실제' 디버프들이 '없음'으로 누락됐다 → 0.68로 복구. 모모 오탐은 임계 일괄 상향이
# 아니라 '모모만 높은 임계'로 따로 잡는 게 맞다(real 0.93 / 오탐 0.67, 간격이 큼).
DEBUFF_DETECT_THRESHOLD = 0.68
DEBUFF_RELEASE_THRESHOLD = 0.58
DEBUFF_THRESHOLD = DEBUFF_DETECT_THRESHOLD  # 진단 스크립트 표시용

# 아이콘별 임계 override. 모모(네잎클로버)처럼 정보량이 적은 아이콘은 풀·바닥·스킬
# 이펙트와 상관계수가 0.67까지 올라가 일괄 임계(0.68)에 거의 붙는다 → 안 걸렸는데
# '걸림'으로 오판돼 오버레이에서 사라진다. 실제로 걸렸을 땐 0.93로 간격이 크므로,
# '그 아이콘만' 높은 임계로 가른다. (일괄 상향은 0.76 아래로 떨어지는 '실제' 다른
# 디버프들을 누락시켜 안 됨 — 위 주석 참고.) 다른 아이콘이 재발하면 여기에 추가한다.
_PER_ICON_DETECT = {"모모": 0.80, "방해 카드": 0.80}
_PER_ICON_RELEASE = {"모모": 0.70, "방해 카드": 0.70}

# 색이 다른 같은 무늬가 동일 슬롯을 중복 점유하지 않도록 후보 위치에서 구분한다.
_IDENTITY_PEERS = {"프라가라흐(마법)": "프라가라흐(물리)",
                   "프라가라흐(물리)": "프라가라흐(마법)"}

# 보스 HP바 앵커(오탐 게이팅). 영역에 보스 체력바까지 포함해 잡으면, 바가 보일 때만
# 디버프를 탐지해 마을·풀밭 오탐을 없앤다. 바 색은 HP/보스마다 달라(보라·파랑·초록·
# 노랑·빨강) 색으로는 못 가르지만, **바 채움은 가로로 길게 '매끈'(인접 픽셀 거의 동일)**
# 하다 — 풀밭 텍스처·채팅 글자는 매끈한 긴 가로런이 없다. 그 최장 매끈런 비율로 판정.
# 실샘플: 보스 바 0.48~0.53 / 마을·풀밭 ≤0.33 → 0.42로 가른다.
_BAR_SMOOTH_GAP = 6  # 인접 픽셀 밝기차가 이 미만이면 '매끈'
_BAR_SAT_MIN = 60  # 이 미만 채도는 '무채색'(돌바닥 등) — 바 채움에서 제외
# 이 미만 밝기는 '어두운 색'(어두운 풀밭 등) — 바 채움에서 제외. 어두운 녹색 풀밭이
# 채도 높고 균일(매끈)해 바로 오인되던 것 방지(실샘플: 풀밭 V중앙 24~42 / 보스 바 135+).
_BAR_VAL_MIN = 90
_BAR_RUN_RATIO = 0.42  # 한 행의 최장 매끈런 / 영역 폭 이 이상이면 '바다운 행'
_BAR_MIN_ROWS = 6  # 그런 '바다운 행'이 이만큼(세로로 두꺼운 띠) 있어야 바로 인정
# (실샘플: 보스 바 22~45행 / 마을·풀밭 0행 → 우연한 매끈 한 줄엔 안 걸림)
_BAR_GRACE_SEC = 1.0  # 바가 잠깐 안 보여도 이 시간까진 유지(보스로 걸어갈 때 깜빡임 방지)

# 사라짐 경고: 걸렸던 디버프가 '보스 바 보이는 동안' 이만큼(초) 연속 미검출되면
# '떨어짐'으로 확정 → 경고(빨간 테두리+X) 노출 + 소리. 노출은 확정 후 이만큼(초).
# 바가 사라지면(보스 이탈) 확정 대기·경고를 모두 취소해 오탐을 없앤다.
_GONE_CONFIRM_SEC = 3.0
_GONE_SHOW_SEC = 5.0

# 검출 디바운스: '걸림(숨김)'으로 확정하기 전, 검출이 이만큼(초) 연속돼야 한다. 지나가는
# 스킬 이펙트·섬광이 **한 프레임만** 임계(0.68)를 넘겨 '걸림'으로 래치되던 오탐을 막는다
# (방해 카드·모모 등 저정보 아이콘이 이펙트에 순간 매칭되던 문제). 실제 디버프는 계속
# 잡히므로 ~이 시간 뒤 정상 표시된다(해제는 즉시 — 떨어짐/사라짐 경고 지연 없음).
_DETECT_CONFIRM_SEC = 0.3

# 3차(percent) 판독 주기(초). read_percent는 비싸(수십 ms) 매 틱 돌리면 성능 목표를
# 크게 넘긴다. 보스 유무는 천천히 바뀌므로 이 간격마다만 재판독하고 그 사이엔 캐시 사용.
_PERCENT_READ_INTERVAL = 0.6


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
        bar_gating: bool | None = None,
        gate_mode: str = GATE_OFF,
        reference_templates: dict[str, np.ndarray] | None = None,
    ) -> None:
        self._templates = templates
        self._order = list(order)
        self._detect_thr = detect_threshold
        self._release_thr = release_threshold
        self._reappear = reappear_sec
        # 디버프 탐지 방식(1차/2차/3차). 기본 off(1차)=항상 탐지. bar_gating(구버전 불리언)은
        # 하위호환: True→band(2차), False→off(1차). gate_mode가 우선이지만 bar_gating이
        # 명시되면 그걸 따른다(기존 호출부 유지).
        if bar_gating is not None:
            gate_mode = GATE_BAND if bar_gating else GATE_OFF
        self._gate_mode = gate_mode if gate_mode in _GATE_MODES else GATE_OFF
        # 템플릿만 실제 화면 아이콘 크기로 미리 맞춘다.
        self._variants = {
            bid: [_variant(t, _MATCH_ICON_PX)] for bid, t in templates.items()
        }
        self._gray_variants = {
            bid: [cv2.cvtColor(t, cv2.COLOR_BGR2GRAY) for t in variants]
            for bid, variants in self._variants.items()
        }
        # 보조 이미지는 후보 패치 비교에만 사용하며 검색/표시/상태 사전에 넣지 않는다.
        self._identity_variants = dict(self._variants)
        for bid in templates:
            peer = _IDENTITY_PEERS.get(bid)
            if peer not in self._identity_variants and peer in (reference_templates or {}):
                self._identity_variants[peer] = [_variant(reference_templates[peer], _MATCH_ICON_PX)]
        # shown=True면 '안 걸림' → 오버레이 표시. 초기엔 전부 표시(보스 전 상태).
        self._shown = {bid: True for bid in templates}
        self._matched = {bid: False for bid in templates}  # 이력 임계용 직전 판정
        # 검출 디바운스: 검출이 처음 True가 된 시각(이만큼 연속돼야 '걸림' 확정).
        self._detect_since: dict[str, float | None] = {bid: None for bid in templates}
        self._absent_since: dict[str, float | None] = {bid: None for bid in templates}
        # 보스 HP바 앵커: 영역에서 바를 한 번이라도 본 뒤부터 게이팅(버프 앵커와 동일).
        # 한 번도 못 봤으면(= 바를 안 넣은 기존 영역) 게이팅 안 함 → 기존처럼 항상 탐지.
        self._bar_seen = False
        self._bar_gone_since: float | None = None  # 바 사라진 시각(유예 판정용)
        self._bar_last = False  # 직전 틱 바 인식 여부(탭 상태 표시용)
        # 방식과 무관하게 '디버프 영역에서 띠를 한 번이라도 봤는지'(사라짐 경고 가능 안내용).
        # 보스가 잠깐 없어도 True로 유지 — 영역이 맞는지 안내가 깜빡이지 않게.
        self._bar_ever_seen = False
        # 3차(percent) 판독 캐시: 마지막 판독 시각(None=아직)·결과(throttle용) + 당첨 오프셋.
        self._percent_last_t: float | None = None
        self._percent_present = False
        self._percent_offset: int | None = None  # 직전 당첨 정렬 오프셋(빠른 재판독 힌트)
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

    @property
    def bar_ever_seen(self) -> bool:
        """디버프 영역에서 띠를 한 번이라도 봤는지(사라짐 경고 가능 안내용, 방식 무관)."""
        return self._bar_ever_seen

    def set_warn_gone_ids(self, ids: set[str]) -> None:
        """'사라짐 경고' 켠 디버프 집합 갱신."""
        self._warn_gone_ids = set(ids)

    def set_bar_gating(self, on: bool) -> None:
        """하위호환: 2차(band) 게이팅 켜기/끄기(= set_gate_mode(band|off))."""
        self.set_gate_mode(GATE_BAND if on else GATE_OFF)

    def set_gate_mode(self, mode: str) -> None:
        """탐지 방식 전환(off=1차 / band=2차 / percent=3차). 전환 시 바 이력 초기화."""
        if mode not in _GATE_MODES or mode == self._gate_mode:
            return
        self._gate_mode = mode
        self._bar_seen = False
        self._bar_gone_since = None
        self._percent_last_t = None  # 다음 틱에 즉시 재판독
        self._percent_present = False
        self._percent_offset = None

    @property
    def gate_mode(self) -> str:
        return self._gate_mode

    def set_order(self, order: list[str]) -> None:
        self._order = list(order)

    def can_track(self, order: list[str]) -> bool:
        return all(bid in self._templates for bid in order)

    @staticmethod
    def reference_ids(order: list[str]) -> set[str]:
        return {_IDENTITY_PEERS[bid] for bid in order if bid in _IDENTITY_PEERS} - set(order)

    @staticmethod
    def _scale(region: np.ndarray) -> np.ndarray:
        """기존 진단 호출부용: 원본 픽셀을 그대로 반환한다."""
        return region

    def best_scores(self, region: np.ndarray) -> dict[str, float]:
        """각 디버프의 원시 최고 컬러 점수. 식별 경쟁/이력 임계 적용 전 진단값."""
        small = self._scale(region)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.size else None
        out: dict[str, float] = {}
        for bid in self._variants:
            out[bid] = self._best(small, bid, gray)
        return out

    def _best(self, small: np.ndarray, bid: str, gray: np.ndarray | None = None) -> float:
        return self._candidate_best(small, bid, gray, identify=False)

    def _candidate_best(self, small: np.ndarray, bid: str, gray: np.ndarray | None,
                        *, identify: bool) -> float:
        best = -1.0
        if small.size == 0:
            return best
        if gray is None:
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        for variant, gray_variant in zip(self._variants.get(bid, ()), self._gray_variants.get(bid, ())):
            if (
                variant.shape[0] <= small.shape[0]
                and variant.shape[1] <= small.shape[1]
            ):
                # 위치 후보만 단일 채널로 찾고 최종 점수는 원본 컬러로 검증한다.
                # 컬러 검증 횟수는 영역 크기와 무관하게 제한한다.
                scores = cv2.matchTemplate(gray, gray_variant, cv2.TM_CCOEFF_NORMED)
                h, w = variant.shape[:2]
                for _ in range(_CANDIDATES):
                    _, peak, _, (x, y) = cv2.minMaxLoc(scores)
                    if peak < 0:
                        break
                    patch = small[y:y + h, x:x + w]
                    score = match_icon(patch, variant).score
                    peers = self._identity_variants.get(_IDENTITY_PEERS.get(bid), ()) if identify else ()
                    # 전체 화면의 최고점끼리 경쟁시키면 서로 다른 슬롯의 동시 적용을 놓친다.
                    ambiguous = any(peer.shape == patch.shape
                                    and match_icon(patch, peer).score >= score - 1e-6
                                    for peer in peers)
                    if not ambiguous:
                        best = max(best, score)
                    scores[max(0, y - h // 2):y + h // 2 + 1,
                           max(0, x - w // 2):x + w // 2 + 1] = -1
        return best

    def detect_threshold_for(self, bid: str) -> float:
        """아이콘별 감지 임계(모모·방해 카드 등 저정보 아이콘은 더 높게)."""
        return _PER_ICON_DETECT.get(bid, self._detect_thr)

    def release_threshold_for(self, bid: str) -> float:
        return _PER_ICON_RELEASE.get(bid, self._release_thr)

    def _detect(self, small: np.ndarray, bid: str, gray: np.ndarray | None = None) -> bool:
        """이력 임계: 시작은 detect_thr 이상, 해제는 release_thr 미만. 그 사이는 유지.
        모모·방해 카드처럼 이펙트에 잘 붙는 저정보 아이콘은 아이콘별로 더 높은 임계를 쓴다."""
        peer = _IDENTITY_PEERS.get(bid)
        score = (self._candidate_best(small, bid, gray, identify=True)
                 if peer in self._identity_variants else self._best(small, bid, gray))
        detect_thr = _PER_ICON_DETECT.get(bid, self._detect_thr)
        release_thr = _PER_ICON_RELEASE.get(bid, self._release_thr)
        if score >= detect_thr:
            matched = True
        elif score < release_thr:
            matched = False
        else:
            matched = self._matched.get(bid, False)  # 경계 구간 → 직전 판정 유지
        self._matched[bid] = matched
        return matched

    def _confirm_detect(self, bid: str, raw: bool, now: float) -> bool:
        """검출 디바운스: raw(이력 임계 통과)가 _DETECT_CONFIRM_SEC 연속일 때만 True.

        한 프레임짜리 거짓 매칭(지나가는 이펙트)은 확정되지 않아 '걸림' 래치를 막는다.
        raw가 False가 되면 즉시 리셋 → 해제(떨어짐)는 지연 없이 바로 반영된다.
        """
        if raw:
            if self._detect_since.get(bid) is None:
                self._detect_since[bid] = now
            return now - self._detect_since[bid] >= _DETECT_CONFIRM_SEC
        self._detect_since[bid] = None
        return False

    @staticmethod
    def _band_rows(ok: np.ndarray, need: int) -> int:
        """각 행의 최장 True 가로 연속이 need 이상인 행 수. (numpy 벡터화 — 폭만큼만 루프,
        각 단계는 행 전체 벡터 연산. 픽셀 단위 Python 이중루프를 대체해 성능 목표를 지킨다.)"""
        if ok.size == 0:
            return 0
        cur = np.zeros(ok.shape[0], dtype=np.int32)
        longest = np.zeros(ok.shape[0], dtype=np.int32)
        for col in ok.T:  # 열(폭) 단위 — 각 연산은 행 전체에 벡터 적용
            cur = np.where(col, cur + 1, 0)
            longest = np.maximum(longest, cur)
        return int((longest >= need).sum())

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
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        sat, val = hsv[:, :, 1], hsv[:, :, 2]
        smooth = np.abs(np.diff(g, axis=1)) < _BAR_SMOOTH_GAP  # (h, w-1)
        # 바 채움 = 유채색(sat) + 밝음(val). 어두운 녹색 풀밭(채도 높고 균일하나 어두움)을
        # 바로 오인하던 것을 밝기 조건으로 배제한다.
        colored = (sat[:, :-1] > _BAR_SAT_MIN) & (val[:, :-1] > _BAR_VAL_MIN)
        need = int(region.shape[1] * _BAR_RUN_RATIO)
        return DebuffEngine._band_rows(smooth & colored, need) >= _BAR_MIN_ROWS

    @staticmethod
    def _is_background(region: np.ndarray) -> bool:
        """영역이 '확실한 바닥/배경'(보스 바가 통째로 사라진 상태)인가.

        _bar_present(밝은 유채색 띠)가 False여도 **보스가 사라진 것은 아니다**: 빈사
        직전 보스 바는 '평평한 검은 띠'로 바뀌어 밝기/채도 조건에서 탈락한다. 그런데
        검은 바도 **가로로 매끈한 띠**다 — 실게임 바닥·마을 텍스처는 '밝기 무관' 매끈
        가로런이 한 줄도 없다(실측: 바닥/마을 0줄 vs 보스 바 30줄+). 그래서 **색·밝기를
        전혀 보지 않고** 매끈한 가로 띠(_BAR_MIN_ROWS줄 이상)가 있으면 바닥이 아니다.

        왜 이렇게 보수적으로 가는가: 빈사(검은 바)를 '보스 없음'으로 오판해 걸린 디버프를
        '미적용'으로 리셋하면, 끝내야 할 보스에게 디버프를 재갱신하러 다가가다 죽을 수
        있다. 그래서 **확실히 바닥일 때만** 리셋하고, 애매하면(검은 바·전환·이펙트) 직전
        상태를 유지하며 매칭을 계속한다(디버프 아이콘은 빈사여도 그대로 보인다).
        """
        if region is None or region.shape[0] < 3 or region.shape[1] < 20:
            return False
        g = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.int16)
        smooth = np.abs(np.diff(g, axis=1)) < _BAR_SMOOTH_GAP  # (h, w-1), 색·밝기 무관
        need = int(region.shape[1] * _BAR_RUN_RATIO)
        # 매끈한 가로 띠가 _BAR_MIN_ROWS줄 미만이면 바닥(보스 바 없음).
        return DebuffEngine._band_rows(smooth, need) < _BAR_MIN_ROWS

    def _gate_absent(
        self,
        region: np.ndarray,
        bar: bool,
        bar_region: np.ndarray | None,
        now: float,
    ) -> bool:
        """현재 방식(1/2/3차)에 따라 '보스 없음 확정'인지 판정.

        - 1차(off): 게이팅 안 함 → 항상 False(= 항상 탐지).
        - 2차(band): 디버프 영역의 '평평한 띠'로 판정. 밝은 바 있으면 보스, 확실한 바닥이면
          유예 후 없음, 애매(검은 바 등)면 유지(리셋 금지). (빈사 보호)
        - 3차(percent): 정렬된 바 영역에서 read_percent가 숫자를 읽으면 보스, 못 읽으면
          유예 후 없음. 바 영역이 없으면(미지정) 게이팅 안 함(= off처럼 안전).
        공통: 바를 한 번도 본 적 없으면(bar_seen=False) 리셋하지 않는다(하위호환/초기 상태).
        """
        mode = self._gate_mode
        if mode == GATE_OFF:
            return False

        if mode == GATE_BAND:
            present = bar
            confident_absent = (not bar) and self._is_background(region)
        elif mode == GATE_PERCENT:
            if bar_region is None:
                return False  # 바 영역 미지정 → 게이팅 보류(안전)
            # 보완1: '확실한 바닥'이면 숫자 판독(수십 ms)을 건너뛴다. 보스가 없는 시간이
            # 대부분이라 이 한 줄이 평균 비용을 가장 크게 줄인다. 바닥이면 어차피 숫자가
            # 안 읽혀 None이므로 판정 결과는 동일(비용만 큼).
            if self._is_background(bar_region):
                present = False
                confident_absent = True  # 확실한 바닥 → 보스 없음(유예 후 리셋)
            else:
                # 바닥 아님(띠 있음=바 존재). 판독해 보스/빈사를 구분한다.
                # 성능: _PERCENT_READ_INTERVAL마다만 재판독 + 직전 당첨 오프셋 힌트로 가속.
                if (
                    self._percent_last_t is None
                    or now - self._percent_last_t >= _PERCENT_READ_INTERVAL
                ):
                    val, off = read_percent_cached(
                        bar_region, hint=self._percent_offset
                    )
                    self._percent_present = val is not None
                    if off is not None:
                        self._percent_offset = off  # 당첨 오프셋 기억(다음 판독 가속)
                    self._percent_last_t = now
                present = self._percent_present
                # 빈사 보호: 바닥이 아닌데 퍼센트를 못 읽으면(검은 바·이펙트·가림) '애매'로
                # 보고 유지(걸린 디버프를 재갱신하다 죽는 사고 방지 — 2차와 같은 철학).
                confident_absent = False
        else:
            return False

        if present:
            self._bar_seen = True
            self._bar_gone_since = None
            return False
        if not self._bar_seen:
            return False  # 바를 본 적 없음 → 아직 게이팅 안 함
        if not confident_absent:
            # 애매(검은 바·전환·이펙트) → 리셋 금지, 유예 재시작, 매칭 유지.
            self._bar_gone_since = None
            return False
        if self._bar_gone_since is None:
            self._bar_gone_since = now
        return now - self._bar_gone_since >= _BAR_GRACE_SEC

    def tick(
        self,
        region: np.ndarray,
        now: float,
        foreground: bool = True,
        bar_region: np.ndarray | None = None,
    ) -> TickResult:
        # foreground: 사라짐 경고(소리)는 게임이 포그라운드일 때만 낸다. 디버프 탐지·표시는
        # 계속하되, '떨어짐' 판정·알림은 포커스+화면 확정 시로 제한한다(안 볼 때의 거짓
        # 사라짐 방지). 비포커스 중엔 대기/노출 상태를 비워, 복귀 시 다시 깨끗이 판정한다.
        # bar_region: 3차(percent)용 '정렬된 보스 바 영역'(없으면 3차는 게이팅 안 함).
        if not foreground:
            self._fell_since.clear()
            self._warn_until.clear()
            self._applied_prev = {bid: False for bid in self._templates}
        # 사라짐 경고용 바 인식(디버프 영역 내 '평평한 띠')은 방식과 무관하게 계속 쓴다.
        bar = self._bar_present(region)
        self._bar_last = bar
        if bar:
            self._bar_ever_seen = True  # 사라짐 경고 안내용(방식 무관, 한 번 보면 유지)
        boss_absent = self._gate_absent(region, bar, bar_region, now)

        if boss_absent:
            # 보스 없음 확정 → 매칭 중단, 전부 미적용으로 리셋(래치 해제), 경고 대기 비움.
            self._applied_prev = {bid: False for bid in self._templates}
            self._fell_since.clear()
            self._warn_until.clear()
            for bid in self._templates:
                self._shown[bid] = True
                self._matched[bid] = False
                self._detect_since[bid] = None
                self._absent_since[bid] = None
            entries = [
                OverlayEntry(bid, None, False, gone=False)
                for bid in self._order
                if self._shown.get(bid, False)
            ]
            return TickResult(entries=entries, alerts=[], frame_valid=True)

        small = self._scale(region)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.size else None
        for bid in self._templates:
            # 이력 임계 통과(raw) → 디바운스로 확정(detected). 단발 스파이크는 확정 안 됨.
            raw = self._detect(small, bid, gray)
            detected = self._confirm_detect(bid, raw, now)
            # 재매칭 대기는 연속 미감지가 아니다. 이미 숨긴 항목의 재표시 대기를 취소한다.
            if detected or (raw and not self._shown[bid]):
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
