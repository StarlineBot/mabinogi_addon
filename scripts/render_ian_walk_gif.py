"""이안 걷기 v3 GIF(사용자·QA 확인용, 11-25) — 기본 옷과 넥타이 조끼가 나란히 걸음.

실행: QT_QPA_PLATFORM=offscreen uv run --frozen --with pillow python -m scripts.render_ian_walk_gif
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon.character import roster  # noqa: E402
from mabinogi_addon.character.brain import IAN, Brain, Floor  # noqa: E402
from mabinogi_addon.ui.pet_window import PetWindow, load_frames  # noqa: E402
from scripts.render_pet_gif import FPS, H, OUT, TASKBAR, W, Clock, compose  # noqa: E402


def main() -> None:
    QApplication.instance() or QApplication([])
    ian = roster.by_pack("부드러운 남성")
    shots = []
    for outfit in ("", "vest_tie"):
        clock = Clock()
        floor = Floor(0, W, H - TASKBAR)
        brain = Brain(floor, rng=random.Random(5), profile=IAN, corner=(W - 170.0, floor.y))
        brain.pos = (120.0, floor.y)
        brain._next_idle = brain._next_extra = 999
        window = PetWindow(brain, load_frames("이안", IAN, outfit), ian.color, game_front=lambda: False, clock=clock,
                           outline=ian.outline)
        brain._walk_to((W - 120.0, floor.y), clock.t)
        frames = []
        for _ in range(int(4.0 * FPS)):
            clock.t += 1 / FPS
            window.step()
            frames.append(compose(window, "걷기 v3 — " + ("넥타이 조끼" if outfit else "기본"), False))
        shots.append(frames)
        window.stop()
    merged = []
    for a, b in zip(*shots):
        img = Image.new("RGB", (a.width, a.height + b.height))
        img.paste(a, (0, 0))
        img.paste(b, (0, a.height))
        merged.append(img)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "ian_walk_v3.gif"
    merged[0].save(path, save_all=True, append_images=merged[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    print(path, len(merged))


if __name__ == "__main__":
    main()
