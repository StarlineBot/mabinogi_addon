"""캐릭터 탭(docs/character-pet-spec.md 1절·3절 1번) — 설정의 '알림 목소리 고르기'를 옮겨 온 캐릭터 고르기.

- 맨 위 `화면에 캐릭터 띄우기` 스위치(펫 창 켜기·끄기).
- 상반신 카드 한 줄 3개(탭 스크롤로 위아래). 이름은 캐릭터 색 + 흰 테두리, 미정 캐릭터는 실루엣을 테마 회색으로 칠하고 `???`.
- 카드를 누르면 그 목소리가 나오고 바로 선택(알림 목소리 팩 저장), 고른 카드는 둘레 강조.
- 카드 아래 ♥ 호감도 바(0~100) + 바 아래 한 줄 지금 구간 퀘스트와 진행(사용자 최종 규칙 11-24).
- 알파는 제작자 전용(11-24): 카드 아래 호감도 숫자 칸(0~100) + 구간 버튼(0/25/50/75/100)으로 바로 바꿈
  (하루 상한과 무관, 구간별 대사·반응 확인용).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QPushButton, QSizePolicy, QSpinBox, QToolTip, QVBoxLayout,
                               QWidget)

from .. import config, paths
from ..character import outfits, roster
from ..character.affinity import MAX_VALUE, STAGES, Affinity, Rules
from .palette import color
from .widgets import VOICE_CREDIT, FeatureHeader, credit_label, hint_label, switch

DESCRIPTION = "고른 캐릭터가 알림을 말해 주고, 화면에서 함께 지내요."
CARD_W, CARD_H = 224, 280   # 카드(기획 11-25 — 4:5, 머리 위 20px)
PAD_TOP = 8      # 카드 위젯 위 여백 — 적용 대기 때 떠오르는 자리
PAD_BOTTOM = 16  # 아래 여백 — 명판이 반쯤 걸치고 그림자가 드리울 자리
FLOAT = 6        # 적용 대기 떠오름
HEAD_ROOM = 20   # 머리 위 여백(그림을 아래로)
ART_RADIUS = 13  # 그림 둥근 모서리(테두리 안쪽)
DIM_ALPHA = 64   # 쓰지 않는 카드 25% 어둡게
PLATE_W, PLATE_H = 76, 22
DRAWER_DELAY_MS = 300   # 카드에 0.3초 머물면 서랍(지나가는 마우스에 번쩍이지 않게)
DRAWER_GAP = 16         # 카드와 서랍 사이(테두리 장식이 넘치는 만큼)
# 이름을 테두리 띠 위로 올리는 양(기획 11-25)
# 카드 그림이 이미 카드 비율(224:260)이라 머리 위 20px 아래 높이에 꽉 맞추고 양옆을 자르지 않는 캐릭터(Starline 손 — 기획 11-25)
CARD_FIT_HEIGHT = {"Starline"}
NAME_LIFT = {"Starline": 12, "이안": 6, "다래": 4, "아리아": 2, "레나": 0}
BAR_H = 22
QUEST_H = 30   # 퀘스트 글 두 줄까지(이름이 들어가면 길어짐)
HEART = "#FF6B9A"
COLUMNS = 3
APPLY_BOTTOM = 50   # 적용 버튼 아래(이름 자리) — 버튼은 이름 바로 위


def card_pixmap(character: roster.Character, outfit: str = outfits.BASE) -> QPixmap:
    """카드 그림 — 착장을 입었으면 outfits/<key>/card.png(없으면 기본 카드)."""
    if outfit != outfits.BASE:
        dressed = paths.resource_dir() / "characters" / outfits.asset(roster.folder(character), outfit, "card.png")
        if dressed.is_file():
            return QPixmap(str(dressed))
    return QPixmap(str(paths.resource_dir() / "characters" / character.card))


def card_frame(character: roster.Character) -> tuple[QPixmap, QRectF] | None:
    """캐릭터 카드 테두리(기획 11-25) — (그림, 카드 왼쪽 위 기준 그릴 자리). 없으면 None(??? 등)."""
    import json

    if not character.known:
        return None
    base = paths.resource_dir() / "characters" / roster.folder(character)
    try:
        meta = json.loads((base / "frame.json").read_text(encoding="utf-8"))
        rect = QRectF(float(meta["x"]), float(meta["y"]), float(meta["w"]), float(meta["h"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    pixmap = QPixmap(str(base / "frame.png"))
    return None if pixmap.isNull() else (pixmap, rect)


def _dimmed(pixmap: QPixmap) -> QPixmap:
    """그림 픽셀에만 검정 25%(뒤 사각형 없이, 회색 변환 아님)."""
    out = QPixmap(pixmap)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    p.fillRect(out.rect(), QColor(0, 0, 0, DIM_ALPHA))
    p.end()
    return out


def draw_card_art(p: QPainter, rect: QRectF, art: QPixmap, fit_height: bool = False) -> None:
    """카드 그림 놓기(카드·서랍 칸 공용 — 4:5 칸): 머리 위 HEAD_ROOM(칸 폭 비례)을 띄우고, 양옆을 잘라 칸 높이를 채움
    (가운데 기준) — 아래는 그만큼 잘림. fit_height(이미 카드 비율인 그림 — Starline)면 머리 위 아래 높이에 꽉, 양옆 안 자름."""
    head = HEAD_ROOM * rect.width() / (CARD_W - 3)
    if fit_height:
        p.drawPixmap(QRectF(rect.left(), rect.top() + head, rect.width(), rect.height() - head + 3 * rect.width() / CARD_W),
                     art, QRectF(art.rect()))
        return
    src_w = min(art.width(), art.height() * rect.width() / rect.height())
    source = QRectF((art.width() - src_w) / 2, 0, src_w, art.height())
    p.drawPixmap(QRectF(rect.left(), rect.top() + head, rect.width(), rect.height()), art, source)


class CharacterCard(QWidget):
    """카드 하나 — 그림(카드 224×280, 머리 위 20px, 둥근 모서리로 자름) + 아래 ♥ 호감도 바(제작자). 누르면 clicked(인사 듣기).
    테두리·이름·`✓ 사용 중` 명판은 탭 위 CardFrameLayer가 그림(장식이 칸 밖으로 넘쳐도 잘리지 않게, 기획 11-25).
    - 쓰는 중(selected): 늘 밝게 + 아래 가운데 명판.
    - 쓰지 않음: 25% 어둡게 — 마우스를 올리거나(서랍이 열려 있거나) 적용 대기면 원래 밝기.
    - 대기(pending): 6px 떠오름 + 아래 그림자 + 이름 바로 위 `이 캐릭터로 적용`(누르면 applied)."""
    clicked = Signal(object)
    applied = Signal(object)
    hovered = Signal(object)   # 마우스가 카드에 들어옴(착장 서랍 — 0.3초 머물면 열림)
    left = Signal(object)      # 마우스가 카드를 나감(서랍 닫을지 확인)
    changed = Signal()         # 테두리 층을 다시 그려야 함(밝기·대기·옷)

    def __init__(self, character: roster.Character, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.character = character
        self.outfit = outfits.BASE
        self._art = card_pixmap(character)
        self.frame = card_frame(character)
        self._frame_dim = _dimmed(self.frame[0]) if self.frame else None
        self._selected = False
        self._affinity = 0
        self._quest = ""
        self._details = True   # ♥ 호감도 바·퀘스트 줄(베타 11-24: 제작자만)
        self._pending = False  # 인사를 들은 뒤 '이 캐릭터로 적용' 대기
        self._hover = False
        self.keep_bright = False   # 그 카드 서랍이 열려 있는 동안(마우스가 서랍에 있어도 밝게)
        self.apply_button = QPushButton("이 캐릭터로 적용", self)
        self.apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_button.setStyleSheet(
            f"QPushButton {{ background:{color('accent')}; color:{color('on-accent')}; font-weight:600;"
            " border:none; border-radius:6px; padding:0 12px; }")
        from PySide6.QtWidgets import QGraphicsDropShadowEffect

        from .settings_layout import plain_button_height
        shadow = QGraphicsDropShadowEffect(self.apply_button)
        shadow.setBlurRadius(10)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.apply_button.setGraphicsEffect(shadow)
        self.apply_button.setFixedHeight(plain_button_height())
        self.apply_button.adjustSize()
        self.apply_button.clicked.connect(lambda: self.applied.emit(self.character))
        self.apply_button.hide()
        self._place_button()
        self.setFixedSize(self.sizeHint())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{character.name if character.known else '아직 이름이 없는 캐릭터'} — 목소리: {character.pack}")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # ---- 자리 ----
    def card_rect(self) -> QRectF:
        """카드 사각형(이 위젯 좌표) — 대기 중엔 6px 떠오름."""
        lift = FLOAT if self._pending else 0
        return QRectF(1.5, PAD_TOP + 1.5 - lift, CARD_W - 3, CARD_H - 3)

    def name_lift(self) -> float:
        """이름을 올리는 양 — 테두리 띠 두께(캐릭터별). 적용 버튼은 이름 바로 위에 뜸(이름은 그대로)."""
        return NAME_LIFT.get(roster.folder(self.character), 0) if self.frame else 0

    def _place_button(self) -> None:
        card = self.card_rect()
        self.apply_button.move(round((CARD_W - self.apply_button.width()) / 2),
                               round(card.bottom() - APPLY_BOTTOM - self.apply_button.height()
                                     - NAME_LIFT.get(roster.folder(self.character), 0)))

    def bright(self) -> bool:
        return self._selected or self._pending or self._hover or self.keep_bright

    def set_keep_bright(self, on: bool) -> None:
        if bool(on) != self.keep_bright:
            self.keep_bright = bool(on)
            self._changed()

    def _changed(self) -> None:
        self.update()
        self.changed.emit()

    def set_outfit(self, key: str) -> None:
        """지금 입은 옷으로 카드 그림을 바꿈(기본 옷 = "")."""
        if key != self.outfit:
            self.outfit = key
            self._art = card_pixmap(self.character, key)
            self._changed()

    def affinity(self) -> int:
        return self._affinity

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self._changed()
        self.hovered.emit(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._changed()
        self.left.emit(self)
        super().leaveEvent(event)

    def set_selected(self, on: bool) -> None:
        if on != self._selected:
            self._selected = on
            if on:
                self.set_pending(False)
            self._changed()

    def set_affinity(self, value: int, quest: str = "") -> None:
        self._affinity = max(0, min(MAX_VALUE, int(value)))
        self._quest = quest
        self.update()

    def selected(self) -> bool:
        return self._selected

    def set_pending(self, on: bool) -> None:
        """'이 캐릭터로 적용' 대기(쓰는 중인 카드는 대기가 되지 않음)."""
        on = bool(on) and not self._selected
        if on != self._pending:
            self._pending = on
            self._place_button()
            self.apply_button.setVisible(on)
            self._changed()

    def pending(self) -> bool:
        return self._pending

    def set_details_visible(self, on: bool) -> None:
        """호감도 바·퀘스트 줄 보이기(제작자) / 숨기기(비제작자 — 카드 아래 자리도 줄임)."""
        if bool(on) != self._details:
            self._details = bool(on)
            self.setFixedSize(self.sizeHint())
            self._changed()

    def details_visible(self) -> bool:
        return self._details

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.character)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card = self.card_rect()
        if self._pending:   # 떠오른 카드 아래 그림자
            for i, alpha in enumerate((40, 28, 18, 10)):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, alpha))
                p.drawRoundedRect(card.adjusted(2 - i, 4 + i * 2, -2 + i, 4 + i * 2), ART_RADIUS, ART_RADIUS)
        clip = QPainterPath()
        clip.addRoundedRect(card, ART_RADIUS, ART_RADIUS)
        p.fillPath(clip, self.palette().color(QPalette.ColorRole.Base))
        p.save()
        p.setClipPath(clip)
        self._paint_art(p, card)
        if not self.bright():   # 쓰지 않는 카드 25% 어둡게(카드 그림에만)
            p.fillRect(card, QColor(0, 0, 0, DIM_ALPHA))
        p.restore()
        if self.frame is None:   # 테두리 그림이 없는 카드(???)는 얇은 선
            p.setPen(QPen(self.palette().color(QPalette.ColorRole.Mid), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(card, ART_RADIUS, ART_RADIUS)
        if self._details:
            self._paint_bar(p)
        p.end()

    def _paint_art(self, p: QPainter, card: QRectF) -> None:
        art = self._art
        if art.isNull():
            return
        if not self.character.known:  # 실루엣 → 테마 회색으로 칠함(그다음 같은 규칙으로 채움)
            tinted = QPixmap(art.size())
            tinted.fill(Qt.GlobalColor.transparent)
            tp = QPainter(tinted)
            tp.drawPixmap(0, 0, art)
            tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            tp.fillRect(tinted.rect(), QColor("#4a4f58") if _dark() else QColor("#c4c8cf"))
            tp.end()
            art = tinted
        fit = roster.folder(self.character) in CARD_FIT_HEIGHT and self.outfit == outfits.BASE
        draw_card_art(p, card, art, fit)

    def paint_overlay(self, p: QPainter, origin: QPointF) -> None:
        """테두리 층이 부름 — 테두리 그림·이름·명판(origin = 이 카드 위젯의 왼쪽 위, 층 좌표)."""
        card = self.card_rect().translated(origin)
        if self.frame is not None:
            pixmap = self.frame[0] if self.bright() else self._frame_dim
            rect = self.frame[1].translated(card.topLeft() - QPointF(1.5, 1.5))
            p.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
        self._paint_name(p, card)
        if self._selected:
            self._paint_plate(p, card)

    def _paint_plate(self, p: QPainter, card: QRectF) -> None:
        """`✓ 사용 중` 명판 — 테두리 아래 가운데에 반쯤 걸침(캐릭터 색 바탕, 흰 2px 테두리)."""
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        rect = QRectF(card.center().x() - PLATE_W / 2, card.bottom() - PLATE_H / 2, PLATE_W, PLATE_H)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(QColor(self.character.color if self.character.known else color("accent")))
        p.drawRoundedRect(rect, PLATE_H / 2, PLATE_H / 2)
        p.setPen(QColor("#ffffff"))
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "✓ 사용 중")

    def _paint_name(self, p: QPainter, card: QRectF) -> None:
        font = QFont(self.font())
        font.setPixelSize(30)
        font.setWeight(QFont.Weight.Black)
        path = QPainterPath()
        path.addText(QPointF(0, 0), font, self.character.name)
        box = path.boundingRect()
        path.translate(card.center().x() - box.center().x(), card.bottom() - 14 - self.name_lift() - box.bottom())
        # 이름: 캐릭터 색 + 캐릭터 외곽선(기본 흰색, Starline 금). 미정(???)은 흰 글자 + 어두운 테두리(시안 charsel_*)
        edge = self.character.outline if self.character.known else "#3a3d44"
        dim = not self.bright()
        edge_col = QColor(edge)
        fill_col = QColor(self.character.color if self.character.known else "#ffffff")
        if dim:   # 이름도 카드와 같이 25% 어둡게
            edge_col = edge_col.darker(133)
            fill_col = fill_col.darker(133)
        p.setPen(QPen(edge_col, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill_col)
        p.drawPath(path)

    def _paint_bar(self, p: QPainter) -> None:
        y = PAD_TOP + CARD_H + PAD_BOTTOM
        heart_col = QColor(HEART if self.character.known else color("muted"))
        font = QFont(self.font())
        font.setPixelSize(17)
        p.setFont(font)
        p.setPen(heart_col)
        p.drawText(QRectF(4, y, 22, BAR_H), int(Qt.AlignmentFlag.AlignCenter), "♥")
        track = QRectF(32, y + BAR_H / 2 - 5, CARD_W - 36, 10)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.palette().color(QPalette.ColorRole.Mid))
        p.drawRoundedRect(track, 5, 5)
        if self._affinity > 0:
            fill = QRectF(track.left(), track.top(), max(10.0, track.width() * self._affinity / MAX_VALUE), track.height())
            p.setBrush(heart_col)
            p.drawRoundedRect(fill, 5, 5)
        if self._quest:  # 바 아래 한 줄 — 지금 구간 퀘스트와 진행
            small = QFont(self.font())
            small.setPixelSize(11)
            p.setFont(small)
            p.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            p.drawText(QRectF(6, y + BAR_H, CARD_W - 8, QUEST_H),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                       self._quest)

    def sizeHint(self) -> QSize:  # noqa: N802
        base = PAD_TOP + CARD_H + PAD_BOTTOM
        return QSize(CARD_W, base + BAR_H + QUEST_H + 4 if self._details else base)


class CardFrameLayer(QWidget):
    """카드 테두리·이름·명판 층 — 탭 전체를 덮고 마우스는 통과(장식이 카드 칸 밖으로 넘쳐도 잘리지 않게)."""

    def __init__(self, parent: QWidget, cards: list[CharacterCard]) -> None:
        super().__init__(parent)
        self.cards = cards
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        for card in cards:
            card.changed.connect(self.update)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for card in self.cards:
            if card.isVisible():
                card.paint_overlay(p, QPointF(card.mapTo(self.parentWidget(), QPoint(0, 0))))
        p.end()


def _dark() -> bool:
    try:
        from .theme import is_dark
        return is_dark()
    except Exception:  # noqa: BLE001
        return True


# ---- 착장 서랍(기획 11-25, 시안 docs/characters/assets/공용/시안/카드_착장서랍.png) ----
DRAWER_BG = "#3a3d44"
CELL_W, CELL_H = 112, 140     # 칸 그림 — 카드와 같은 4:5(사용자 11-25 '서랍 칸 비율이 카드와 달라 그림 높낮이가 달라 보임')
CELL_GAP = 10
CAPTION_H = 22
DRAWER_W = CELL_GAP + 2 * (CELL_W + CELL_GAP)
DRAWER_OPEN_MS = 170


def _gray(pixmap: QPixmap) -> QPixmap:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_ARGB32)
    # 투명도는 원래 그림 그대로
    alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
    out = QImage(gray)
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, alpha)
    painter.end()
    return QPixmap.fromImage(out)


class OutfitCell(QWidget):
    """서랍 칸 하나 — 카드 그림(칸에 꽉, 위 기준) + 흰 3px 테두리·아래 그림자 + 아래 작은 글.
    잠김: 흑백 + 가운데 가로 띠 '해금'(사용자 11-25). 누르면 picked(옷)."""
    picked = Signal(object)

    def __init__(self, character: roster.Character, outfit: outfits.Outfit, unlocked: bool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.outfit = outfit
        self.unlocked = unlocked
        art = card_pixmap(character, outfit.key)
        self._art = art if unlocked or art.isNull() else _gray(art)
        self.setFixedSize(CELL_W, CELL_H + CAPTION_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor if unlocked else Qt.CursorShape.ForbiddenCursor)
        self.setToolTip("" if unlocked else self.locked_text())

    def caption(self) -> str:
        if self.outfit.level == 0:
            return "기본"
        return f"♥ {self.outfit.level} · 입을 수 있음" if self.unlocked else f"♥ {self.outfit.level}"

    def locked_text(self) -> str:
        return f"호감도 {self.outfit.level}에서 열려요"

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.picked.emit(self.outfit)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        frame = QRectF(2, 1, CELL_W - 4, (CELL_W - 4) * CARD_H / CARD_W)   # 4:5
        p.setPen(Qt.PenStyle.NoPen)   # 아래 그림자
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawRoundedRect(frame.translated(0, 4), 8, 8)
        clip = QPainterPath()
        clip.addRoundedRect(frame, 8, 8)
        p.fillPath(clip, QColor("#ffffff"))
        if not self._art.isNull():   # 카드와 같은 규칙(머리 위 여백·양옆 자르기·아래 잘림)
            p.save()
            p.setClipPath(clip)
            draw_card_art(p, frame, self._art)
            if not self.unlocked:   # 가운데 가로 띠 '해금'(가슴 높이 62%)
                band = QRectF(frame.left(), frame.top() + frame.height() * 0.62 - 17, frame.width(), 34)
                p.fillRect(band, QColor(20, 20, 26, 190))
                p.fillRect(QRectF(band.left(), band.top(), band.width(), 3), QColor(HEART))
                p.fillRect(QRectF(band.left(), band.bottom() - 3, band.width(), 3), QColor(HEART))
                font = QFont(self.font())
                font.setPixelSize(16)
                font.setWeight(QFont.Weight.Bold)
                p.setFont(font)
                p.setPen(QColor("#ffffff"))
                p.drawText(band, int(Qt.AlignmentFlag.AlignCenter), "해금")
            p.restore()
        p.setPen(QPen(QColor("#ffffff"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(frame, 8, 8)
        small = QFont(self.font())
        small.setPixelSize(11)
        p.setFont(small)
        p.setPen(QColor(HEART) if self.unlocked and self.outfit.level else QColor("#b8bcc4"))
        p.drawText(QRectF(0, CELL_H - 2, CELL_W, CAPTION_H), int(Qt.AlignmentFlag.AlignCenter), self.caption())
        p.end()


class OutfitDrawer(QWidget):
    """카드 옆에 겹쳐 뜨는 서랍 — 지금 입은 옷을 뺀 두 벌(기본 → 50 → 100 순서).
    열린 칸 누름 → chosen(카드, 옷 key), 잠긴 칸 누름 → 짧은 안내."""
    chosen = Signal(object, str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.card: CharacterCard | None = None
        self.cells: list[OutfitCell] = []
        self.opens_left = False
        self.notice = ""
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(DRAWER_OPEN_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.hide()

    def open_for(self, card: "CharacterCard", animate: bool = True) -> None:
        folder = roster.folder(card.character)
        items = outfits.drawer(folder, card.outfit)
        if not items:
            self.close_drawer()
            return
        if self.card is not None and self.card is not card:
            self.card.set_keep_bright(False)
        self.card = card
        card.set_keep_bright(True)   # 서랍이 열린 카드는 원래 밝기
        self.notice = ""
        for cell in self.cells:
            cell.hide()   # deleteLater는 다음 이벤트 때 지워짐 — 그 전에 겹쳐 그려지지 않게
            cell.deleteLater()
        self.cells = []
        for i, outfit in enumerate(items):
            cell = OutfitCell(card.character, outfit, outfits.unlocked(outfit, card.affinity()), self)
            cell.move(CELL_GAP + i * (CELL_W + CELL_GAP), CELL_GAP)
            cell.picked.connect(self._picked)
            cell.show()
            self.cells.append(cell)
        tab = self.parentWidget()
        rect = card.card_rect().translated(QPointF(card.mapTo(tab, QPoint(0, 0)))).toAlignedRect()
        top_left = rect.topLeft()
        height = CELL_GAP * 2 + CELL_H + CAPTION_H   # 칸(4:5) + 아래 글
        right = QRect(rect.right() + DRAWER_GAP, top_left.y(), DRAWER_W, height)
        # 맨 오른쪽 줄은 왼쪽으로(창 밖으로 안 잘리게), 왼쪽·가운데 줄은 오른쪽으로
        cards = getattr(tab, "cards", [])
        column = cards.index(card) % COLUMNS if card in cards else 0
        self.opens_left = column == COLUMNS - 1
        target = QRect(rect.left() - DRAWER_GAP - DRAWER_W, top_left.y(), DRAWER_W, height) if self.opens_left else right
        target.moveLeft(max(2, min(target.left(), tab.width() - DRAWER_W - 2)))   # 창이 좁아도 탭 안에
        self.raise_()
        self.show()
        if animate:
            start = QRect(target.right() - 20, target.top(), 20, height) if self.opens_left \
                else QRect(target.left(), target.top(), 20, height)
            self._anim.stop()
            self._anim.setStartValue(start)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._anim.stop()
            self.setGeometry(target)

    def close_drawer(self) -> None:
        self._anim.stop()
        if self.card is not None:
            self.card.set_keep_bright(False)
        self.card = None
        self.hide()

    def _picked(self, outfit: outfits.Outfit) -> None:
        cell = next(c for c in self.cells if c.outfit is outfit)
        if not cell.unlocked:
            self.notice = cell.locked_text()
            QToolTip.showText(cell.mapToGlobal(QPoint(CELL_W // 2, CELL_H // 2)), self.notice, cell)
            return
        if self.card is not None:
            self.chosen.emit(self.card, outfit.key)

    def leaveEvent(self, event) -> None:  # noqa: N802
        parent = self.parentWidget()
        if hasattr(parent, "_maybe_close_drawer"):
            QTimer.singleShot(60, parent._maybe_close_drawer)
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1.5, 1.5, self.width() - 3, self.height() - 3)
        p.setPen(QPen(QColor(color("accent")), 3))
        p.setBrush(QColor(DRAWER_BG))
        p.drawRoundedRect(rect, 10, 10)
        p.end()


class AffinityEditor(QWidget):
    """제작자용 호감도 바로 바꾸기 — 숫자 칸 + 구간 버튼. 바꾸면 edited(캐릭터 키, 값)."""
    edited = Signal(str, int)

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setFixedWidth(CARD_W)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self.spin = QSpinBox()
        self.spin.setRange(0, MAX_VALUE)
        self.spin.setToolTip("호감도(제작자 확인용 — 하루 상한과 무관하게 바로 저장)")
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(54)
        self.spin.valueChanged.connect(lambda v: self.edited.emit(self.key, int(v)))
        row.addWidget(self.spin)
        self.buttons = []
        for stage in STAGES:
            button = QPushButton(str(stage))
            button.setFixedWidth(31)
            button.setToolTip(f"호감도 {stage}으로")
            button.clicked.connect(lambda _c=False, v=stage: self.spin.setValue(v))
            row.addWidget(button)
            self.buttons.append(button)
        row.addStretch(1)

    def show_value(self, value: int) -> None:
        self.spin.blockSignals(True)
        self.spin.setValue(int(value))
        self.spin.blockSignals(False)


class CharacterTab(QWidget):
    """캐릭터 고르기 + 화면에 띄우기 스위치 + (제작자) 호감도 바·퀘스트·바로 바꾸기(베타 11-24 — 비제작자는 숨김)."""
    voice_pack_changed = Signal()
    pet_toggled = Signal(bool)
    affinity_edited = Signal()
    outfit_changed = Signal(str)   # 캐릭터 key — 그 캐릭터 옷을 갈아입음
    motion_requested = Signal(str)   # 제작자: 호감도 모션 key — 펫이 바로 한 번(Windows 확인용, 기획 11-26)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.addWidget(FeatureHeader("캐릭터", DESCRIPTION))
        top = QHBoxLayout()
        self.pet_switch = switch("화면에 캐릭터 띄우기")
        self.pet_switch.setChecked(config.load_pet_on())
        self.pet_switch.toggled.connect(self._on_pet)
        top.addWidget(self.pet_switch)
        top.addStretch(1)
        v.addLayout(top)
        self.pet_hint = hint_label("")
        v.addWidget(self.pet_hint)
        # 대사 목소리(사용자 11-24): 말풍선 줄에 녹음이 있으면 소리로도 — 끄면 말풍선만(알림 목소리는 그대로)
        voice_row = QHBoxLayout()
        self.voice_switch = switch("대사 목소리")
        self.voice_switch.setChecked(config.load_voice_lines())
        self.voice_switch.toggled.connect(lambda on: config.save_character(voiceLines=bool(on)))
        voice_row.addWidget(self.voice_switch)
        voice_row.addStretch(1)
        v.addLayout(voice_row)
        v.addWidget(hint_label("캐릭터가 말할 때 녹음된 대사는 목소리로도 들려줘요. 버프 알림 목소리와는 따로예요."))
        # 기본 녹음 목소리로 돌아가기(0.56.0 — 설정의 목소리 고르기가 캐릭터 탭으로 옮겨와 카드만 누르면 돌아갈 길이 없었음)
        default_row = QHBoxLayout()
        self.default_button = QPushButton("기본 목소리로")
        self.default_button.setToolTip("캐릭터를 고르지 않고 기본 녹음 목소리로 알림을 들어요.")
        self.default_button.clicked.connect(self.choose_default)
        default_row.addWidget(self.default_button)
        default_row.addStretch(1)
        v.addLayout(default_row)
        # 제작자 전용 — 지금 캐릭터·지금 옷에 그림이 있는 호감도 모션을 바로 한 번(25·75를 기다리지 않고 확인)
        self.motion_row = QHBoxLayout()
        self.motion_box = QWidget()
        self.motion_box.setLayout(self.motion_row)
        self.motion_row.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.motion_box)
        v.addSpacing(10)   # 첫 줄 테두리 장식이 위로 넘치는 자리
        grid = QGridLayout()
        grid.setContentsMargins(8, 0, 0, 0)   # 왼쪽 줄 장식(리본·꽃)이 탭 밖으로 안 잘리게
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(18)
        self.cards: list[CharacterCard] = []
        self.editors: list[AffinityEditor] = []
        for i, character in enumerate(roster.ROSTER):
            cell = QVBoxLayout()
            cell.setSpacing(4)
            card = CharacterCard(character)
            card.clicked.connect(self.preview)   # 누르면 인사만(사용자 11-25 B안)
            card.applied.connect(self.choose)    # 카드 안 '이 캐릭터로 적용' → 선택
            card.hovered.connect(self._hover_card)
            card.left.connect(self._leave_card)
            editor = AffinityEditor(character.key)
            editor.edited.connect(self.set_affinity)
            cell.addWidget(card)
            cell.addWidget(editor)
            grid.addLayout(cell, i // COLUMNS, i % COLUMNS, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.cards.append(card)
            self.editors.append(editor)
        grid.setColumnStretch(COLUMNS, 1)
        v.addLayout(grid)
        v.addStretch(1)
        v.addWidget(credit_label(VOICE_CREDIT))   # 목소리 출처(ElevenLabs 무료 요금제 표기, 기획 11-26)
        self._preview = None
        self.frames = CardFrameLayer(self, self.cards)   # 테두리·이름·명판(카드 위, 서랍 아래)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(DRAWER_DELAY_MS)
        self._hover_timer.timeout.connect(self._hover_elapsed)
        self._hover_target: CharacterCard | None = None
        self.drawer = OutfitDrawer(self)
        self.drawer.chosen.connect(self.wear)
        self.set_creator(False)
        self.refresh()

    def set_creator(self, on: bool) -> None:
        """카드 아래 ♥ 바·퀘스트 줄은 모두에게(11-26 게이지 배포), 호감도 조절 칸은 제작자만."""
        self._creator = bool(on)
        for card, editor in zip(self.cards, self.editors):
            card.set_details_visible(True)
            editor.setVisible(self._creator)
        self._refresh_motion_buttons()

    def _refresh_motion_buttons(self) -> None:
        """제작자: 고른 캐릭터·입은 옷의 호감도 모션 버튼(그림이 다 있는 것만). 비제작자는 숨김."""
        from ..character import motions
        while self.motion_row.count():
            item = self.motion_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        chosen = roster.by_pack(config.load_voice_pack())
        buttons = []
        if self._creator and chosen is not None and chosen.has_pet:
            folder = roster.folder(chosen)
            outfit = outfits.wearing(folder, config.load_outfit(chosen.key))
            base = paths.resource_dir() / "characters" / folder
            where = base / "outfits" / outfit if outfit and (base / "outfits" / outfit).is_dir() else base
            from .pet_window import frame_file
            for m in motions.of(folder, where != base):   # 영상판 다래가 착장을 입으면 예전 시트 모션
                if all(frame_file(where, n) is not None for n in m.names()):   # PNG 또는 WebP(Starline 영상판)
                    btn = QPushButton(f"♥ {m.stage} 모션")
                    btn.setToolTip(f"{m.key} — 펫이 서 있으면 바로 한 번(제작자 확인용)")
                    btn.clicked.connect(lambda _=False, k=m.key: self.motion_requested.emit(k))
                    buttons.append(btn)
        if buttons:
            label = hint_label("모션 바로 보기(제작자)")
            self.motion_row.addWidget(label)
            for btn in buttons:
                self.motion_row.addWidget(btn)
            self.motion_row.addStretch(1)
        self.motion_box.setVisible(bool(buttons))

    def refresh(self) -> None:
        """고른 캐릭터 강조·호감도 바·안내 글을 저장 값으로 다시 맞춘다(적용 대기는 풀림)."""
        pack = config.load_voice_pack()
        for card in self.cards:
            card.set_pending(False)
        rules = Rules.from_dict(config.load_affinity_rules())
        for card, editor in zip(self.cards, self.editors):
            card.set_selected(card.character.pack == pack)
            card.set_outfit(outfits.wearing(roster.folder(card.character), config.load_outfit(card.character.key)))
            affinity = Affinity.load(config.load_affinity(card.character.key), rules)
            card.set_affinity(affinity.value, affinity.quest_text(card.character.name))
            editor.show_value(affinity.value)
        chosen = roster.by_pack(pack)
        if chosen is None:
            text = "카드를 누르면 인사를 들어 볼 수 있고, '이 캐릭터로 적용'을 누르면 그 목소리로 알림을 말해 줘요. 지금은 기본 녹음 목소리예요."
        elif not chosen.has_pet:
            text = "이 캐릭터는 아직 화면에 띄울 그림이 없어요. 목소리 알림만 바뀌어요."
        else:
            text = "게임 중엔 구석에서 조용히 기다리고, 게임 밖에선 화면 아래를 돌아다녀요. 끌어서 옮길 수 있어요."
        self.pet_hint.setText(text)
        self.default_button.setEnabled(bool(pack))   # 이미 기본이면 누를 일 없음
        if hasattr(self, "_creator"):
            self._refresh_motion_buttons()

    def set_affinity(self, key: str, value: int) -> None:
        """제작자가 호감도를 바로 바꿈 → 값 + 그 값까지의 구간 퀘스트는 깬 것으로(오늘 횟수·누적은 그대로)."""
        affinity = Affinity.load(config.load_affinity(key), Rules.from_dict(config.load_affinity_rules()))
        affinity.set_value(value)
        config.save_character(affinity=(key, affinity.to_dict()))
        self.refresh()
        self.affinity_edited.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.frames.setGeometry(self.rect())
        self.frames.raise_()
        if self.drawer.isVisible():
            self.drawer.raise_()
        super().resizeEvent(event)

    def _hover_card(self, card: CharacterCard) -> None:
        """카드에 마우스 → 0.3초 머물면 서랍(그 전에 나가면 안 열림)."""
        if self.drawer.card is card and self.drawer.isVisible():
            return
        self._hover_target = card
        self._hover_timer.start()

    def _hover_elapsed(self) -> None:
        card, self._hover_target = self._hover_target, None
        if card is not None:
            self.open_drawer(card)

    def _leave_card(self, card: CharacterCard) -> None:
        if self._hover_target is card:
            self._hover_timer.stop()
            self._hover_target = None
        QTimer.singleShot(60, self._maybe_close_drawer)

    def open_drawer(self, card: CharacterCard) -> None:
        """카드에 마우스 → 옆에 착장 서랍(착장 없는 캐릭터·미정 캐릭터는 안 열림)."""
        if self.drawer.card is card and self.drawer.isVisible():
            return
        self.drawer.open_for(card)

    def _maybe_close_drawer(self, pos: QPoint | None = None) -> None:
        """마우스가 카드·서랍 둘 다 밖이면 닫음(pos는 이 탭 좌표, 없으면 지금 커서)."""
        card = self.drawer.card
        if card is None:
            return
        pos = self.mapFromGlobal(QCursor.pos()) if pos is None else pos
        card_rect = QRect(card.mapTo(self, QPoint(0, 0)), card.size())   # 카드 위젯(떠오른 자리 포함)
        if not card_rect.contains(pos) and not self.drawer.geometry().contains(pos):
            self.drawer.close_drawer()

    def wear(self, card: CharacterCard, key: str) -> None:
        """열린 옷 누름 → 바로 갈아입기(확인 창·호감도 감소 없음). 그 캐릭터 옷만 저장 — 고른 캐릭터·적용 대기는 그대로."""
        config.save_character(outfit=(card.character.key, key))
        card.set_outfit(key)
        self.drawer.open_for(card, animate=False)   # 서랍은 '지금 옷 뺀 두 벌'로 다시
        self.outfit_changed.emit(card.character.key)
        self._refresh_motion_buttons()

    def preview(self, character: roster.Character) -> None:
        """카드 누름 → 그 캐릭터 인사만 듣기(선택은 그대로). 쓰는 중이 아니면 그 카드에 '이 캐릭터로 적용'(한 번에 하나)."""
        self._play_sample(character.pack)
        current = config.load_voice_pack()
        for card in self.cards:
            card.set_pending(card.character is character and character.pack != current)
        leaving = roster.by_pack(current)
        if leaving is not None and character.pack != current:   # 확정 전 안내(호감도 2차 '캐릭터 바꾸기')
            from ..character.affinity import _has_final
            josa = "이" if _has_final(leaving.name) else "가"
            self.pet_hint.setText(f"'이 캐릭터로 적용'을 누르면 {leaving.name}{josa} 서운해할 거예요(♥ −3).")
        if self.drawer.isVisible() and self.drawer.card is not None:   # 떠오른 카드 자리에 맞춰 서랍도
            self.drawer.open_for(self.drawer.card, animate=False)

    def choose(self, character: roster.Character) -> None:
        """'이 캐릭터로 적용' → 알림 목소리 팩 저장(인사는 이미 들었으므로 다시 안 틂). 떠나는 캐릭터는 −3(하루 한 번)."""
        leaving = roster.by_pack(config.load_voice_pack())
        if leaving is not None and leaving.pack != character.pack:
            from .character_controller import today
            affinity = Affinity.load(config.load_affinity(leaving.key), Rules.from_dict(config.load_affinity_rules()))
            affinity.leave(today())
            config.save_character(affinity=(leaving.key, affinity.to_dict()))
        config.save_voice_pack(character.pack)
        self.refresh()
        self.voice_pack_changed.emit()

    def choose_default(self) -> None:
        """'기본 목소리로' — 고른 캐릭터를 풀고 기본 녹음으로(카드 누름과 같이 미리듣기 한 번)."""
        config.save_voice_pack("")
        self._play_sample("")
        self.refresh()
        self.voice_pack_changed.emit()

    def _play_sample(self, pack: str) -> None:
        """그 팩 인사 듣기 — 인사.mp3·인사2~5.mp3 중 있는 것 무작위(연속 같은 것 없음), 없으면 투아림 알림."""
        from .notifier import SoundNotifier, greeting_path

        sample = greeting_path(pack)
        if not sample.exists():
            return
        if self._preview is None:
            self._preview = SoundNotifier({})
        self._preview.set_sounds({"preview": sample})
        self._preview.play("preview")

    def hideEvent(self, event) -> None:  # noqa: N802
        """탭을 떠나면 적용 대기는 풀림."""
        for card in self.cards:
            card.set_pending(False)
        self.drawer.close_drawer()
        super().hideEvent(event)

    def _on_pet(self, on: bool) -> None:
        config.save_character(pet=bool(on))
        self.pet_toggled.emit(bool(on))
