"""이안 펫 동작 GIF(사용자 확인용) — 서기↔시계 보기, 서서 클릭(시선 위 → 말하기), 끌기→떨어지기→착지,
구석(쪼그려 앉아 시계), 말하기·알림(시계 가리키며).

실행: QT_QPA_PLATFORM=offscreen uv run --with pillow python -m scripts.render_ian_gif
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon import paths  # noqa: E402
from mabinogi_addon.character import roster  # noqa: E402
from mabinogi_addon.character.brain import IAN, Brain, Floor  # noqa: E402
from mabinogi_addon.character.lines import Line, Picker, read  # noqa: E402
from mabinogi_addon.ui.pet_window import PetWindow, load_frames  # noqa: E402
from scripts.render_pet_gif import FPS, H, OUT, TASKBAR, W, Clock, compose  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication([])
    clock = Clock()
    front = {"on": False}
    floor = Floor(0, W, H - TASKBAR)
    ian = roster.by_pack("차분한 남성")
    brain = Brain(floor, rng=random.Random(7), profile=IAN, corner=(W - 170.0, floor.y))
    brain.pos = (260.0, floor.y)
    window = PetWindow(brain, load_frames("이안", IAN), ian.color, game_front=lambda: front["on"], clock=clock)
    picker = Picker(read(paths.resource_dir() / "characters" / "이안" / "lines.json"), random.Random(3))
    window.events.connect(lambda events: [window.say(picker.pick(e[1])) for e in events if e[0] == "say"])
    frames = []

    def shoot(seconds: float, caption: str, each=None) -> None:
        for i in range(int(seconds * FPS)):
            clock.t += 1 / FPS
            if each:
                each(i)
            window.step()
            frames.append(compose(window, caption, front["on"]))

    brain._next_walk = clock.t + 99
    brain._next_idle = clock.t + 999
    shoot(1.5, "서 있기")
    brain._next_extra = clock.t
    shoot(2.5, "가만히 서 있으면 가끔 시계 보기")
    brain.press(clock.t, *brain.pos); window.events.emit(brain.release(clock.t))
    shoot(3.0, "서서 클릭 — 시선 위 → 말하기")
    brain._go("watch", clock.t); brain._extra_until = clock.t + 5
    shoot(0.6, "시계 보는 중")
    brain.press(clock.t, *brain.pos); window.events.emit(brain.release(clock.t))
    shoot(3.0, "시계 보는 중 클릭")
    brain._next_extra = clock.t + 99
    for text, mood, label in (("여기 있습니다.", "normal", "말하기 — 보통(입)"),
                              ("다녀오세요. 버프는 제가 보겠습니다.", "explain", "말하기 — 설명(손짓)")):
        window.say(Line(text, mood))
        shoot(3.2, label)
    brain.notify(clock.t)
    window.say(picker.alert("비바체 연장.mp3"))
    shoot(3.0, "알림 — 시계를 가리키며 말함")
    x0, y0 = brain.pos[0], brain.pos[1] - 100
    brain.press(clock.t, x0, y0)
    shoot(1.6, "끌기 — 늘어진 회사원", each=lambda i: window.events.emit(brain.move(clock.t, x0 + i * 5, y0 - i * 6)))
    window.events.emit(brain.release(clock.t))
    shoot(3.0, "놓으면 떨어지기 → 두 발 착지 → 바로 서기")
    front["on"] = True
    shoot(9.0, "게임이 앞 — 구석에서 쪼그려 앉아 시계 보기")
    brain.press(clock.t, brain.pos[0], brain.pos[1] - 60); window.events.emit(brain.release(clock.t))
    shoot(3.0, "앉아서 클릭 — 앉은 그대로 말풍선")
    front["on"] = False
    shoot(2.5, "게임이 뒤로 — 일어남")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "ian_pet_actions.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    print(path, len(frames))
    app.processEvents()


if __name__ == "__main__":
    main()
