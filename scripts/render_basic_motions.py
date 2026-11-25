"""기본 동작 4종 GIF(기획 11-25) — 아리아 기지개·레나 마법 펑·Starline 재채기(말풍선)·다래 구석에서 엎드려 자기.

실행: QT_QPA_PLATFORM=offscreen uv run --with pillow python -m scripts.render_basic_motions
서 있기 → 드문 동작 1바퀴 → 서 있기(크기·색이 이어지는지), 다래는 구석 졸기 → 엎드림 → 숨쉬기 → 게임 끝 앉아 일어남.
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
from scripts.render_pet_gif import FPS, H, OUT, TASKBAR, W, Clock, compose  # noqa: E402


def run(folder: str, frames_out: list) -> None:
    character = next(c for c in roster.ROSTER if roster.folder(c) == folder)
    profile = PROFILES[folder]
    if profile.sleep_after:   # 렌더용으로 짧게(앱은 5~10분)
        from dataclasses import replace
        profile = replace(profile, sleep_after=(6.0, 6.0))
    clock = Clock()
    front = {"on": False}
    floor = Floor(0, W, H - TASKBAR)
    brain = Brain(floor, rng=random.Random(5), profile=profile, corner=(W / 2, floor.y))
    brain.pos = (W / 2, floor.y)
    window = PetWindow(brain, load_frames(folder, profile), character.color, game_front=lambda: front["on"],
                       clock=clock, outline=character.outline)
    picker = Picker(read(paths.resource_dir() / "characters" / folder / "lines.json"), random.Random(3))
    window.events.connect(lambda events: [window.say(picker.pick(e[1])) for e in events if e[0] == "say"])
    brain._next_walk = brain._next_idle = brain._next_extra = clock.t + 9999

    def shoot(seconds, caption):
        for _ in range(int(seconds * FPS)):
            clock.t += 1 / FPS
            window.step()
            frames_out.append(compose(window, f"{folder} — {caption}", front["on"]))

    if profile.rare_extra:
        shoot(1.0, "서 있기")
        brain._next_rare = clock.t
        length = sum(profile.anims[profile.rare_extra][1])
        shoot(length + 1.5, {"stretch": "기지개", "magic": "마법 연습 펑", "sneeze": "재채기"}[profile.rare_extra])
    else:  # 다래: 구석에서 졸다가 엎드려 자기
        front["on"] = True
        shoot(9.0, "구석에서 졸다가(앱은 5~10분 뒤) 엎드림")
        shoot(4.0, "엎드려 숨쉬기(Zzz)")
        front["on"] = False
        shoot(7.0, "게임이 끝나면 눈 비비며 앉고 일어남")
    window.close()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    for folder in ("아리아", "레나", "Starline", "다래"):
        frames: list = []
        run(folder, frames)
        name = {"아리아": "aria", "레나": "lena", "Starline": "starline", "다래": "dare"}[folder]
        path = OUT / f"basic_motion_{name}.gif"
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
        print(path, len(frames))
    app.processEvents()


if __name__ == "__main__":
    main()
