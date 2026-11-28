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
from collections import OrderedDict
from collections.abc import Mapping

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


LAZY_OVER = 150      # 이보다 장이 많은 캐릭터(Starline 영상판 350장, 11-27)는 늘 쓰는 장만 미리 읽고 나머지는 그때그때
LAZY_KEEP = 40       # 화면 크기로 줄인 장을 늘 쓰는 동작 말고 이만큼만 들고 있음(한 동작 30장 + 여유)
LAZY_ORIGINALS = 6   # 원본(저장 크기) 장은 줄이는 동안만 — 원본 크기 그림(Starline 서기 키 약 520, 11-27)은 장당 약 0.7MB
PINNED = ("stand", "walk", "talk", "talk_end")   # 화면용 장을 늘 들고 있는 동작


class LazyFrames(Mapping):
    """{이름: QImage} — 이름·경로는 다 알고, 그림은 처음 쓸 때 읽음(원본은 최근 몇 장만). 펫 창은 화면 크기로 줄인 장을
    캐시하고(늘 쓰는 동작 pinned는 안 버림) 크기·기준점은 meta로 — 원본을 오래 들고 있지 않음. 한 장 읽기 ≈ 2ms.
    frame_h = 저장 그림의 서 있는 키(frames.json standH, 없으면 FRAME_DIR_H) — 앱은 이 키에서 한 번만 줄여 그림."""

    def __init__(self, paths_by_name: dict, anchors: dict, pinned: set, keep: int = LAZY_ORIGINALS,
                 frame_h: float = 0.0, draw_scale: dict | None = None) -> None:
        self._paths = dict(paths_by_name)
        self._anchors = anchors
        self.pinned = set(pinned) & set(self._paths)
        self.frame_h = frame_h or FRAME_DIR_H
        self.draw_scale = dict(draw_scale or {})   # 동작(이름 앞부분) → 그리기 배율(frames.json drawScale)
        self._keep = keep
        self._recent: OrderedDict[str, QImage] = OrderedDict()
        self._meta: dict[str, tuple[int, int, str]] = {}

    def _read(self, name: str) -> QImage | None:
        path = self._paths[name]
        if path.suffix == ".webp":   # OpenCV로(빌드에 Qt webp 플러그인이 없어도 읽힘) — BGRA = QImage ARGB32(리틀 엔디언)
            import cv2

            from .. import image_io
            data = image_io.imread(path, cv2.IMREAD_UNCHANGED)
            if data is None or data.ndim != 3 or data.shape[2] != 4:
                return None
            h, w = data.shape[:2]
            image = QImage(data.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
        else:
            image = QImage(str(path))
        if image.isNull():
            return None
        if name in self._anchors:
            image.setText("anchor", "{},{}".format(*self._anchors[name]))
        self._meta[name] = (image.width(), image.height(), image.text("anchor"))
        return image

    def meta(self, name: str) -> tuple[int, int, str] | None:
        """(폭, 키, 기준점 글) — 한 번 읽으면 원본을 버려도 남음."""
        if name not in self._meta and self.get(name) is None:
            return None
        return self._meta[name]

    def __getitem__(self, name: str) -> QImage:
        if name in self._recent:
            self._recent.move_to_end(name)
            return self._recent[name]
        if name not in self._paths:
            raise KeyError(name)
        image = self._read(name)
        if image is None:
            raise KeyError(name)
        self._recent[name] = image
        while len(self._recent) > self._keep:
            self._recent.popitem(last=False)
        return image

    def __contains__(self, name) -> bool:
        return name in self._paths

    def __iter__(self):
        return iter(self._paths)

    def __len__(self) -> int:
        return len(self._paths)

    def loaded(self) -> set[str]:
        return set(self._recent)


def frame_file(folder, name: str):
    """그 장 파일 — PNG, 없으면 WebP(Starline 영상판, 11-27). 둘 다 없으면 None."""
    for ext in (".png", ".webp"):
        path = folder / f"{name}{ext}"
        if path.is_file():
            return path
    return None


def dressed(folder: str, outfit: str) -> bool:
    """착장 폴더 그림을 입는지(그 옷 폴더가 있음) — 영상판 캐릭터(다래)는 그때 예전 시트 프로필·모션(brain.profile_for)."""
    return bool(outfit) and (paths.resource_dir() / "characters" / folder / "outfits" / outfit).is_dir()


def load_frames(folder: str, profile: brain_mod.Profile | None = None, outfit: str = "") -> Mapping[str, QImage]:
    """그 캐릭터 동작에 쓰는 프레임만 읽는다(assets/characters/<폴더>/<이름>.png).
    outfit(착장 key)이면 outfits/<key>/<이름>.png를 먼저 — 없는 프레임은 기본 옷 그대로(착장 SD는 아직 없음, 기획 11-25).
    영상판 캐릭터(다래, 기획 11-28)가 착장을 입으면 그 옷 폴더 그림만(예전 시트 한 벌 — 기본 옷 영상 장과 섞지 않음)."""
    base = paths.resource_dir() / "characters" / folder
    wearing = dressed(folder, outfit)
    dressed_dir = base / "outfits" / outfit if wearing else None   # SD 없는 옷 = 기본 그대로
    if wearing and folder in brain_mod.SHEET_PROFILES:
        base, dressed_dir = dressed_dir, None   # 크기(frames.json)·놓는 자리(anchors.json)도 옷 폴더 것(없음 = 예전 기준)
    profile = profile or brain_mod.profile_for(folder, wearing)
    out = {}
    names = {name for frames, _times, _loop in profile.anims.values() for name in frames}
    from ..character import motions
    motion_names = motions.frame_names(folder, wearing)   # 호감도 모션 — 입은 옷 폴더에 있는 것만(기본 옷 모션으로 대신하지 않음)
    anchors = _anchors(base)
    if len(names | motion_names) > LAZY_OVER:
        found = {}
        for name in sorted(names | motion_names):
            path = frame_file(dressed_dir, name) if dressed_dir is not None else None
            path = path or frame_file(base, name)
            if path is None or (name in motion_names and dressed_dir is not None and path.parent != dressed_dir):
                continue
            found[name] = path
        pinned = {n for state in PINNED if state in profile.anims for n in profile.anims[state][0]}
        return LazyFrames(found, anchors, pinned, frame_h=_frame_h(base), draw_scale=_draw_scale(base))
    for name in sorted(names | motion_names):
        path = dressed_dir / f"{name}.png" if dressed_dir is not None and (dressed_dir / f"{name}.png").is_file() else base / f"{name}.png"
        if name in motion_names and dressed_dir is not None and path.parent != dressed_dir:
            continue
        image = QImage(str(path))
        if not image.isNull():
            if name in anchors:  # 프레임별 그리기 오프셋(저장 px) — 예: 이안 떨어지기 두 장의 머리 위치 맞춤
                image.setText("anchor", "{},{}".format(*anchors[name]))
            out[name] = image
    return out


def _frame_h(base) -> float:
    """assets/characters/<폴더>/frames.json {"standH": 저장 그림 서 있는 키} — 없거나 잘못되면 0(= FRAME_DIR_H)."""
    import json

    try:
        value = json.loads((base / "frames.json").read_text(encoding="utf-8")).get("standH")
    except (OSError, ValueError, AttributeError):
        return 0.0
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 100 <= value <= 2000 else 0.0


def _draw_scale(base) -> dict[str, float]:
    """frames.json {"drawScale": {동작: 배율}} — 원본 영상 자체가 서기보다 크게 찍힌 동작을 그릴 때만 맞춤(그림 파일은 그대로,
    Starline 착지 0.95 — 사용자 11-28 '내려놓은 뒤 서기로 바뀔 때 작아짐'). 잘못된 값은 버림."""
    import json

    try:
        raw = json.loads((base / "frames.json").read_text(encoding="utf-8")).get("drawScale", {})
    except (OSError, ValueError, AttributeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: float(v) for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool) and 0.5 <= v <= 1.5}


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

    def __init__(self, brain: brain_mod.Brain, frames: Mapping[str, QImage], tint: str,
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
        self._scaled: OrderedDict[str, QImage] = OrderedDict()   # 화면 크기로 줄인 장(그때그때 읽는 캐릭터는 최근 것만)
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
        self.brain.bubble_until(now + len(text) * brain_mod.TYPE_SECONDS)
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
        shown = (name, self.brain.facing_left, self.bubble_shown(now), self.brain.shake(now),
                 round(self.brain.float_offset(now)))
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
            k = self._k() * dpr * self._scale_of(name)
            cached = image.scaled(round(image.width() * k), round(image.height() * k),
                                  Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            cached.setDevicePixelRatio(dpr)
            self._scaled[name] = cached
            pinned = getattr(self.frames, "pinned", None)
            if pinned is not None:   # LazyFrames — 늘 쓰는 장 말고는 최근 LAZY_KEEP장만
                extra = [n for n in self._scaled if n not in pinned]
                for old in extra[:max(0, len(extra) - LAZY_KEEP)]:
                    del self._scaled[old]
        else:
            self._scaled.move_to_end(name)
        return cached

    # ---- 그리기 ------------------------------------------------------------------------------
    def _k(self) -> float:
        """저장 프레임 → 화면 배율(키 190 기준 × 캐릭터 배율)."""
        return brain_mod.FIGURE_H / getattr(self.frames, "frame_h", FRAME_DIR_H) * min(MAX_SCALE, self.brain.profile.scale)

    def _rect(self, name: str) -> QRectF:
        """그 장을 그릴 자리 — 그때그때 읽는 캐릭터는 원본 없이 크기·기준점(meta)으로."""
        meta = getattr(self.frames, "meta", None)
        if meta is None:
            return self._frame_rect(self.frames[name])
        w, h, anchor = meta(name)
        return self._frame_rect(None, (w, h, anchor), self._scale_of(name))

    def _scale_of(self, name: str) -> float:
        table = getattr(self.frames, "draw_scale", None)
        return table.get(name.rsplit("_", 1)[0], 1.0) if table else 1.0

    def _frame_rect(self, image: QImage | None, meta: tuple | None = None, scale: float = 1.0) -> QRectF:
        k = self._k() * scale   # 그리기 배율 — 크기·기준점(발 자리)을 같이 늘리고 줄여 발은 그대로
        w, h, anchor = meta if meta is not None else (image.width(), image.height(), image.text("anchor"))
        w, h = w * k, h * k
        dx = dy = 0.0
        if anchor:
            dx, dy = (float(v) * k for v in anchor.split(","))
        return QRectF(WIN_W / 2 - w / 2 + dx, WIN_H - FOOT - h + dy, w, h)

    def layers(self, now: float) -> list[tuple[str, float]]:
        """그릴 그림과 불투명도 — 늘 한 장(덮기 전환 없음, 사용자 11-24 잔상)."""
        return [(self.brain.frame(now), 1.0)]

    def paintEvent(self, _event) -> None:  # noqa: N802
        now = self._clock()
        name = self.brain.frame(now)
        image = self._image(name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if image is not None:
            lift = self.brain.float_offset(now)   # 레나 앉아 떠 있기(마법) — 그림·클릭 판정 같이 위로
            self._sprite = self._rect(name).translated(0, lift)
            for layer, opacity in self.layers(now):
                small, rect = self._image(layer), self._rect(layer)
                if "_m2_" in layer:
                    rect.translate(0, -1)  # 입 크게일 때 1px 끄덕임
                rect.translate(self.brain.shake(now), lift)  # 쓰다듬기 참는 중 좌우 1px 떨림(레나)·앉아 떠 있기
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
        name = self.brain.frame(self._clock())
        image = self._image(name) if hasattr(self.frames, "meta") else self.frames.get(name)   # 그때그때 읽기: 화면용 장으로
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
