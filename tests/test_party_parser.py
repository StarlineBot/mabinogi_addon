from mabinogi_addon.party.parser import is_recruit, parse_recruit


def test_non_recruit_returns_none():
    # 파티모집이 아닌 일반 외침(# 로 시작 안 함)
    assert parse_recruit("홍길동 : 안녕하세요~", "홍길동", "2026-10-06T12:00:00+09:00") is None
    assert not is_recruit("홍길동 : 안녕", "홍길동")


def test_parse_basic_recruit():
    msg = "글렌해방 : #[채널14] 글렌베르나 레이드 딜러구함 [1/4명]"
    r = parse_recruit(msg, "글렌해방", "2026-10-06T12:00:00+09:00")
    assert r is not None
    assert r.character_name == "글렌해방"
    assert r.channel == "14"
    assert r.content == "글렌베르나 레이드 딜러구함"
    assert r.current == 1
    assert r.needed == 4
    assert r.done is False
    assert r.headcount == "1/4"


def test_done_by_wan_marker():
    r = parse_recruit("아무개 : #[채널7] 던전 [3/4명]완", "아무개", "t")
    assert r.done is True


def test_done_by_full_headcount():
    r = parse_recruit("아무개 : #[채널7] 던전 [8/8명]", "아무개", "t")
    assert r.done is True


def test_signature_ignores_numbers_and_names():
    # 같은 파티를 다른 사람이, 인원만 바뀌어 외쳐도 서명은 같아야 함
    a = parse_recruit("갑 : #[채널7] 브리레흐 딜러 2모집 [5/8명]", "갑", "t1")
    b = parse_recruit("을 : #[채널7] 브리레흐 딜러 1모집 [6/8명]", "을", "t2")
    assert a.signature == b.signature


def test_signature_differs_by_channel():
    a = parse_recruit("갑 : #[채널7] 같은내용 [1/4명]", "갑", "t")
    b = parse_recruit("갑 : #[채널8] 같은내용 [1/4명]", "갑", "t")
    assert a.signature != b.signature
