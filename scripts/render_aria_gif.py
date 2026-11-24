"""아리아 펫 동작 GIF(사용자 확인용) — 서기↔머리 쓰다듬기, 걷기(머리색 보정), 구석 앉기·클릭 말풍선, 말하기.

실행: QT_QPA_PLATFORM=offscreen uv run --with pillow python -m scripts.render_aria_gif
(Pillow는 이 렌더에만 쓰고 앱 의존성에는 넣지 않는다. 그리기는 render_pet_gif.compose와 같음.)
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon import paths  # noqa: E402
from mabinogi_addon.character import roster  # noqa: E402
from mabinogi_addon.character.brain import ARIA, Brain, Floor  # noqa: E402
from mabinogi_addon.character.lines import Line, Picker, read  # noqa: E402
from mabinogi_addon.ui.pet_window import PetWindow, load_frames  # noqa: E402
from scripts.render_pet_gif import FPS, H, OUT, TASKBAR, W, Clock, compose  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication([])
    clock = Clock()
    front = {"on": False}
    floor = Floor(0, W, H - TASKBAR)
    aria = roster.by_pack("부드러운 여성")
    brain = Brain(floor, rng=random.Random(7), profile=ARIA, corner=(W - 170.0, floor.y))
    brain.pos = (260.0, floor.y)
    window = PetWindow(brain, load_frames("아리아", ARIA), aria.color, game_front=lambda: front["on"], clock=clock)
    picker = Picker(read(paths.resource_dir() / "characters" / "아리아" / "lines.json"), random.Random(3))
    window.events.connect(lambda events: [window.say(picker.pick(e[1])) for e in events if e[0] == "say"])
    frames = []

    def shoot(seconds: float, caption: str, each=None) -> None:
        for i in range(int(seconds * FPS)):
            clock.t += 1 / FPS
            if each:
                each(i)
            window.step()
            frames.append(compose(window, caption, front["on"]))

    # 1) 서 있기(두 자세) ↔ 가만히 있으면 머리 쓰다듬기
    brain._next_walk = clock.t + 99
    brain._next_idle = clock.t + 999
    shoot(2.5, "서 있기 — 두 자세 번갈아")
    brain._next_extra = clock.t
    shoot(4.5, "가만히 서 있으면 가끔 머리 쓰다듬기(1~2바퀴)")
    # 2) 머리 쓰다듬는 중 클릭 → 그 상황 대사
    brain._go("hairstroke", clock.t); brain._extra_until = clock.t + 5
    shoot(0.6, "머리 쓰다듬는 중")
    brain.press(clock.t, *brain.pos); window.events.emit(brain.release(clock.t))
    shoot(3.0, "머리 쓰다듬는 중 클릭")
    # 3) 걷기(정수리 머리색을 서 있기에 맞춤)
    brain._go("stand", clock.t); brain._next_extra = clock.t + 99
    brain._walk_to((620.0, floor.y), clock.t)
    shoot(4.0, "걷기 — 머리색 보정")
    # 4) 말하기 — 분위기별
    for text, mood, label in (("나 찾았어? 여기 있지~", "normal", "말하기 — 보통(입)"),
                              ("다녀와~ 버프는 내가 챙길게.", "explain", "말하기 — 설명(손짓·꽃머리 포즈)"),
                              ("햇살 좋은 날엔 기분도 좋아져~", "happy", "말하기 — 기쁨"),
                              ("주머니에 캐모마일 남았나…?", "think", "말하기 — 생각(그림 없음 → 보통)")):
        window.say(Line(text, mood))
        shoot(3.2, label)
    # 5) 게임이 앞 → 구석으로 가서 머리 안고 앉음, 앉아서 클릭 = 웃음 + 말풍선
    front["on"] = True
    shoot(5.5, "게임이 앞 — 구석에서 머리를 안고 앉음(졸지 않음)")
    brain.press(clock.t, brain.pos[0], brain.pos[1] - 60); window.events.emit(brain.release(clock.t))
    shoot(3.0, "앉아서 클릭 — 웃음 + 말풍선")
    shoot(3.0, "구석에서 앉아 있기")
    front["on"] = False
    shoot(3.0, "게임이 뒤로 — 일어남")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "aria_pet_actions.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    print(path, len(frames))
    app.processEvents()


if __name__ == "__main__":
    main()
