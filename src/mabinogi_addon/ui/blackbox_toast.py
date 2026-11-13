"""블랙박스 저장 반응을 게임 화면 위에 잠깐 보여주는 오버레이(블랙박스 명세 11.1).

항상 위·포커스를 빼앗지 않음·클릭 통과. 기본 위치는 게임 창이 있는 화면의 상단 중앙이며 약 3초 뒤 사라진다.
완료 문구는 실제 파일 검증을 마친 저장 결과에서만 띄운다(3절). 게임 창만 캡처하므로 녹화에는 원칙상 찍히지 않는다.
0.48.0: ② 게임 위 알림 공용 부품(game_notice.GameNotice)의 '보통' 크기 — 모양·자리·시간은 예전 그대로, 늘 맨 위.
"""
from __future__ import annotations

from PySide6.QtGui import QColor

from .game_notice import GameNotice

SHOW_MS = 3000
_COLORS = {'pending': QColor('#00d1a7'), 'done': QColor('#2ecc71'), 'failed': QColor('#ff8a65')}


def format_duration(us) -> str:
    seconds = max(0, int(us or 0) // 1_000_000)
    minutes, seconds = divmod(seconds, 60)
    return f'{minutes}분 {seconds}초' if minutes else f'{seconds}초'


class BlackboxToast(GameNotice):
    stack_rank = 0  # 알람 알림과 겹치면 블랙박스가 위(예전 자리), 알람은 그 아래

    def __init__(self) -> None:
        super().__init__(size='normal', colors=_COLORS, show_ms=SHOW_MS)
        self._kind = 'pending'

    def show_message(self, text, kind='pending', screen_rect=None, sticky=False):
        """kind: pending(진행) · done(완료) · failed(거부·실패). sticky면 끝날 때까지 유지, 아니면 SHOW_MS 뒤 사라짐."""
        super().show_message(text, kind, screen_rect, sticky)
