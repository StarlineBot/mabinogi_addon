"""자동 찾기 v2 찾기 엔진 순수 로직(docs/autofind-v2-creator-spec.md 3·6절) — 가짜 프레임·가짜 시계."""
import numpy as np

from mabinogi_addon import autofind_v2 as v2


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _frame():
    return np.zeros((100, 200, 3), np.uint8)


def test_initial_order_reuses_one_frame_and_waits_for_appear_items():
    frame = _frame()
    seen = []

    def finder(name, box):
        def run(f):
            seen.append((name, id(f)))
            return box
        return run
    finders = {"skillbar": finder("skillbar", (1, 1, 10, 10)), "stat_bars": finder("stat_bars", None),
               "buff": finder("buff", (5, 5, 20, 40)),
               "resources": finder("resources", {"dorcha": (2, 2, 5, 5), "tuarim": None}),
               "boss": finder("boss", None), "halo_timer": finder("halo_timer", (3, 3, 6, 6))}
    out = v2.run_initial(frame, finders, sleep=lambda s: None)
    assert [n for n, _ in seen] == ["skillbar", "stat_bars", "buff", "resources", "boss", "halo_timer"]  # 빠르고 확실한 것부터
    assert {i for _, i in seen} == {id(frame)}  # 한 번 찍은 화면 재사용
    assert out.status == {"skillbar": "found", "stat_bars": "missing", "buff": "found", "dorcha": "found",
                          "tuarim": "missing", "boss": "waiting", "halo_timer": "found"}


def test_last_position_checked_first_and_skips_search():
    frame = _frame()
    calls = []
    out = v2.run_initial(frame, {"dorcha": lambda f: calls.append(1)}, last={"dorcha": (0, 0, 10, 10)},
                         readers={"dorcha": lambda crop: crop.shape == (10, 10, 3)}, sleep=lambda s: None)
    assert out.status["dorcha"] == "found" and out.source["dorcha"] == "last" and calls == []


def _margin_finder(at, calls):
    """여백 조각이면 그 안의 자리(at은 화면 좌표), 화면 전체면 at 그대로 — 호출 크기를 기록."""
    def run(f):
        calls.append(f.shape[:2])
        if f.shape[:2] == (100, 200):
            return at
        x0, y0, x1, y1 = v2.margin_rect(LAST, 200, 100)
        return (at[0] - x0, at[1] - y0, at[2], at[3]) if f.shape[:2] == (y1 - y0, x1 - x0) else None
    return run


LAST = (40, 30, 50, 12)


def test_detector_items_check_last_spot_in_margin_crop():
    """QA 536ec7c: 단축바·체력바·버프는 지난 자리 딱 맞는 조각이 아니라 둘레 여백 조각에 탐지기 — 4px 이내면 '지난 자리 그대로'."""
    calls = []
    out = v2.run_initial(_frame(), {"skillbar": _margin_finder((42, 31, 50, 12), calls)}, last={"skillbar": LAST},
                         sleep=lambda s: None)
    assert out.status["skillbar"] == "found" and out.source["skillbar"] == "last"
    assert out.boxes["skillbar"] == (42, 31, 50, 12)  # 쓰는 자리는 지금 찾은 자리
    assert (100, 200) not in calls and len(calls) == 1  # 화면 전체 탐지 없음


def test_detector_item_moved_within_margin_is_new_spot():
    calls = []
    out = v2.run_initial(_frame(), {"stat_bars": _margin_finder((60, 40, 50, 12), calls)}, last={"stat_bars": LAST},
                         sleep=lambda s: None)
    assert out.status["stat_bars"] == "found" and out.source["stat_bars"] == "search" and out.boxes["stat_bars"] == (60, 40, 50, 12)


def test_detector_item_not_in_margin_falls_back_to_full_search():
    calls = []
    out = v2.run_initial(_frame(), {"buff": _margin_finder((150, 80, 20, 10), calls)}, last={"buff": (0, 0, 20, 10)},
                         sleep=lambda s: None)
    assert out.source["buff"] == "search" and out.boxes["buff"] == (150, 80, 20, 10)
    assert calls[-1] == (100, 200)  # 여백에서 못 찾아 화면 전체


def test_known_spot_from_ui_check_is_reused():
    calls = []
    out = v2.run_initial(_frame(), {"skillbar": _margin_finder(LAST, calls)}, last={"skillbar": LAST},
                         known={"skillbar": (41, 30, 50, 12)}, sleep=lambda s: None)
    assert out.source["skillbar"] == "last" and calls == []  # 앞의 'UI 보이나' 확인 결과 그대로


