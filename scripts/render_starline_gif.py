"""Starline 펫 동작 GIF(사용자 확인용) — 서기↔손바닥 불꽃, 걷기, 서서 클릭(바로 말하기 → 끝 두 장), 설명, 쓰다듬기,
끌기 → 떨어지기 → 착지 → 서기, 구석(앉아 마법진 돌리기 · 클릭).

실행: QT_QPA_PLATFORM=offscreen uv run --with pillow python -m scripts.render_starline_gif
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
    app = QApplication.instance() or QApplication([])
    clock = Clock()
    front = {"on": False}
    floor = Floor(0, W, H - TASKBAR)
    sl = roster.by_pack("장난스러운 남성")
    brain = Brain(floor, rng=random.Random(7), profile=STARLINE, corner=(W - 170.0, floor.y))
    brain.pos = (260.0, floor.y)
    window = PetWindow(brain, load_frames("Starline", STARLINE), sl.color, game_front=lambda: front["on"], clock=clock,
                       outline=sl.outline)
    picker = Picker(read(paths.resource_dir() / "characters" / "Starline" / "lines.json"), random.Random(3))
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
    shoot(1.2, "서 있기(씩 웃음)")
    brain._next_extra = clock.t
    shoot(1.5, "가만히 서 있으면 가끔 손바닥 불꽃")
    brain.press(clock.t, *brain.pos); window.events.emit(brain.release(clock.t))
    shoot(2.6, "불꽃 중 클릭")
    brain._next_extra = clock.t + 99
    brain._go("stand", clock.t)
    brain._walk_to((420.0, floor.y), clock.t)
    shoot(2.2, "걷기 — 0.22초·초당 75px(×1.15)")
    brain._next_walk = clock.t + 99
    brain.press(clock.t, *brain.pos); window.events.emit(brain.release(clock.t))
    shoot(3.2, "서서 클릭 — 바로 말하기 → 끝 두 장 → 서기")
    window.say(Line("버프는 내가 볼게. 대가는 나중에.", "explain"))
    shoot(3.6, "말하기 — 설명(손가락 튕김 먼저)")
    x0, y0 = brain.pos[0], brain.pos[1] - 175
    window.events.emit(brain.hover(clock.t, x0, True))
    shoot(3.5, "쓰다듬기 — 귀 젖힘 → 걷어내기",
          each=lambda i: window.events.emit(brain.hover(clock.t, x0 + (12 if (i // 3) % 2 else -12), True)))
    shoot(2.4, "손 떼면 손 털고 씩 → 서기")
    brain._next_walk = clock.t + 99
    x0, y0 = brain.pos[0], brain.pos[1] - 100
    brain.press(clock.t, x0, y0)
    shoot(1.4, "끌기", each=lambda i: window.events.emit(brain.move(clock.t, x0 + i * 4, y0 - i * 6)))
    window.events.emit(brain.release(clock.t))
    shoot(3.8, "떨어지기 → 착지 → 서기(덮기 없음)")
    front["on"] = True
    shoot(12.0, "게임이 앞 — 구석에 앉아 마법진 돌리기")
    brain.press(clock.t, brain.pos[0], brain.pos[1] - 60); window.events.emit(brain.release(clock.t))
    shoot(3.0, "앉아서 클릭 — 앉은 그대로 말풍선")
    front["on"] = False
    shoot(2.5, "게임이 뒤로 — 일어남")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "starline_pet_actions.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    print(path, len(frames))
    app.processEvents()


if __name__ == "__main__":
    main()
