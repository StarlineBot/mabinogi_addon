"""사용 기능 보고 `featureUsage`(docs/account-management-spec.md 3.4.2, 사용자 결정 2026-11-18 B안) — Qt 없는 순수 로직.

봇 '켠 기능'은 스위치 값(enabled)만 봐서 스위치가 없는 버프·디버프·보스 패턴·1분 헤일로는 써도 안 나왔다.
→ 앱이 기능별 '마지막으로 실제 동작한 날'(현지 날짜 YYYY-MM-DD)을 설정 최상위 `featureUsage`에 적고, 봇은 그것만 읽는다.

- 무엇이 '동작'인지는 메인 창이 판단해 `active` 키 묶음으로 넘긴다(명세 표). 이 모듈은 '언제 적을지'만 정한다.
- 게임이 실행 중이고 전투 보조 일시정지가 아닐 때만, 그날 처음 동작한 키만 한 번 저장(같은 날 다시 쓰지 않음 —
  설정 동기화의 30초 모으기를 매번 깨우지 않게).
- 동기화·내보내기 대상(빼는 값 아님). 가져오기(동기화 받기·파일 가져오기)는 이 PC 값을 그대로 둔다(`keep_local`).
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import datetime

KEY = "featureUsage"
# 명세 3.4.2 표 — 홈 화면 키와 같은 이름. 새 기능을 만들면 여기에 키를 더한다.
KEYS = ("buff", "debuff", "boss", "halo", "tuarim", "dorcha", "stat_bars", "skillbar", "custom",
        "cooldown", "boss_bar", "fps", "opt", "cursor", "blackbox", "alarm", "keywords",
        "pet", "character_voice")   # 11-25 캐릭터: 펫이 화면에 보임 / 고른 캐릭터 목소리로 알림이 울림
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean(raw) -> dict[str, str]:
    """저장값 → {키: 날짜}(알려진 키·날짜 형식만)."""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in KEYS and isinstance(v, str) and _DATE.match(v)}


def keep_local(merged: dict, local: dict) -> None:
    """가져오기 결과(merged)에서 featureUsage를 이 PC 값으로(없으면 넣지도 지우지도 않음 — 받은 값은 버림)."""
    if KEY in local:
        merged[KEY] = dict(local[KEY]) if isinstance(local[KEY], dict) else local[KEY]
    else:
        merged.pop(KEY, None)


class Recorder:
    """그날 처음 동작한 키만 저장. load() → {키: 날짜}, save({키: 날짜}) → 새로 적을 값만(병합은 save 쪽)."""

    def __init__(self, load: Callable[[], dict], save: Callable[[dict], None],
                 today: Callable[[], str] = lambda: datetime.now().astimezone().date().isoformat()) -> None:  # 현지 날짜
        self._load, self._save, self._today = load, save, today
        self._dates: dict[str, str] | None = None  # 처음 한 번 읽어 둔다(틱마다 설정 파일을 읽지 않음)

    def observe(self, active: Iterable[str], *, game_running: bool, paused: bool) -> list[str]:
        """이번에 새로 적은 키(없으면 []). 게임이 꺼져 있거나 일시정지면 아무것도 안 함."""
        if not game_running or paused:
            return []
        if self._dates is None:
            self._dates = clean(self._load())
        today = self._today()
        new = sorted(k for k in set(active) if k in KEYS and self._dates.get(k) != today)
        if not new:
            return []
        updates = {k: today for k in new}
        self._save(updates)  # 실패(OSError)하면 예외 — 기억하지 않아 다음 틱에 다시 시도
        self._dates.update(updates)
        return new