def test_cpu_cap_marks_rest_missing():
    cpu = {"t": 0.0}

    def slow(_f):
        cpu["t"] += 15.0
        return None
    finders = {k: slow for k in ("skillbar", "stat_bars", "buff", "resources", "boss", "halo_timer")}
    out = v2.run_initial(_frame(), finders, cpu_clock=lambda: cpu["t"], sleep=lambda s: None, cpu_limit=20.0)
    assert out.stopped_by_cap
    assert out.status["buff"] == "missing" and out.status["dorcha"] == "missing"  # 상한 넘어 건너뜀
    assert out.status["boss"] == "waiting"  # 나타나면 찾기 항목은 대기
    assert cpu["t"] == 30.0  # 두 개 돌고 멈춤


def _stable_engine(now=0.0):
    e = v2.Engine()
    e.reset(now)
    gen = e.begin_initial()
    res = v2.InitialResult(boxes={"buff": (1, 1, 10, 10), "dorcha": (2, 2, 5, 5)},
                           status={"buff": "found", "dorcha": "found", "tuarim": "missing", "skillbar": "found",
                                   "stat_bars": "found", "boss": "waiting", "halo_timer": "waiting"}, wall=3.0, cpu=1.0)
    assert e.finish_initial(gen, res, now)
    return e


def test_stable_state_makes_no_search_calls():
    e = _stable_engine()
    calls = e.search_calls
    wanted = lambda k: k != "tuarim"  # noqa: E731 — 투아림은 꺼진 기능(다시 찾지 않음)
    for i in range(1, 1200):  # 10분, 0.5초마다
        now = i * 0.5
        e.tick(now, True)
        e.note_read("buff", True, now)
        e.note_read("dorcha", True, now)
        assert e.due(now, wanted) == []
    assert e.search_calls == calls  # 안정 = 찾기 0(대기 항목도 꺼져 있으면 0)
    assert e.appear_due(600.0, lambda k: False) is None


def test_research_after_10s_then_slow_after_three_failures_and_reset_on_recovery():
    e = _stable_engine()
    wanted = lambda k: True  # noqa: E731
    t = 0.0
    e.tick(t, True)  # 첫 틱은 시간 기준만 잡는다
    e.note_read("buff", False, t)
    while t < 10.0:
        t += 0.5
        e.tick(t, True)
    assert "buff" not in e.due(t, wanted)  # 10초 '넘게'
    t += 0.5
    e.tick(t, True)
    assert "buff" in e.due(t, wanted)
    for n in range(3):
        gen = e.start_search(["buff"])
        e.search_result(gen, "buff", None, t)
    assert e.items["buff"].failures == 3 and e.items["buff"].next_try == t + 60  # 3번 연속 실패 → 1분 간격
    e.note_read("buff", True, t + 1)
    assert e.items["buff"].failures == 0 and e.items["buff"].lost == 0  # 복구 시 초기화


def test_paused_time_is_not_counted():
    e = _stable_engine()
    e.note_read("buff", False, 0.0)
    e.tick(0.0, True)
    for i in range(1, 100):  # 최소화·뒤로 감 50초
        e.tick(i * 0.5, False)
    assert e.items["buff"].lost == 0.0 and e.due(50.0, lambda k: True) in ([], ["tuarim"])


def test_new_spot_confirms_after_3s_of_fresh_reads_and_failure_restarts():
    e = _stable_engine()
    gen = e.start_search(["buff"])
    e.search_result(gen, "buff", (9, 9, 10, 10), 0.0)
    assert e.region("buff") == (9, 9, 10, 10)  # 확정 전엔 새 자리로 읽어 보기만
    assert e.note_read("buff", True, 0.0, frame_id=1) is None
    assert e.note_read("buff", True, 1.0, frame_id=1) is None  # 같은 판독(새 화면 아님)은 세지 않음
    assert e.note_read("buff", True, 2.0, frame_id=2) is None
    assert e.note_read("buff", False, 2.5, frame_id=3) is None  # 실패 한 번 → 처음부터
    assert e.note_read("buff", True, 3.0, frame_id=4) is None
    assert e.note_read("buff", True, 5.0, frame_id=5) is None
    assert e.note_read("buff", True, 6.0, frame_id=6) == "confirmed"
    assert e.items["buff"].box == (9, 9, 10, 10) and e.items["buff"].source == "research"


