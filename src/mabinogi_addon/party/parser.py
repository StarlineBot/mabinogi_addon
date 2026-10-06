"""거뿔 외침 → Recruit 파싱. (섯다라인봇 partyAlerts.parseRecruit 포팅)

파티모집 형식: "{캐릭명} : #[채널N] 내용 [현재/모집명]완?"
"""

from __future__ import annotations

import re

from .models import Recruit

_CHANNEL = re.compile(r"#\[채널(\d+)\]")
_HEADCOUNT = re.compile(r"\[(\d+)/(\d+)명\](완)?")


def is_recruit(message: str, character_name: str) -> bool:
    """파티모집 외침인지. 본문이 "{캐릭명} : #"로 시작하면 파티모집."""
    return bool(message) and message.startswith(character_name + " : #")


def parse_recruit(message: str, character_name: str, date_send: str) -> Recruit | None:
    """파티모집이면 Recruit, 아니면 None."""
    if not is_recruit(message, character_name):
        return None

    body = message[len(character_name + " : ") :]

    channel_match = _CHANNEL.search(body)
    channel = channel_match.group(1) if channel_match else "?"
    channel_token = channel_match.group(0) if channel_match else ""

    hc = _HEADCOUNT.search(body)
    current = int(hc.group(1)) if hc else None
    needed = int(hc.group(2)) if hc else None
    done = bool(hc and (hc.group(3) == "완" or hc.group(1) == hc.group(2)))

    content = _CHANNEL.sub("", body)
    content = _HEADCOUNT.sub("", content).strip()

    # 서명: 채널 + (숫자·공백 제거한 내용). 남은 인원이 줄거나 공동모집이어도 같은 파티로 인식.
    sig_content = re.sub(r"\d+", "", content).replace(" ", "")
    signature = channel_token + "|" + sig_content

    return Recruit(
        character_name=character_name,
        channel=channel,
        content=content,
        current=current,
        needed=needed,
        done=done,
        date_send=date_send,
        signature=signature,
    )
