"""펫 창 진단 기록(QA 11-28 — 사용자 제보 '게임에서 알트탭하면 캐릭터도 사라짐', 간헐·재현 안 됨): 게임 앞/뒤가 바뀔 때
그 순간·0.5·2·5초 뒤 펫 창 상태를 app.log '[펫 창]' 한 줄로, 문의 묶음에 그 줄들을 붙임."""
from __future__ import annotations

import logging
import os
import random

from mabinogi_addon import inquiry_session as inq
from mabinogi_addon import paths
from mabinogi_addon.character import brain as br
from mabinogi_addon.system import pet_window_probe as probe


class FakeApi:
    """가짜 win32 — 펫 창 1001, 가운데 점에 보이는 창은 게임(2002, 다른 pid)."""
    def __init__(self, hit=2002, visible=True, iconic=False, ex=0x00080088):
        self.hit, self.visible, self.iconic, self.ex = hit, visible, iconic, ex

    def IsWindowVisible(self, hwnd): return self.visible  # noqa: E704,N802
    def IsIconic(self, hwnd): return self.iconic  # noqa: E704,N802
    def GetWindowLong(self, hwnd, index): return self.ex  # noqa: E704,N802
    def WindowFromPoint(self, point): return self.hit  # noqa: E704,N802
    def GetAncestor(self, hwnd, flag): return hwnd  # noqa: E704,N802
    def GetClassName(self, hwnd): return "Qt-pet" if hwnd == 1001 else "Mabinogi"  # noqa: E704,N802

    def GetWindowThreadProcessId(self, hwnd):  # noqa: N802
        return (1, os.getpid() if hwnd == 1001 else 4242)


def test_probe_reads_window_bits_and_what_is_at_center():
    got = probe.probe(1001, (100, 200), FakeApi())
    assert got["visible"] and not got["iconic"] and got["topmost"] and got["layered"] and got["toolwindow"]
    assert got["at_center"] == {"ours": False, "pid": 4242, "own_pid": False, "class": "Mabinogi"}
    ours = probe.probe(1001, (100, 200), FakeApi(hit=1001, ex=0))
    assert ours["at_center"]["ours"] and ours["at_center"]["own_pid"] and not ours["topmost"]

    class Broken(FakeApi):
        def GetWindowLong(self, hwnd, index):  # noqa: N802
            raise OSError("x")
    assert probe.probe(1001, (0, 0), Broken())["error"] == "OSError"   # 진단 실패가 앱을 멈추지 않음


def test_line_is_one_tagged_line_in_fixed_order():
    text = probe.line({"fg_now": "Client.exe", "why": "게임 앞", "after": 0.5, "shown": True, "extra": 1})
    assert text.startswith("[펫 창] why=게임 앞 after=0.5 shown=True fg_now=Client.exe") and text.endswith("extra=1")
    assert "\n" not in text


def test_front_change_logs_now_and_after_half_two_five_seconds(caplog):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from mabinogi_addon.ui import pet_window as pw

    clock = [100.0]
    front = {"on": False}
    fg = {"exe": "chrome.exe"}
    b = br.Brain(br.Floor(0, 1000, 700), rng=random.Random(1), profile=br.ARIA)
    b.pos = (300.0, 700.0)
    w = pw.PetWindow(b, pw.load_frames("아리아", br.ARIA), "#888888", game_front=lambda: front["on"],
                     clock=lambda: clock[0], foreground=lambda: fg["exe"])
    try:
        caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.pet_window")
        w.step()
        assert not [r for r in caplog.records if "[펫 창]" in r.getMessage()]   # 처음엔 바뀐 게 없음
        front["on"], fg["exe"] = True, "Client.exe"
        times = []
        for _ in range(140):   # 7초
            clock[0] += 0.05
            before = len(caplog.records)
            w.step()
            if len(caplog.records) > before:
                times.append(round(clock[0] - 100.0, 2))
        lines = [r.getMessage() for r in caplog.records if "[펫 창]" in r.getMessage()]
        assert len(lines) == 4
        assert [line.split("after=")[1].split()[0] for line in lines] == ["0.0", "0.5", "2.0", "5.0"]
        first = lines[0]
        for key in ("why=게임 앞", "shown=", "logical=", "physical=", "screen=", "win32=", "state=", "pos=", "goal=",
                    "blocked=", "fg_before=chrome.exe", "fg_now=Client.exe"):
            assert key in first, key
        assert times[0] <= 0.35 and abs((times[1] - times[0]) - 0.5) < 0.11 and abs((times[3] - times[0]) - 5.0) < 0.11
        line = w.probe_line("게임 밖", 0.0, FakeApi())
        assert "'at_center': {'ours': False" in line and "'topmost': True" in line   # 가짜 win32 결과가 그대로 한 줄에
    finally:
        w.close()


def test_inquiry_attaches_pet_window_lines(tmp_path):
    log = paths.user_data_dir() / "logs" / "app.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("10:00 INFO a: [펫 창] why=게임 밖 after=0.0 shown=True\n10:00 INFO b: 다른 줄\n", encoding="utf-8")
    s = inq.Session(inq.CARD_BY_KEY["other"], root=tmp_path)
    inq.attach_pet_window(s)
    item = next(a for a in s.attachments if a.name == "pet_window_log.txt")
    assert item.path.read_text(encoding="utf-8") == "10:00 INFO a: [펫 창] why=게임 밖 after=0.0 shown=True\n"
    empty = inq.Session(inq.CARD_BY_KEY["other"], root=tmp_path / "b")
    log.write_text("없음\n", encoding="utf-8")
    inq.attach_pet_window(empty)
    assert not empty.attachments   # 기록이 없으면 안 붙임