def test_trial_gives_up_after_10s():
    e = _stable_engine()
    gen = e.start_search(["buff"])
    e.search_result(gen, "buff", (9, 9, 10, 10), 0.0)
    assert e.note_read("buff", False, 10.5, frame_id=1) == "failed"
    assert e.items["buff"].failures == 1 and e.region("buff") == (1, 1, 10, 10)


def test_window_change_discards_running_results():
    e = v2.Engine()
    e.reset(0.0)
    gen = e.begin_initial()
    e.reset(1.0)  # 창 크기 변경 → 세대 올림
    assert not e.finish_initial(gen, v2.InitialResult(status={"buff": "found"}, boxes={"buff": (1, 1, 2, 2)}), 2.0)
    assert e.phase == "waiting_ui" and e.items["buff"].box is None
    e2 = _stable_engine()
    g = e2.start_search(["buff"])
    e2.reset(5.0)
    assert not e2.search_result(g, "buff", (3, 3, 3, 3), 6.0)  # 늦은 결과 버림


def test_user_override_wins_for_the_run():
    e = _stable_engine()
    e.user_override("buff")
    assert e.region("buff") is None  # 제공자는 저장 영역(사용자 지정)을 쓰게 된다
    g = e.start_search(["buff"])
    assert not e.search_result(g, "buff", (4, 4, 4, 4), 1.0)
    e.reset(2.0)
    assert e.items["buff"].user  # 지금 다시 찾기 후에도 이번 실행 동안 유지


def test_appear_small_every_second_full_every_minute():
    e = _stable_engine()
    wanted = lambda k: k == "boss"  # noqa: E731
    modes = []
    for i in range(0, 121):
        got = e.appear_due(float(i), wanted)
        if got:
            modes.append((i, got[1]))
    full = [i for i, m in modes if m == "full"]
    assert full == [60, 120] and len([m for _, m in modes if m == "small"]) == 119
    assert e.appear_result(e.generation, "boss", (1, 2, 3, 4))
    assert e.appear_due(200.0, wanted) is None  # 찾으면 대기 끝


def test_ui_not_ready_retries_after_10s():
    e = v2.Engine()
    e.reset(0.0)
    assert e.ready_for_initial(0.0)
    e.ui_not_ready(0.0)
    assert not e.ready_for_initial(9.9) and e.ready_for_initial(10.0)


def _pending_engine():
    e = v2.Engine()
    e.reset(0.0)
    gen = e.begin_initial()
    out = v2.run_initial(_frame(), {}, last={"boss": (10, 10, 50, 8), "halo_timer": (20, 30, 16, 8)},
                         readers={"boss": lambda c: False, "halo_timer": lambda c: False}, sleep=lambda s: None)
    assert out.source["boss"] == v2.LAST_PENDING and out.status["boss"] == "found"
    assert e.finish_initial(gen, out, 0.0)
    return e


def test_last_spot_pending_skips_appear_and_full_checks_every_5_minutes():
    e = _pending_engine()
    wanted = lambda k: k in ("boss", "halo_timer")  # noqa: E731
    due = [(t, e.appear_due(float(t), wanted)) for t in range(0, 601)]
    assert [(t, d) for t, d in due if d] == [(300, (["boss", "halo_timer"], "full")), (600, (["boss", "halo_timer"], "full"))]
    assert e.region("boss") == (10, 10, 50, 8)
    assert e.note_read("boss", False, 601.0) is None and e.items["boss"].pending
    assert e.note_read("boss", True, 602.0) == "confirmed_last" and not e.items["boss"].pending
    assert e.note_read("boss", True, 603.0) is None
    assert e.appear_result(e.generation, "halo_timer", (21, 31, 16, 8)) == "confirmed_last"  # 4px 이내 = 같은 자리
    assert e.items["halo_timer"].box == (20, 30, 16, 8)
    assert e.appear_due(900.0, wanted) is None  # 모두 확인됨 → 더 안 봄


def test_last_spot_pending_moves_when_full_check_finds_other_place():
    e = _pending_engine()
    assert e.appear_result(e.generation, "boss", None) is None and e.items["boss"].pending  # 화면에 없음 → 그대로
    assert e.appear_result(e.generation, "boss", (5, 40, 60, 10)) == "moved"
    it = e.items["boss"]
    assert it.box == (5, 40, 60, 10) and not it.pending and it.source == "appear"
    assert e.appear_result(e.generation, "boss", (99, 99, 9, 9)) is None  # 확인된 자리는 덮지 않음

