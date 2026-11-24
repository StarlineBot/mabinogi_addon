"""펫 동작 GIF(사용자 확인용) — 실제 PetWindow·Brain을 가짜 시계로 돌려 장면별로 찍는다.

실행: QT_QPA_PLATFORM=offscreen uv run --with pillow python -m scripts.render_pet_gif
(Pillow는 이 렌더에만 쓰고 앱 의존성에는 넣지 않는다.)
"""
from __future__ import annotations

import os
import random
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon import paths  # noqa: E402
from mabinogi_addon.character.brain import Brain, Floor  # noqa: E402
from mabinogi_addon.character.lines import Picker, read  # noqa: E402
from mabinogi_addon.ui.pet_window import PetWindow, load_frames  # noqa: E402

OUT = Path("docs/assets/character-alpha-20261124")
W, H = 760, 340
TASKBAR = 40
FPS = 10


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def main() -> None:
    app = QApplication.instance() or QApplication([])
    clock = Clock()
    front = {"on": False}
    floor = Floor(0, W, H - TASKBAR)
    brain = Brain(floor, rng=random.Random(4))
    brain.pos = (260.0, floor.y)
    window = PetWindow(brain, load_frames("다래"), "#B9A3E3", game_front=lambda: front["on"], clock=clock)
    picker = Picker(read(paths.resource_dir() / "characters" / "다래" / "lines.json"), random.Random(2))
    window.events.connect(lambda events: [window.say(picker.pick(e[1])) for e in events if e[0] == "say"])
    frames: list[Image.Image] = []
    captions: list[str] = []

    def shoot(seconds: float, caption: str, each=None) -> None:
        n = int(seconds * FPS)
        for i in range(n):
            clock.t += 1 / FPS
            if each:
                each(i)
            window.step()
            frames.append(compose(window, caption, front["on"]))

    def hover(x: float, y: float) -> None:
        local = QPointF(x - window.x(), y - window.y())
        events = brain.hover(clock.t, x, local.y() < window._sprite.top() + window._sprite.height() * 0.4)
        if events:
            window.events.emit(events)

    # 1) 바탕화면: 서 있다 걷기
    brain._next_walk = clock.t + 1.0
    shoot(5.0, "게임 밖 — 화면 아래를 돌아다님")
    # 2) 클릭 → 놀람
    brain.press(clock.t, *brain.pos); window.events.emit(brain.release(clock.t))
    shoot(2.5, "서 있을 때 클릭 — 놀람")
    # 3) 쓰다듬기: 머리 위 좌우로 문지름
    brain._target = None; brain._go("stand", clock.t); brain._next_walk = clock.t + 99
    head_y = brain.pos[1] - 165
    xs = [brain.pos[0] + (12 if (i // 3) % 2 else -12) for i in range(60)]
    shoot(4.5, "머리 위를 문지름 — 쓰다듬기", each=lambda i: hover(xs[i % len(xs)], head_y) if i < 36 else None)
    shoot(2.0, "손 떼면 삐침")
    # 4) 게임이 앞으로 → 구석으로 가서 앉아 졸기(Zzz)
    front["on"] = True
    shoot(4.5, "게임이 앞 — 구석으로 가서 쪼그려 앉음")
    shoot(3.0, "구석에서 졸림")
    brain._go("sit_doze", clock.t)  # 졸림 5초 → 꾸벅 졸기 차례를 앞당겨 찍음
    shoot(3.0, "꾸벅 졸기(Zzz)")
    brain.press(clock.t, brain.pos[0], brain.pos[1] - 60); window.events.emit(brain.release(clock.t))
    shoot(3.0, "졸 때 클릭 — 깜짝 깨기")
    shoot(3.0, "다시 구석에 앉음")
    # 5) 게임이 뒤로 → 일어나 다시 돌아다님
    front["on"] = False
    shoot(3.5, "게임이 뒤로 — 일어남")
    # 6) 끌어서 놓기 → 떨어져 착지
    brain._next_walk = clock.t + 99
    x0, y0 = brain.pos[0], brain.pos[1] - 100
    brain.press(clock.t, x0, y0)
    shoot(2.0, "끌기 — 끌려 다니기", each=lambda i: window.events.emit(brain.move(clock.t, x0 - i * 6, y0 - i * 5)))
    window.events.emit(brain.release(clock.t))
    shoot(4.0, "놓으면 떨어져 착지 → 일어남")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "pet_actions.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    frames[len(frames) // 2].save(OUT / "pet_still.png")
    print(path, len(frames))
    app.processEvents()


def compose(window: PetWindow, caption: str, game: bool) -> Image.Image:
    image = QImage(W, H, QImage.Format.Format_ARGB32)
    p = QPainter(image)
    grad = QLinearGradient(0, 0, 0, H)
    if game:
        grad.setColorAt(0, QColor("#3b2a1e")); grad.setColorAt(1, QColor("#1d1612"))
    else:
        grad.setColorAt(0, QColor("#2c4a6e")); grad.setColorAt(1, QColor("#14233a"))
    p.fillRect(0, 0, W, H, grad)
    p.fillRect(0, H - TASKBAR, W, TASKBAR, QColor("#20232a"))
    p.setPen(QColor("#e8e8e8"))
    font = QFont(); font.setPixelSize(15); font.setBold(True); p.setFont(font)
    p.drawText(QRectF(14, 10, W - 28, 24), int(Qt.AlignmentFlag.AlignLeft), caption)
    p.setPen(QColor("#9aa0aa"))
    p.drawText(QRectF(14, 32, W - 28, 20), int(Qt.AlignmentFlag.AlignLeft),
               "게임 창이 앞" if game else "게임 창이 뒤(바탕화면)")
    sprite = QImage(window.size(), QImage.Format.Format_ARGB32_Premultiplied)
    sprite.fill(Qt.GlobalColor.transparent)
    window.render(sprite)
    p.drawImage(window.x(), window.y(), sprite)
    p.end()
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = bytes(rgba.constBits())
    return Image.frombytes("RGBA", (W, H), data).convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE)


if __name__ == "__main__":
    main()
