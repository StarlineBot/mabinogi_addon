"""호감도 구간 100으로 올렸을 때 stage_up 말풍선 렌더(사용자 확인용) — 다래·아리아 각 1장.

실행: QT_QPA_PLATFORM=offscreen uv run --with pillow python -m scripts.render_stage_up
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon import paths  # noqa: E402
from mabinogi_addon.character import roster  # noqa: E402
from mabinogi_addon.character.brain import PROFILES, Brain, Floor  # noqa: E402
from mabinogi_addon.character.lines import Picker, read  # noqa: E402
from mabinogi_addon.ui.pet_window import PetWindow, load_frames  # noqa: E402
from scripts.render_pet_gif import OUT, TASKBAR, Clock, compose, H, W  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication([])
    for pack, name in (("조용한 여성", "dare"), ("부드러운 여성", "aria")):
        character = roster.by_pack(pack)
        folder = roster.folder(character)
        clock = Clock()
        floor = Floor(0, W, H - TASKBAR)
        brain = Brain(floor, rng=random.Random(1), profile=PROFILES[folder])
        brain.pos = (W / 2, floor.y)
        brain._next_walk = brain._next_extra = clock.t + 99
        window = PetWindow(brain, load_frames(folder, PROFILES[folder]), character.color, clock=clock)
        line = Picker(read(paths.resource_dir() / "characters" / folder / "lines.json")).stage_up(100)
        window.say(line)
        for _ in range(int(len(line.text) * 0.07 * 10) + 4):  # 글자가 다 나올 때까지
            clock.t += 0.1
            window.step()
        compose(window, f"{character.name} — 호감도 100으로 올림(제작자 구간 버튼): 구간 오름 대사", False) \
            .convert("RGB").save(OUT / f"stage_up_100_{name}.png")
    app.processEvents()
    print(OUT)


if __name__ == "__main__":
    main()
