"""캐릭터 탭(docs/character-pet-spec.md 1절·3절 1번) — 설정의 '알림 목소리 고르기'를 옮겨 온 캐릭터 고르기.

- 맨 위 `화면에 캐릭터 띄우기` 스위치(펫 창 켜기·끄기).
- 상반신 카드 한 줄 3개(탭 스크롤로 위아래). 이름은 캐릭터 색 + 흰 테두리, 미정 캐릭터는 실루엣을 테마 회색으로 칠하고 `???`.
- 카드를 누르면 그 목소리가 나오고 바로 선택(알림 목소리 팩 저장), 고른 카드는 둘레 강조.
- 카드 아래 ♥ 호감도 바(0~100) + 바 아래 한 줄 지금 구간 퀘스트와 진행(사용자 최종 규칙 11-24).
- 알파는 제작자 전용(11-24): 카드 아래 호감도 숫자 칸(0~100) + 구간 버튼(0/25/50/75/100)으로 바로 바꿈
  (하루 상한과 무관, 구간별 대사·반응 확인용).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout,
                               QWidget)

from .. import config, paths
from ..character import roster
from ..character.affinity import MAX_VALUE, STAGES, Affinity, Rules
from .palette import color
from .widgets import FeatureHeader, hint_label, switch

DESCRIPTION = "고른 캐릭터가 알림을 말해 주고, 화면에서 함께 지내요."
CARD_W, CARD_H = 224, 248
BAR_H = 22
QUEST_H = 18
HEART = "#FF6B9A"
COLUMNS = 3


def card_pixmap(character: roster.Character) -> QPixmap:
    return QPixmap(str(paths.resource_dir() / "characters" / character.card))


class CharacterCard(QWidget):
    """카드 하나 — 그림(윗부분 채움) + 이름 + 아래 ♥ 호감도 바. 누르면 clicked."""
    clicked = Signal(object)

    def __init__(self, character: roster.Character, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.character = character
        self._art = card_pixmap(character)
        self._selected = False
        self._affinity = 0
        self._quest = ""
        self.setFixedSize(CARD_W, CARD_H + BAR_H + QUEST_H + 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{character.name if character.known else '아직 이름이 없는 캐릭터'} — 목소리: {character.pack}")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_selected(self, on: bool) -> None:
        if on != self._selected:
            self._selected = on
            self.update()

    def set_affinity(self, value: int, quest: str = "") -> None:
        self._affinity = max(0, min(MAX_VALUE, int(value)))
        self._quest = quest
        self.update()

    def selected(self) -> bool:
        return self._selected

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.character)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        card = QRectF(1.5, 1.5, CARD_W - 3, CARD_H - 3)
        clip = QPainterPath()
        clip.addRoundedRect(card, 10, 10)
        p.fillPath(clip, self.palette().color(QPalette.ColorRole.Base))
        p.save()
        p.setClipPath(clip)
        self._paint_art(p, card)
        p.restore()
        self._paint_name(p, card)
        border = QColor(color("accent")) if self._selected else self.palette().color(QPalette.ColorRole.Mid)
        p.setPen(QPen(border, 3 if self._selected else 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card, 10, 10)
        self._paint_bar(p)
        p.end()

    def _paint_art(self, p: QPainter, card: QRectF) -> None:
        art = self._art
        if art.isNull():
            return
        if not self.character.known:  # 실루엣 → 테마 회색으로 칠함
            tinted = QPixmap(art.size())
            tinted.fill(Qt.GlobalColor.transparent)
            tp = QPainter(tinted)
            tp.drawPixmap(0, 0, art)
            tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            tp.fillRect(tinted.rect(), QColor("#4a4f58") if _dark() else QColor("#c4c8cf"))
            tp.end()
            art = tinted
        # 폭에 맞추고 위에서부터(얼굴이 보이게) — 남는 아래는 잘림
        scale = card.width() / art.width()
        h = art.height() * scale
        top = card.top() + (8 if self.character.known else 18)
        p.drawPixmap(QRectF(card.left(), top, card.width(), h), art, QRectF(art.rect()))

    def _paint_name(self, p: QPainter, card: QRectF) -> None:
        font = QFont(self.font())
        font.setPixelSize(30)
        font.setWeight(QFont.Weight.Black)
        path = QPainterPath()
        path.addText(QPointF(0, 0), font, self.character.name)
        box = path.boundingRect()
        path.translate(card.center().x() - box.center().x(), card.bottom() - 14 - box.bottom())
        # 이름: 캐릭터 색 + 흰 테두리. 미정(???)은 흰 글자 + 어두운 테두리(시안 charsel_*)
        edge = "#ffffff" if self.character.known else "#3a3d44"
        p.setPen(QPen(QColor(edge), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.character.color if self.character.known else "#ffffff"))
        p.drawPath(path)

    def _paint_bar(self, p: QPainter) -> None:
        y = CARD_H + 6
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
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._quest)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(CARD_W, CARD_H + BAR_H + QUEST_H + 8)


def _dark() -> bool:
    try:
        from .theme import is_dark
        return is_dark()
    except Exception:  # noqa: BLE001
        return True


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
    """캐릭터 고르기 + 화면에 띄우기 스위치 + (제작자) 호감도 바로 바꾸기."""
    voice_pack_changed = Signal()
    pet_toggled = Signal(bool)
    affinity_edited = Signal()

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
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(14)
        self.cards: list[CharacterCard] = []
        self.editors: list[AffinityEditor] = []
        for i, character in enumerate(roster.ROSTER):
            cell = QVBoxLayout()
            cell.setSpacing(4)
            card = CharacterCard(character)
            card.clicked.connect(self.choose)
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
        self._preview = None
        self.refresh()

    def refresh(self) -> None:
        """고른 캐릭터 강조·호감도 바·안내 글을 저장 값으로 다시 맞춘다."""
        pack = config.load_voice_pack()
        rules = Rules.from_dict(config.load_affinity_rules())
        for card, editor in zip(self.cards, self.editors):
            card.set_selected(card.character.pack == pack)
            affinity = Affinity.load(config.load_affinity(card.character.key), rules)
            card.set_affinity(affinity.value, affinity.quest_text())
            editor.show_value(affinity.value)
        chosen = roster.by_pack(pack)
        if chosen is None:
            text = "카드를 누르면 그 캐릭터 목소리로 알림을 말해 줘요. 지금은 기본 녹음 목소리예요."
        elif not chosen.has_pet:
            text = "이 캐릭터는 아직 화면에 띄울 그림이 없어요. 목소리 알림만 바뀌어요."
        else:
            text = "게임 중엔 구석에서 조용히 기다리고, 게임 밖에선 화면 아래를 돌아다녀요. 끌어서 옮길 수 있어요."
        self.pet_hint.setText(text)

    def set_affinity(self, key: str, value: int) -> None:
        """제작자가 호감도를 바로 바꿈 → 값 + 그 값까지의 구간 퀘스트는 깬 것으로(오늘 횟수·누적은 그대로)."""
        affinity = Affinity.load(config.load_affinity(key), Rules.from_dict(config.load_affinity_rules()))
        affinity.set_value(value)
        config.save_character(affinity=(key, affinity.to_dict()))
        self.refresh()
        self.affinity_edited.emit()

    def choose(self, character: roster.Character) -> None:
        """카드 누름 → 그 목소리 미리듣기 + 바로 선택(알림 목소리 팩 저장)."""
        config.save_voice_pack(character.pack)  # 먼저 저장 → sound_path가 선택 팩을 가리킴
        self._play_sample()
        self.refresh()
        self.voice_pack_changed.emit()

    def _play_sample(self) -> None:
        from .notifier import SoundNotifier, sound_path

        sample = sound_path("투아림 부스트 발동 직전.mp3")
        if not sample.exists():
            return
        if self._preview is None:
            self._preview = SoundNotifier({})
        self._preview.set_sounds({"preview": sample})
        self._preview.play("preview")

    def _on_pet(self, on: bool) -> None:
        config.save_character(pet=bool(on))
        self.pet_toggled.emit(bool(on))
