"""쿨타임 오버레이 한 줄 상태(쿨타임 명세 10.1) — 화면과 무관한 순수 로직.

- 등록 칸이 '사용 중'이 되면 줄 끝에 붙는다(쓴 순서).
- 사용 가능해지면 약 1초 강조 + 알림 뒤 빠지고 뒤 칸이 당겨진다. 소리는 0.5초 안에 끝난 칸들끼리 한 번,
  같은 칸이 강조 중 번쩍임으로 다시 끝나도 다시 울리지 않는다(알림음은 기본 꺼짐, 쿨타임 전용 효과음).
- 강조 중 다시 사용 중이 되면 강조를 취소하고 줄 끝으로 간다.
- 가려짐·페이지 바뀜(hidden)은 사용 가능으로 치지 않는다 → 강조·알림 없이 그 칸만 줄에서 뺀다.
- 앱 시작·다시 보임: 이미 사용 중이면 바로 줄에, 이미 사용 가능이면 강조·알림 없이 비워 둔다.
자체 타이머로 남은 시간을 세지 않는다(게임 표시만 따름 — 장비로 쿨타임이 바뀌어도 그대로 반영).
"""
from __future__ import annotations

COOLING, READY, HIDDEN = "cooling", "ready", "hidden"
HIGHLIGHT_SECONDS = 1.0
SOUND_GAP = 0.5  # 이 안에 끝난 칸들은 '동시에'로 보고 소리 한 번(관측 0.22초 간격으로 나뉘어 들어와도)


class CooldownRow:
    def __init__(self, highlight: float = HIGHLIGHT_SECONDS) -> None:
        self.highlight = highlight
        self.row: list[str] = []
        self.until: dict[str, float] = {}   # 강조 중인 칸 → 끝나는 시각
        self._seen: set[str] = set()         # 이번에 보이기 시작한 뒤 한 번이라도 관측한 칸
        self._sounded: dict[str, float] = {}  # 칸 → 마지막으로 소리 낸 시각(같은 칸은 강조 시간 안에 다시 울리지 않음)
        self._last_sound = float("-inf")

    def update(self, states: dict[str, str], now: float) -> bool:
        """칸 상태(바뀐 것만이어도 됨)를 반영. 알림음을 낼지(True) 돌려준다."""
        sound = False
        for sid, state in states.items():
            if state not in (COOLING, READY):  # 가려짐·페이지 바뀜·못 읽음
                self._drop(sid)
                self._seen.discard(sid)
                continue
            first = sid not in self._seen
            self._seen.add(sid)
            if state == COOLING:
                if sid in self.until:  # 강조 중 다시 사용 → 강조 취소, 줄 끝으로
                    self.until.pop(sid)
                    self.row.remove(sid)
                    self.row.append(sid)
                elif sid not in self.row:
                    self.row.append(sid)
            elif sid in self.row and sid not in self.until and not first:
                self.until[sid] = now + self.highlight
                if now - self._sounded.get(sid, float("-inf")) >= self.highlight:  # 강조 중 번쩍임으로 다시 끝나도 반복 안 함
                    sound = True
                    self._sounded[sid] = now
        self.expire(now)
        if sound and now - self._last_sound < SOUND_GAP:
            sound = False  # 방금 울렸다(여러 칸이 거의 동시에 끝남) → 한 번만
        if sound:
            self._last_sound = now
        return sound

    def expire(self, now: float) -> bool:
        """강조가 끝난 칸을 뺀다. 바뀌었으면 True."""
        done = [sid for sid, t in self.until.items() if now >= t]
        for sid in done:
            self._drop(sid)
        return bool(done)

    def prune(self, ids) -> None:
        """등록에서 빠진 칸 정리."""
        keep = set(ids)
        for sid in [s for s in self.row if s not in keep]:
            self._drop(sid)
        self._seen &= keep

    def reset(self) -> None:
        """게임 비활성·일시정지·끄기 — 다음에 보일 때 초기 판별부터(강조 없음)."""
        self.row.clear()
        self.until.clear()
        self._seen.clear()
        self._sounded.clear()
        self._last_sound = float("-inf")

    def _drop(self, sid: str) -> None:
        self.until.pop(sid, None)
        if sid in self.row:
            self.row.remove(sid)
