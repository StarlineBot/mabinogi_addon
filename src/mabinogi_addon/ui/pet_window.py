"""화면을 돌아다니는 SD 펫 창(docs/character-pet-spec.md 2절) — 그리기·마우스만, 동작 판단은 character/brain.py.

코드 → 런타임 동작 → 시스템 영향
- 투명·테두리 없는·맨 위·작업 표시줄에 안 뜨는(Tool) 창 하나. 포커스를 가져가지 않는다(게임 입력을 뺏지 않게).
- 화면 판독 캡처에서 항상 뺀다(overlay_capture.OVERLAYS 'PetWindow') — 빠지면 버프·디버프 판독 화면에 펫이 찍혀 판독이 틀어진다.
- 0.05초마다 brain.tick → 창 위치를 발 밑 가운데에 맞추고 다시 그림. 투명한 칸은 Windows가 클릭을 통과시켜
  캐릭터 그림 위 클릭만 받는다(per-pixel 알파 창).
- 키보드는 읽지 않는다(명세 5절). 창·커서를 건드리지 않는다.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QWidget

from .. import paths
from ..character import brain as brain_mod

FRAME_DIR_H = 285            # 저장 프레임의 서 있는 키(scripts/build_dare_frames.py STAND_H)
WIN_W = 300                  # 창 폭(가장 넓은 프레임 + 말풍선 여유)
BUBBLE_H = 74                # 머리 위 말풍선 자리
MAX_SCALE = 1.2              # 캐릭터 그리기 배율 상한(Profile.scale — Starline 1.15) — 창 높이를 이만큼 키워 둠
WIN_H = round(brain_mod.FIGURE_H * MAX_SCALE) + BUBBLE_H + 40
FOOT = 6                     # 창 아래에서 발 밑까지
BUBBLE_SECONDS = 4.5
TICK_MS = 50
FRONT_CHECK = 0.25           # 게임 앞/뒤 판정 주기(초)
BLOCK_CHECK = 1.0            # 보이는 게임 화면(진짜 창모드) 다시 구하는 주기(초) — 게임이 포그라운드가 아닐 때만


def load_frames(folder: str, profile: brain_mod.Profile | None = None, outfit: str = "") -> dict[str, QImage]:
    """그 캐릭터 동작에 쓰는 프레임만 읽는다(assets/characters/<폴더>/<이름>.png).
    outfit(착장 key)이면 outfits/<key>/<이름>.png를 먼저 — 없는 프레임은 기본 옷 그대로(착장 SD는 아직 없음, 기획 11-25)."""
    base = paths.resource_dir() / "characters" / folder
    dressed = base / "outfits" / outfit if outfit and (base / "outfits" / outfit).is_dir() else None   # SD 없는 옷 = 기본 그대로
    profile = profile or brain_mod.PROFILES.get(folder, brain_mod.DARE)
    out = {}
    names = {name for frames, _times, _loop in profile.anims.values() for name in frames}
    from ..character import motions
    motion_names = motions.frame_names(folder)   # 호감도 모션 — 입은 옷 폴더에 있는 것만(기본 옷 모션으로 대신하지 않음)
    anchors = _anchors(base)
    for name in sorted(names | motion_names):
        path = dressed / f"{name}.png" if dressed is not None and (dressed / f"{name}.png").is_file() else base / f"{name}.png"
        if name in motion_names and dressed is not None and path.parent != dressed:
            continue
        image = QImage(str(path))
        if not image.isNull():
            if name in anchors:  # 프레임별 그리기 오프셋(저장 px) — 예: 이안 떨어지기 두 장의 머리 위치 맞춤
                image.setText("anchor", "{},{}".format(*anchors[name]))
            out[name] = image
    return out


def _anchors(base) -> dict[str, tuple[float, float]]:
    """assets/characters/<폴더>/anchors.json {프레임: [dx, dy]} — 없거나 잘못되면 {}(발 밑 가운데 그대로)."""
    import json

    try:
        raw = json.loads((base / "anchors.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    if isinstance(raw, dict):
        for name, value in raw.items():
            if (isinstance(value, list) and len(value) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) < 200 for v in value)):
                out[name] = (float(value[0]), float(value[1]))
    return out


class PetWindow(QWidget):
    """펫 창. events 신호로 말풍선·호감도 처리할 사건을 넘긴다(컨트롤러가 받음)."""
    events = Signal(list)

    def __init__(self, brain: brain_mod.Brain, frames: dict[str, QImage], tint: str,
                 game_front=lambda: False, clock=time.monotonic, parent: QWidget | None = None,
                 outline: str | None = None, blocked=lambda: ()) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        from . import overlay_capture
        overlay_capture.watch(self)  # 판독 캡처에서 빼기(다른 오버레이와 같음)
        overlay_capture.keep_pet_front(self)  # 미러링·오버레이보다 앞(커서 창보다는 뒤, 사용자 11-24)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFixedSize(WIN_W, WIN_H)
        self.brain = brain
        self.frames = frames
        self.tint = QColor(tint)
        # 말풍선 바깥선(Starline 금 — 진한 메인색 테두리만으로는 어두운 화면에 묻힘). 흰색·없음이면 그리지 않음
        self.outline = QColor(outline) if outline and outline.lower() != "#ffffff" else None
        self._game_front = game_front
        self._clock = clock
        self._front = False
        self._front_checked = -1e9
        self._blocked_fn = blocked      # 보이는 게임 화면이 바닥과 겹치는 x 구간(진짜 창모드, QA 11-26)
        self._blocked: tuple = ()
        self._blocked_checked = -1e9
        self._bubble: tuple[str, float, float] | None = None   # (글, 나오기 시작, 사라질 때)
        self._sprite = QRectF()
        self._shown = None            # 마지막으로 그린 것(프레임·위치·말풍선) — 같으면 다시 안 그림(CPU)
        self._cur_name: str | None = None
        self._scaled: dict[str, QImage] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self.step)
        self._place()

    # ---- 바깥에서 ---------------------------------------------------------------------------
    def start(self) -> None:
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def say(self, line, mood: str = "normal") -> None:
        """말풍선 — 글자가 한 자씩 나오고(TYPE_SECONDS), 서 있으면 그동안 말하기 그림(분위기별).
        line은 글(str) 또는 character.lines.Line."""
        if not line:
            return
        text, mood = (line, mood) if isinstance(line, str) else (line.text, line.mood)
        now = self._clock()
        self._bubble = (text, now, now + len(text) * brain_mod.TYPE_SECONDS + BUBBLE_SECONDS)
        self.brain.talk(now, len(text), mood)
        self.update()

    def hold_talk(self, seconds: float) -> None:
        """말풍선이 뜬 때부터 seconds초 동안 말하기 그림 유지(대사 목소리 길이)."""
        if self._bubble:
            text, start, end = self._bubble
            self.brain.hold_talk(start + seconds)
            self._bubble = (text, start, max(end, start + seconds + 1.5))

    def bubble(self) -> str | None:
        return self._bubble[0] if self._bubble else None

    def bubble_shown(self, now: float | None = None) -> str:
        """지금 보이는 만큼의 글(한 글자씩 나옴)."""
        if not self._bubble:
            return ""
        text, start, _end = self._bubble
        now = self._clock() if now is None else now
        return text[:max(1, min(len(text), int((now - start) / brain_mod.TYPE_SECONDS) + 1))]

    # ---- 시간 --------------------------------------------------------------------------------
    def step(self) -> None:
        now = self._clock()
        if now - self._front_checked >= FRONT_CHECK:
            self._front_checked = now
            try:
                self._front = bool(self._game_front())
            except Exception:  # noqa: BLE001 — 판정 실패는 '게임 밖'으로
                self._front = False
        if self._front:
            self._blocked = ()   # 게임 중엔 구석으로 — 창 영역 계산 안 함(CPU)
        elif now - self._blocked_checked >= BLOCK_CHECK:
            self._blocked_checked = now
            try:
                self._blocked = tuple(self._blocked_fn() or ())
            except Exception:  # noqa: BLE001 — 판정 실패는 '막힌 곳 없음'(지금 동작 그대로)
                self._blocked = ()
        events = self.brain.tick(now, self._front, self._blocked)
        if self._bubble and now >= self._bubble[2]:
            self._bubble = None
        self._place()
        # 서 있기·앉아 있기처럼 그림이 그대로면 다시 그리지 않는다(Zzz가 떠오르는 동안만 매번).
        # 그림은 늘 바로 바뀜 — 덮기 전환(앞 그림 위에 새 그림 0.13초)은 없앰(사용자 11-24 '잔상' — QA 전수 조사: 포즈가 다른
        # 두 그림이 겹쳐 보임, ghost_survey)
        name = self.brain.frame(now)
        self._cur_name = name
        shown = (name, self.brain.facing_left, self.bubble_shown(now), self.brain.shake(now))
        if shown != self._shown or self.brain.zzz():
            self._shown = shown
            self.update()
        if events:
            self.events.emit(events)

    def _place(self) -> None:
        x, y = self.brain.pos
        target = (round(x - WIN_W / 2), round(y - (WIN_H - FOOT)))
        if (self.x(), self.y()) != target:
            self.move(*target)

    def _image(self, name: str) -> QImage | None:
        """그 프레임을 화면 크기(키 190, 화면 배율 반영)로 한 번만 줄여 둔다 — 그릴 때마다 줄이지 않게."""
        image = self.frames.get(name)
        if image is None:
            return None
        cached = self._scaled.get(name)
        if cached is None:
            dpr = max(1.0, self.devicePixelRatioF())
            k = self._k() * dpr
            cached = image.scaled(round(image.width() * k), round(image.height() * k),
                                  Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            cached.setDevicePixelRatio(dpr)
            self._scaled[name] = cached
        return cached

    # ---- 그리기 ------------------------------------------------------------------------------
    def _k(self) -> float:
        """저장 프레임 → 화면 배율(키 190 기준 × 캐릭터 배율)."""
        return brain_mod.FIGURE_H / FRAME_DIR_H * min(MAX_SCALE, self.brain.profile.scale)

    def _frame_rect(self, image: QImage) -> QRectF:
        k = self._k()
        w, h = image.width() * k, image.height() * k
        dx = dy = 0.0
        anchor = image.text("anchor")
        if anchor:
            dx, dy = (float(v) * k for v in anchor.split(","))
        return QRectF(WIN_W / 2 - w / 2 + dx, WIN_H - FOOT - h + dy, w, h)

    def layers(self, now: float) -> list[tuple[str, float]]:
        """그릴 그림과 불투명도 — 늘 한 장(덮기 전환 없음, 사용자 11-24 잔상)."""
        return [(self.brain.frame(now), 1.0)]

    def paintEvent(self, _event) -> None:  # noqa: N802
        now = self._clock()
        name = self.brain.frame(now)
        image = self.frames.get(name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if image is not None:
            self._sprite = self._frame_rect(image)
            for layer, opacity in self.layers(now):
                small, rect = self._image(layer), self._frame_rect(self.frames[layer])
                if "_m2_" in layer:
                    rect.translate(0, -1)  # 입 크게일 때 1px 끄덕임
                rect.translate(self.brain.shake(now), 0)  # 쓰다듬기 참는 중 좌우 1px 떨림(레나)
                p.setOpacity(opacity)
                if self.brain.state == "walk" and self.brain.facing_left:  # 걷기 시트는 오른쪽 — 왼쪽은 뒤집기
                    p.save()
                    p.setTransform(QTransform(-1, 0, 0, 1, WIN_W, 0))
                    p.drawImage(QRectF(WIN_W - rect.right(), rect.top(), rect.width(), rect.height()), small)
                    p.restore()
                else:
                    p.drawImage(rect, small)
            p.setOpacity(1.0)
            rect = self._sprite
            if self.brain.zzz():
                self._paint_zzz(p, rect, now)
        if self._bubble:
            self._paint_bubble(p, self._bubble[0], self.bubble_shown(now))
        p.end()

    def _paint_zzz(self, p: QPainter, rect: QRectF, now: float) -> None:
        """졸 때 Z 세 개 — 머리 옆(폭 85%·머리 높이)에서 차례로 떠오르며 커지고 흐려짐, 한 바퀴 약 2초(다래.md)."""
        x0, y0 = rect.left() + rect.width() * 0.85, rect.top() + rect.height() * 0.3
        for i in range(3):
            t = ((now / 2.0) + i / 3) % 1.0
            size = 16 + 16 * t
            font = QFont(self.font())
            font.setPixelSize(round(size))
            font.setWeight(QFont.Weight.Black)
            path = QPainterPath()
            path.addText(QPointF(0, 0), font, "Z")
            path.translate(x0 + math.sin(t * math.tau) * 4 + t * 10, y0 - t * 46)
            p.setOpacity(max(0.0, 1.0 - t))
            p.setPen(QPen(QColor("#ffffff"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.tint)
            p.drawPath(path)
        p.setOpacity(1.0)

    def _paint_bubble(self, p: QPainter, text: str, shown: str) -> None:
        """흰 바탕·캐릭터 색 테두리·꼬리, 머리 위. 크기는 다 나온 글 기준(한 글자씩 나와도 말풍선이 흔들리지 않게)."""
        font = QFont(self.font())
        font.setPixelSize(13)
        metrics = QFontMetricsF(font)
        box = metrics.boundingRect(QRectF(0, 0, WIN_W - 40, 200),
                                   int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft), text)
        w, h = box.width() + 22, box.height() + 14
        head = self._sprite.top() if not self._sprite.isNull() else BUBBLE_H
        rect = QRectF(WIN_W / 2 - w / 2, max(2.0, head - h - 6), w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        tail = QPainterPath()
        cx = rect.center().x()
        tail.moveTo(cx - 7, rect.bottom() - 1)
        tail.lineTo(cx, rect.bottom() + 7)
        tail.lineTo(cx + 7, rect.bottom() - 1)
        path = path.united(tail)
        if self.outline is not None:
            p.setPen(QPen(self.outline, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.setPen(QPen(self.tint, 2))
        p.setBrush(QColor(255, 255, 255, 245))
        p.drawPath(path)
        p.setFont(font)
        p.setPen(QColor("#2b2d33"))
        # 왼쪽 위 기준으로 — 한 글자씩 나와도 이미 나온 글자가 움직이지 않게
        inner = rect.adjusted(11, 7, -11, -7)
        p.drawText(inner, int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), shown)

    # ---- 마우스(캐릭터 위만) ------------------------------------------------------------------
    def _on_figure(self, pos) -> bool:
        if not self._sprite.contains(pos):
            return False
        image = self.frames.get(self.brain.frame(self._clock()))
        if image is None:
            return False
        k = image.width() / self._sprite.width()
        x = (pos.x() - self._sprite.left()) * k
        if self.brain.state == "walk" and self.brain.facing_left:
            x = image.width() - 1 - x
        y = (pos.y() - self._sprite.top()) * k
        if not (0 <= x < image.width() and 0 <= y < image.height()):
            return False
        return image.pixelColor(int(x), int(y)).alpha() > 40

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self._on_figure(event.position()):
            event.ignore()
            return
        g = event.globalPosition()
        self.brain.press(self._clock(), g.x(), g.y())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        now = self._clock()
        g = event.globalPosition()
        if event.buttons() & Qt.MouseButton.LeftButton:
            events = self.brain.move(now, g.x(), g.y())
            self._place()
            self.update()
        else:
            pos = event.position()
            on_head = (self._on_figure(pos) or self._sprite.contains(pos)) and \
                pos.y() < self._sprite.top() + self._sprite.height() * 0.4
            events = self.brain.hover(now, g.x(), on_head)
        if events:
            self.events.emit(events)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        events = self.brain.release(self._clock())
        self._place()
        self.update()
        if events:
            self.events.emit(events)
