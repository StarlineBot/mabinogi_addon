"""Starline 말하기 GIF(사용자 확인용, QA 11-25 '말할 때 발이 변하고 색감이 달라짐') — 서기 → 클릭 → 말하기 → 서기.

실행: QT_QPA_PLATFORM=offscreen uv run --frozen --with pillow python -m scripts.render_starline_talk_gif
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon import paths  # noqa: E402
from mabinogi_addon.character import roster  # noqa: E402
from mabinogi_addon.character.brain import STARLINE, Brain, Floor  # noqa: E402
from mabinogi_addon.character.lines import Line, Picker, read  # noqa: E402
from mabinogi_addon.ui.pet_window import PetWindow, load_frames  # noqa: E402
from scripts.render_pet_gif import FPS, H, OUT, TASKBAR, W, Clock, compose  # noqa: E402


def main() -> None:
    QApplication.instance() or QApplication([])
    clock = Clock()
    floor = Floor(0, W, H - TASKBAR)
    sl = roster.by_pack("장난스러운 남성")
    brain = Brain(floor, rng=random.Random(7), profile=STARLINE, corner=(W - 170.0, floor.y))
    brain.pos = (300.0, floor.y)
    window = PetWindow(brain, load_frames("Starline", STARLINE), sl.color, game_front=lambda: False, clock=clock,
                       outline=sl.outline)
    picker = Picker(read(paths.resource_dir() / "characters" / "Starline" / "lines.json"), random.Random(3))
    window.events.connect(lambda events: [window.say(picker.pick(e[1])) for e in events if e[0] == "say"])
    frames = []

    def shoot(seconds: float, caption: str) -> None:
        for _ in range(int(seconds * FPS)):
            clock.t += 1 / FPS
            window.step()
            frames.append(compose(window, caption, False))

    brain._next_walk = clock.t + 999
    brain._next_idle = clock.t + 999
    brain._next_extra = clock.t + 999
    brain._next_rare = clock.t + 999
    shoot(1.0, "서 있기")
    brain.press(clock.t, *brain.pos)
    window.events.emit(brain.release(clock.t))
    shoot(3.4, "클릭 — 말하기(발·색 그대로) → 서기")
    window.say(Line("버프는 내가 볼게. 대가는 나중에.", "explain"))
    shoot(4.2, "긴 말 — 강조·깜빡임 장도 발이 같음")
    shoot(1.0, "서 있기")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "starline_talk.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    print(path, len(frames))


if __name__ == "__main__":
    main()
