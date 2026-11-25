"""새 말하기(사용자 11-24 다시 만들기) GIF — 세 캐릭터를 앱 그리기 경로(PetWindow)로 나란히. 시안과 비교용.

실행: QT_QPA_PLATFORM=offscreen uv run --with pillow python -m scripts.render_talk_gif
"""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PIL import Image  # noqa: E402
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mabinogi_addon.character import roster  # noqa: E402
from mabinogi_addon.character.brain import PROFILES, Brain, Floor  # noqa: E402
from mabinogi_addon.character.lines import Line  # noqa: E402
from mabinogi_addon.ui.pet_window import WIN_W, PetWindow, load_frames  # noqa: E402
from scripts.render_pet_gif import OUT, Clock  # noqa: E402

FPS = 20
W, H = 3 * WIN_W, 330
SCRIPT = [  # (시각, 대사, 분위기) — 다래·아리아·이안 같은 시각에 말함
    (0.6, ("…구름 같은 거 보고 싶다.", "오늘은 어떤 약초를 말려 볼까…", "…서류가 또 쌓였군."), "normal"),
    (4.2, ("버프 끝나면… 내가 말해 줄게.", "다녀와~ 버프는 내가 챙길게.", "다녀오세요. 버프는 제가 보겠습니다."), "explain"),
    (8.2, ("응… 안녕.", "응? 무슨 일 있어?", "…네."), "normal"),
]
LENGTH = 11.0


def main() -> None:
    app = QApplication.instance() or QApplication([])
    clock = Clock()
    windows = []
    for i, pack in enumerate(("조용한 여성", "부드러운 여성", "부드러운 남성")):
        character = roster.by_pack(pack)
        folder = roster.folder(character)
        brain = Brain(Floor(0, 10000, H - 10), rng=random.Random(5 + i), profile=PROFILES[folder])
        brain.pos = (5000.0, H - 10)
        brain._next_walk = brain._next_extra = brain._next_idle = clock.t + 999
        windows.append(PetWindow(brain, load_frames(folder, PROFILES[folder]), character.color, clock=clock))
    frames, start, done = [], clock.t, set()
    while clock.t - start < LENGTH:
        clock.t += 1 / FPS
        for k, (at, texts, mood) in enumerate(SCRIPT):
            if k not in done and clock.t - start >= at:
                done.add(k)
                for w, text in zip(windows, texts):
                    w.say(Line(text, mood))
        for w in windows:
            w.step()
        frames.append(compose(windows))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "talk_new_three.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    print(path, len(frames))
    app.processEvents()


def compose(windows) -> Image.Image:
    image = QImage(W, H, QImage.Format.Format_ARGB32)
    image.fill(QColor("#22324a"))
    p = QPainter(image)
    font = QFont()
    font.setPixelSize(13)
    p.setFont(font)
    for i, w in enumerate(windows):
        sprite = QImage(w.size(), QImage.Format.Format_ARGB32_Premultiplied)
        sprite.fill(Qt.GlobalColor.transparent)
        w.render(sprite)
        p.drawImage(i * WIN_W, H - w.height(), sprite)
        p.setPen(QColor("#cfd6e0"))
        p.drawText(QRectF(i * WIN_W + 8, 6, WIN_W - 16, 18), int(Qt.AlignmentFlag.AlignLeft),
                   f"{w.brain.state} · {w.brain.frame(w._clock())}")
    p.end()
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes("RGBA", (W, H), bytes(rgba.constBits())).convert("RGB").convert(
        "P", palette=Image.Palette.ADAPTIVE)


if __name__ == "__main__":
    main()
