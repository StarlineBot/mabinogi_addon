"""거뿔 원시 데이터 → 현황판 리스트 / 키워드 알림. (순수 함수, 테스트 가능)"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .alerts import AlertState
from .models import Recruit
from .parser import parse_recruit

KST = timezone(timedelta(hours=9))
FRESH_MINUTES = 5


def _parse_recruits(raw: list[dict], excludes: set[str]) -> list[Recruit]:
    out: list[Recruit] = []
    for item in raw:
        recruit = parse_recruit(
            item.get("message", ""),
            item.get("character_name", ""),
            item.get("date_send", ""),
        )
        if recruit is None:
            continue
        if recruit.character_name in excludes:
            continue
        out.append(recruit)
    return out


def build_board(
    raw: list[dict], excludes: list[str] | set[str], list_size: int | None = None
) -> list[Recruit]:
    """현황판: 제외 파티장을 뺀 뒤 파티장(캐릭)별 최신 1건을 최신순으로 전부.

    같은 파티장이 인원 채우며 반복 외친 것만 묶고(최신 1건), 모집 중인 파티장은
    모두 표시한다. list_size가 주어지면 그 수만큼만 자른다(기본 무제한).
    """
    recruits = _parse_recruits(raw, set(excludes))
    recruits.sort(key=lambda r: r.date_send, reverse=True)

    seen: set[str] = set()
    board: list[Recruit] = []
    for recruit in recruits:
        if recruit.character_name in seen:
            continue
        seen.add(recruit.character_name)
        board.append(recruit)
        if list_size is not None and len(board) >= list_size:
            break
    return board


def humanize_age(date_send: str, now: datetime | None = None) -> str:
    """발송 시각을 상대 표기로. 예: "방금", "3분 전", "1시간 전". 파싱 불가면 빈 문자열."""
    try:
        sent = datetime.fromisoformat(date_send)
    except ValueError:
        return ""
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=KST)
    now = now or datetime.now(KST)
    seconds = max(0, (now - sent).total_seconds())
    if seconds < 60:
        return "방금"
    if seconds < 3600:
        return f"{int(seconds // 60)}분 전"
    if seconds < 86400:
        return f"{int(seconds // 3600)}시간 전"
    return f"{int(seconds // 86400)}일 전"


def _is_fresh(date_send: str, now: datetime, minutes: int) -> bool:
    try:
        sent = datetime.fromisoformat(date_send)
    except ValueError:
        return True  # 파싱 불가면 억제하지 않음
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=KST)
    seconds = (now - sent).total_seconds()
    return -60 <= seconds <= minutes * 60  # 약간의 시계 오차 허용


def find_alerts(
    raw: list[dict],
    keywords: list[str],
    excludes: list[str] | set[str],
    alert_state: AlertState,
    now: datetime | None = None,
) -> list[tuple[str, Recruit]]:
    """최근 5분 내 신규 모집 중 키워드 매칭 건을 (키워드, Recruit)로. 서명별 1회."""
    keywords = [kw.strip() for kw in keywords if isinstance(kw, str) and kw.strip()]  # 빈 키워드는 모든 글에 걸린다
    if not keywords:
        return []
    now = now or datetime.now(KST)

    fresh = [
        r
        for r in _parse_recruits(raw, set(excludes))
        if _is_fresh(r.date_send, now, FRESH_MINUTES)
    ]
    fresh.sort(key=lambda r: r.date_send)  # 오래된 → 최신 순 처리

    out: list[tuple[str, Recruit]] = []
    for recruit in fresh:
        matched = next((kw for kw in keywords if kw in recruit.content), None)
        if matched is None:
            continue
        if alert_state.should_alert(recruit.signature):
            out.append((matched, recruit))
    return out
