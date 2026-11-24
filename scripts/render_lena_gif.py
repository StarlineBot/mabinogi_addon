"""레나 펫 동작 GIF(사용자 확인용) — 서기·걷기, 서서 클릭(바로 말하기 → 끝 두 장), 설명(손가락), 쓰다듬기(참는 중 1px 떨림 → '흥'),
끌기 → 떨어지기 한 장 → 착지 4장 → 서기, 구석(쪼그려 앉아 다리 꼬고 기다림 · 클릭).

실행: QT_QPA_PLATFORM=offscreen uv run --with pillow python -m scripts.render_lena_gif
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon import paths  # noqa: E402
from mabinogi_addon.character import roster  # noqa: E402
from mabinogi_addon.character.brain import LENA, Brain, Floor  # noqa: E402
from mabinogi_addon.character.lines import Line, Picker, read  # noqa: E402
from mabinogi_addon.ui.pet_window import PetWindow, load_frames  # noqa: E402
from scripts.render_pet_gif import FPS, H, OUT, TASKBAR, W, Clock, compose  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication([])
    clock = Clock()
    front = {"on": False}
    floor = Floor(0, W, H - TASKBAR)
    lena = roster.by_pack("화난 여성")
    brain = Brain(floor, rng=random.Random(7), profile=LENA, corner=(W - 170.0, floor.y))
    brain.pos = (260.0, floor.y)
    window = PetWindow(brain, load_frames("레나", LENA), lena.color, game_front=lambda: front["on"], clock=clock)
    picker = Picker(read(paths.resource_dir() / "characters" / "레나" / "lines.json"), random.Random(3))
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
    shoot(1.2, "서 있기(팔짱)")
    brain._walk_to((420.0, floor.y), clock.t)
    shoot(2.2, "걷기 — 0.22초·초당 90px")
    brain._next_walk = clock.t + 99
    brain.press(clock.t, *brain.pos); window.events.emit(brain.release(clock.t))
    shoot(3.2, "서서 클릭 — 바로 말하기 → 끝 두 장 → 서기")
    window.say(Line("게임에나 집중해. 버프는 내가 봐.", "explain"))
    shoot(3.6, "말하기 — 설명(손가락 먼저)")
    x0, y0 = brain.pos[0], brain.pos[1] - 175
    window.events.emit(brain.hover(clock.t, x0, True))
    shoot(3.5, "쓰다듬기 — 움찔 → 이 악묾 → 참는 중(1px 떨림)",
          each=lambda i: window.events.emit(brain.hover(clock.t, x0 + (12 if (i // 3) % 2 else -12), True)))
    shoot(2.4, "손 떼면 '흥' → 서기")
    brain._next_walk = clock.t + 99
    x0, y0 = brain.pos[0], brain.pos[1] - 100
    brain.press(clock.t, x0, y0)
    shoot(1.4, "끌기", each=lambda i: window.events.emit(brain.move(clock.t, x0 + i * 4, y0 - i * 6)))
    window.events.emit(brain.release(clock.t))
    shoot(3.8, "떨어지기(한 장) → 착지 4장 → 서기")
    front["on"] = True
    shoot(12.0, "게임이 앞 — 구석에 앉아 기다림(가끔 발끝·한숨·깜빡임)")
    brain.press(clock.t, brain.pos[0], brain.pos[1] - 60); window.events.emit(brain.release(clock.t))
    shoot(3.0, "앉아서 클릭 — 앉은 그대로 말풍선")
    front["on"] = False
    shoot(2.5, "게임이 뒤로 — 일어남")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "lena_pet_actions.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    print(path, len(frames))
    app.processEvents()


if __name__ == "__main__":
    main()
