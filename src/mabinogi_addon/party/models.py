"""파티모집 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Recruit:
    """거뿔 외침에서 파싱한 파티모집 한 건."""

    character_name: str  # 파티장(외친 캐릭터)
    channel: str  # 채널 번호 ("7") 또는 "?"
    content: str  # 제목(채널·인원·완 제거)
    current: int | None  # 현재 인원
    needed: int | None  # 모집 인원
    done: bool  # 완료 여부(완 표기 또는 current==needed)
    date_send: str  # API가 준 발송 시각(ISO 문자열)
    signature: str  # 중복 알림 억제용 서명(채널+숫자·공백 제거 내용)

    @property
    def headcount(self) -> str:
        """표시용 인원 문자열. 예: "1/4". 정보 없으면 빈 문자열."""
        if self.current is None or self.needed is None:
            return ""
        return f"{self.current}/{self.needed}"
