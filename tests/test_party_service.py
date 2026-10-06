from datetime import datetime, timedelta, timezone

from mabinogi_addon.party.alerts import AlertState
from mabinogi_addon.party.service import KST, build_board, find_alerts


def _now():
    return datetime(2026, 10, 6, 12, 0, 0, tzinfo=KST)


def _iso(minutes_ago):
    return (_now() - timedelta(minutes=minutes_ago)).isoformat()


def _raw(name, ch, title, cur, need, minutes_ago, done=False):
    tail = "완" if done else ""
    return {
        "character_name": name,
        "message": f"{name} : #[채널{ch}] {title} [{cur}/{need}명]{tail}",
        "date_send": _iso(minutes_ago),
    }


def test_board_latest_per_person_all():
    raw = [
        _raw("A", 1, "글렌 레이드", 1, 4, 1),
        _raw("A", 1, "글렌 레이드", 2, 4, 0),  # 같은 사람 최신 → 이게 남아야
        _raw("B", 2, "브리레흐", 3, 8, 2),
        _raw("C", 3, "탈라가흐", 1, 4, 3),
    ]
    board = build_board(raw, excludes=[])  # 무제한
    assert [r.character_name for r in board] == ["A", "B", "C"]  # 파티장별 1건 전부, 최신순
    assert board[0].current == 2  # A의 최신 건


def test_board_optional_cap():
    raw = [
        _raw("A", 1, "글렌", 1, 4, 0),
        _raw("B", 2, "브리레흐", 3, 8, 1),
        _raw("C", 3, "탈라가흐", 1, 4, 2),
    ]
    board = build_board(raw, excludes=[], list_size=2)
    assert [r.character_name for r in board] == ["A", "B"]


def test_board_excludes_leader():
    raw = [_raw("A", 1, "글렌", 1, 4, 0), _raw("시끄러운놈", 2, "스팸", 1, 4, 0)]
    board = build_board(raw, excludes=["시끄러운놈"], list_size=5)
    assert [r.character_name for r in board] == ["A"]


def test_board_ignores_non_recruit():
    raw = [
        {"character_name": "A", "message": "A : 그냥 인사", "date_send": _iso(0)},
        _raw("B", 1, "글렌", 1, 4, 0),
    ]
    board = build_board(raw, excludes=[], list_size=5)
    assert [r.character_name for r in board] == ["B"]


def test_alert_matches_keyword_once():
    state = AlertState()
    raw = [_raw("A", 1, "글렌베르나 레이드", 1, 4, 1)]
    hits = find_alerts(raw, keywords=["글렌"], excludes=[], alert_state=state, now=_now())
    assert len(hits) == 1
    assert hits[0][0] == "글렌"
    # 같은 파티 재외침 → 서명 중복으로 억제
    hits2 = find_alerts(raw, keywords=["글렌"], excludes=[], alert_state=state, now=_now())
    assert hits2 == []


def test_alert_skips_old_recruit():
    state = AlertState()
    raw = [_raw("A", 1, "글렌 레이드", 1, 4, 10)]  # 10분 전 → 5분 초과
    hits = find_alerts(raw, keywords=["글렌"], excludes=[], alert_state=state, now=_now())
    assert hits == []


def test_alert_skips_excluded_leader():
    state = AlertState()
    raw = [_raw("시끄러운놈", 1, "글렌 레이드", 1, 4, 0)]
    hits = find_alerts(raw, ["글렌"], ["시끄러운놈"], state, now=_now())
    assert hits == []


def test_alert_no_keyword_no_scan():
    state = AlertState()
    raw = [_raw("A", 1, "글렌", 1, 4, 0)]
    assert find_alerts(raw, keywords=[], excludes=[], alert_state=state, now=_now()) == []
