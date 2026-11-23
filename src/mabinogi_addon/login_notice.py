"""로그인 1.0 예고(계정 명세 4.1, 사용자 결정 2026-11-23) — 문구·판정만(Qt 없음).

0.x 동안은 예고만: 비로그인 홈 맨 위 띠(매 실행), ✕는 확인 창(다시 보지 않기 = 1.0 제한 동의, general.loginNoticeAgreed),
앱 릴리즈 노트 창 맨 위 고정 블록(앱 버전 1.0.0 미만일 때). 실제 기능 잠금은 1.0에서.
"""
from __future__ import annotations

import re

TITLE = "❗ 꼭 읽어보세요 ❗"
BODY = ("정식 출시(1.0)부터 일부 기능은 디스코드 로그인 후 쓸 수 있어요. "
        "지금 로그인해 두면 1.0 이후에도 모든 기능을 그대로 쓰고, 설정도 서버에 저장돼요.")
LOGIN_BUTTON = "디스코드로 로그인"
CONFIRM_TITLE = "안내를 다시 보지 않을까요?"
CONFIRM_BODY = ("정식 출시(1.0)부터 일부 기능은 디스코드 로그인 후에만 쓸 수 있어요. "
                "다시 보지 않기를 누르면 이 내용에 동의한 것으로 보고, 1.0 이후 로그인하지 않으면 일부 기능을 쓸 수 없어요.")
AGREE_BUTTON = "다시 보지 않기"
CANCEL_BUTTON = "취소"


def _version_tuple(version: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", version or "")[:3]
    return tuple(int(n) for n in nums) if nums else (0,)


def before_1_0(version: str) -> bool:
    return _version_tuple(version) < (1, 0, 0)


def pinned_notes_block(version: str) -> str:
    """릴리즈 노트 창 맨 위 고정 블록(마크다운). 1.0.0 이상이면 빈 문자열."""
    return f"> **{TITLE}** {BODY}\n\n" if before_1_0(version) else ""


def show_home_notice(logged_in: bool, agreed: str | None) -> bool:
    """홈 띠를 보일지: 비로그인이고 '다시 보지 않기' 동의 기록이 없을 때."""
    return not logged_in and not agreed
