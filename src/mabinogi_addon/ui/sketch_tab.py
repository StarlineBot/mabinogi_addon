"""편의기능 › 그림대화 탭(그림대화 명세 3절).

256×96 캔버스(3배 표시)에 그리거나 이미지를 불러와 다듬고, 게임의 그림대화 폴더에 2비트 PNG로 저장한다.
서명은 내가 마지막에 그린 recentchatimage.png에서만 바이트 그대로 가져온다(사칭 방지, 명세 2절).
그리기·파일 형식은 sketch 패키지의 순수 로직이고, 이 파일은 화면과 입력만 다룬다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QStandardPaths, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import config
from ..sketch import convert
from ..sketch.canvas import BACKGROUND, GRAY_PALETTE, SketchCanvas
from ..sketch.pngfile import HEIGHT, RECENT_NAME, WIDTH, chat_filename, encode_png, read_signature_file
from .help_dialog import help_button
from .palette import color
from .sketch_import_dialog import SketchImportDialog, indices_pixmap
from .widgets import FeatureHeader, hint_label, wrapping_row

TOOLS = (("pen", "펜"), ("eraser", "지우개"), ("fill", "채우기"), ("line", "직선"),
         ("rect", "네모"), ("picker", "스포이드"))
WIDTHS = (1, 2, 4, 8)
ZOOMS = (1, 2, 3, 4, 6, 8)
DEFAULT_ZOOM = 3
PALETTE_ITEMS = (("흑백", "gray"), ("자동", "auto"), ("선명", "vivid"), ("직접 고르기", "custom"))
NO_SIGNATURE = "게임에서 그림대화를 한 번 그리면 서명을 가져올 수 있어요"

HELP_HTML = """
<p><b>그림대화 만들기</b>는 게임의 그림대화(256×96, 4색) 그림을 미리 만들어 두는 기능이에요.</p>
<ul>
<li>흰 캔버스에 바로 그리거나 <b>이미지 불러오기…</b>(파일·끌어 놓기·Ctrl+V)로 그림을 가져와요.</li>
<li>색 칸을 두 번 누르면 그 칸의 색을 바꿔요. 그 칸으로 그린 곳이 한꺼번에 바뀌어요.</li>
<li>마우스 휠로 캔버스를 확대·축소해요. Ctrl+Z 되돌리기, Ctrl+Y 다시 하기.</li>
<li>색이 적은 그림(선화·이모티콘)이 잘 나와요. 사진은 4색 포스터 느낌이 돼요.</li>
</ul>
<p><b>서명</b>은 게임에서 마지막에 그린 그림대화(<code>recentchatimage.png</code>)에서만 가져와요.
받은 그림의 서명은 쓸 수 없고, 앱이 서명을 만들거나 고치지 않아요.
저장한 그림은 게임의 <b>그림 대화 이미지 보기</b>에 서명 이름으로 나타나요.</p>
"""


def default_sketch_dir() -> Path:
    """문서\\마비노기\\그림대화 — OneDrive가 문서 폴더를 옮겼을 수 있어 OS에서 문서 경로를 받는다."""
    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(docs or Path.home()) / "마비노기" / "그림대화"


def sketch_dir() -> Path:
    saved = config.load_sketch_dir()
    return Path(saved) if saved else default_sketch_dir()


def _display_dir(folder: Path) -> str:
    """기본 위치는 `문서\\마비노기\\그림대화`로 짧게, 바꾼 위치는 전체 경로."""
    if folder == default_sketch_dir():
        return "문서\\마비노기\\그림대화"
    return str(folder)


class SketchView(QWidget):
    """캔버스 확대 표시와 마우스 입력. 칸 번호 배열을 4색으로 칠해서만 보여준다."""

    zoom_changed = Signal(int)
    image_dropped = Signal(QImage)

    def __init__(self, tab: "SketchTab"):
        super().__init__()
        self._tab = tab
        self.zoom = DEFAULT_ZOOM
        self.fit_width = WIDTH * DEFAULT_ZOOM  # 3배 이하는 창 폭에 맞춰 조금 줄여 가로 스크롤 없이 보인다
        self.scale = float(DEFAULT_ZOOM)
        self._hover: QPointF | None = None
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        fit = max(1.0, self.fit_width / WIDTH)
        self.scale = min(float(self.zoom), fit) if self.zoom <= DEFAULT_ZOOM else float(self.zoom)
        self.setFixedSize(round(WIDTH * self.scale), round(HEIGHT * self.scale))

    def set_fit_width(self, width: int) -> None:
        if width > 0 and width != self.fit_width:
            self.fit_width = width
            self._apply_zoom()
            self.update()

    def set_zoom(self, zoom: int) -> None:
        zoom = min(ZOOMS, key=lambda z: abs(z - zoom))
        if zoom != self.zoom:
            self.zoom = zoom
            self._apply_zoom()
            self.update()
            self.zoom_changed.emit(zoom)

    def to_canvas(self, pos: QPointF) -> QPointF:
        return QPointF(pos.x() / self.scale - 0.5, pos.y() / self.scale - 0.5)

    def paintEvent(self, _event):
        p = QPainter(self)
        rgb = np.ascontiguousarray(self._tab.canvas.rgb())
        img = QImage(rgb.data, WIDTH, HEIGHT, WIDTH * 3, QImage.Format.Format_RGB888)
        p.drawImage(QRectF(self.rect()), img)  # 확대는 최근접(흐림 없음)
        if self._hover is not None and self._tab.tool in ("pen", "eraser"):
            d = self._tab.width_px * self.scale
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(color("accent")), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(self._hover, d / 2 + 1, d / 2 + 1)  # 펜 크기 원 미리보기
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._tab.press(self.to_canvas(event.position()))

    def mouseMoveEvent(self, event):
        self._hover = event.position()
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._tab.drag(self.to_canvas(event.position()))
        else:
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._tab.release(self.to_canvas(event.position()))

    def leaveEvent(self, _event):
        self._hover = None
        self.update()

    def wheelEvent(self, event):
        steps = event.angleDelta().y()
        if not steps:
            return
        i = ZOOMS.index(self.zoom) + (1 if steps > 0 else -1)
        self.set_zoom(ZOOMS[max(0, min(len(ZOOMS) - 1, i))])
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasImage() or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        image = _image_from_mime(event.mimeData())
        if image is not None:
            event.acceptProposedAction()
            self.image_dropped.emit(image)


def _image_from_mime(mime) -> QImage | None:
    if mime.hasImage():
        image = QImage(mime.imageData())
        if not image.isNull():
            return image
    for url in mime.urls() if mime.hasUrls() else ():
        if url.isLocalFile():
            image = QImage(url.toLocalFile())
            if not image.isNull():
                return image
    return None


class _ElidedLabel(QLabel):
    """전체 글자는 툴팁으로, 화면에는 칸 폭만큼 가운데를 …로 줄여 보여주는 라벨. 최소 폭이 글자 길이를 따르지 않는다."""

    def __init__(self):
        super().__init__()
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(0, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class _Slot(QPushButton):
    """색 칸. 한 번 누르면 고르기, 두 번 누르면 색 바꾸기 창."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        event.accept()


def _tool_qss() -> str:
    return (
        "QPushButton { border:1px solid palette(mid); border-radius:6px; padding:5px 12px; }"
        f"QPushButton:checked {{ background:{color('accent')}; color:{color('on-accent')};"
        f" border-color:{color('accent')}; font-weight:700; }}"
    )


class SketchTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.canvas = SketchCanvas()
        self.tool = "pen"
        self.width_px = 2
        self.slot = 0
        self._last: QPointF | None = None
        self._start: QPointF | None = None
        self._base: np.ndarray | None = None
        self._import: dict | None = None  # 마지막으로 불러온 그림(색 묶음 자동/선명 다시 바꾸기용)
        self.signature = None

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.addWidget(FeatureHeader(
            "그림대화 만들기",
            "흰 캔버스에 바로 그리거나 이미지를 불러와 다듬은 뒤, 게임의 그림대화 목록에 넣어요.",
            help_button("그림대화 만들기 사용법", HELP_HTML, self)))

        # 도구 줄
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.tool_group = QButtonGroup(self)
        self.tool_buttons: dict[str, QPushButton] = {}
        for key, text in TOOLS:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setStyleSheet(_tool_qss())
            b.clicked.connect(lambda _=False, k=key: self.set_tool(k))
            self.tool_group.addButton(b)
            self.tool_buttons[key] = b
            tools.addWidget(b)
        tools.addStretch(1)
        widths = QHBoxLayout()  # 글꼴이 크거나 창이 좁으면 굵기 줄은 다음 줄로 내려간다
        widths.setSpacing(6)
        widths.addWidget(QLabel("굵기"))
        self.width_group = QButtonGroup(self)
        self.width_buttons: dict[int, QPushButton] = {}
        for w in WIDTHS:
            b = QPushButton(str(w))
            b.setCheckable(True)
            b.setFixedWidth(36)
            b.setStyleSheet(_tool_qss())
            b.clicked.connect(lambda _=False, n=w: self.set_width(n))
            self.width_group.addButton(b)
            self.width_buttons[w] = b
            widths.addWidget(b)
        widths.addStretch(1)
        v.addLayout(wrapping_row(tools, widths))

        # 캔버스(휠 확대 시 넘치면 스크롤)
        self.view = SketchView(self)
        self.view.zoom_changed.connect(self._on_zoom)
        self.view.image_dropped.connect(self.open_import)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.view)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setFixedHeight(HEIGHT * DEFAULT_ZOOM + 2)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.scroll.viewport().installEventFilter(self)
        v.addWidget(self.scroll)

        # 캔버스 아래: 왼쪽에 크기 안내·색 4칸·편집 줄, 오른쪽에 실제 크기 미리보기(창 높이 안에 들어오게)
        below = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(8)
        below.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(4)
        real = hint_label("실제 크기")
        right.addWidget(real)
        self.real_preview = QLabel()
        self.real_preview.setFixedSize(WIDTH + 2, HEIGHT + 2)
        self.real_preview.setStyleSheet("border:1px solid palette(mid);")
        right.addWidget(self.real_preview)
        right.addStretch(1)
        below.addLayout(right)
        v.addLayout(below)
        self.zoom_label = hint_label("")
        left.addWidget(self.zoom_label)

        # 색 4칸 + 색 묶음
        colors = QHBoxLayout()
        colors.addWidget(QLabel("색 4칸"))
        self.slot_buttons: list[_Slot] = []
        for i in range(4):
            b = _Slot(str(i + 1))
            b.setFixedSize(34, 30)
            b.clicked.connect(lambda _=False, n=i: self.set_slot(n))
            b.double_clicked.connect(lambda n=i: self.edit_slot(n))
            self.slot_buttons.append(b)
            colors.addWidget(b)
        colors.addSpacing(12)
        colors.addWidget(QLabel("색 묶음"))
        self.palette_combo = QComboBox()
        for text, key in PALETTE_ITEMS:
            self.palette_combo.addItem(text, key)
        self.palette_combo.activated.connect(self._on_palette_combo)
        colors.addWidget(self.palette_combo)
        colors.addStretch(1)
        left.addLayout(colors)
        left.addWidget(hint_label("칸을 두 번 누르면 색을 바꿀 수 있어요. 바꾸면 그 색으로 그린 곳이 한꺼번에 바뀌어요."))

        # 편집 줄
        edit = QHBoxLayout()
        self.undo_btn = QPushButton("되돌리기")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn = QPushButton("다시 하기")
        self.redo_btn.clicked.connect(self.redo)
        self.clear_btn = QPushButton("전체 지우기")
        self.clear_btn.clicked.connect(self.clear)
        for b in (self.undo_btn, self.redo_btn, self.clear_btn):
            edit.addWidget(b)
        edit.addStretch(1)
        load = QHBoxLayout()  # 글꼴이 크면 불러오기 버튼은 다음 줄로
        load.addStretch(1)
        self.import_btn = QPushButton("이미지 불러오기…")
        self.import_btn.clicked.connect(self.choose_image)
        load.addWidget(self.import_btn)
        left.addLayout(wrapping_row(edit, load))

        # 게임에 넣기
        box = QGroupBox("게임에 넣기")
        g = QVBoxLayout(box)
        self.signature_label = QLabel()
        self.signature_label.setWordWrap(True)
        g.addWidget(self.signature_label)
        row = QHBoxLayout()
        row.addWidget(QLabel("저장 위치"))
        self.folder_label = _ElidedLabel()  # 긴 경로는 가운데를 …로 줄이고 툴팁에 전체 경로(탭 폭을 넓히지 않게)
        row.addWidget(self.folder_label, 1)
        self.folder_btn = QPushButton("변경")
        self.folder_btn.clicked.connect(self.change_folder)
        row.addWidget(self.folder_btn)
        self.save_btn = QPushButton("그림대화로 저장")
        self.save_btn.setStyleSheet(
            f"QPushButton {{ background:{color('accent')}; color:{color('on-accent')}; font-weight:700;"
            " border:none; border-radius:6px; padding:7px 16px; }"
            f"QPushButton:disabled {{ background:palette(mid); color:{color('muted')}; }}")
        self.save_btn.clicked.connect(self.save)
        row.addWidget(self.save_btn)
        g.addLayout(row)
        g.addWidget(hint_label("저장한 그림은 게임의 그림 대화 이미지 보기에 서명 이름으로 나타나요."))
        self.result_label = hint_label("")
        self.result_label.hide()
        g.addWidget(self.result_label)
        v.addWidget(box)
        v.addStretch(1)

        for seq, slot in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                          (QKeySequence.StandardKey.Paste, self.paste)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

        self.set_tool("pen")
        self.set_width(2)
        self.set_slot(0)
        self._on_zoom(self.view.zoom)
        self.refresh_signature()
        self._refresh()

    # --- 상태 ---
    def set_tool(self, key: str) -> None:
        self.tool = key
        self.tool_buttons[key].setChecked(True)
        self.view.update()

    def set_width(self, n: int) -> None:
        self.width_px = n
        self.width_buttons[n].setChecked(True)
        self.view.update()

    def set_slot(self, n: int) -> None:
        self.slot = n
        self._paint_slots()

    def _on_zoom(self, zoom: int) -> None:
        self.zoom_label.setText(f"{WIDTH} × {HEIGHT} · {zoom}배로 크게 보는 중 · 마우스 휠로 확대·축소")
        # 3배 이하는 창 안에 다 보이고, 그보다 크면 가로로 넘겨 본다(높이도 늘린다)
        bar = self.scroll.horizontalScrollBar().sizeHint().height() if zoom > DEFAULT_ZOOM else 0
        self.scroll.setFixedHeight(min(self.view.height(), HEIGHT * 4) + 2 + bar)

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent

        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self.view.set_fit_width(watched.width() - 2)
            self._on_zoom(self.view.zoom)
        return super().eventFilter(watched, event)

    def _paint_slots(self) -> None:
        for i, b in enumerate(self.slot_buttons):
            r, g, bl = self.canvas.palette[i]
            text = "#000000" if (r * 299 + g * 587 + bl * 114) / 1000 > 140 else "#ffffff"
            border = f"2px solid {color('accent')}" if i == self.slot else "1px solid palette(mid)"
            b.setStyleSheet(f"QPushButton {{ background: rgb({r},{g},{bl}); color:{text}; border:{border};"
                            " border-radius:5px; font-weight:700; }")

    def _refresh(self) -> None:
        """캔버스·실제 크기·칸 색·되돌리기 버튼을 다시 그린다."""
        self.view.update()
        self.real_preview.setPixmap(indices_pixmap(self.canvas.pixels, self.canvas.palette))
        self._paint_slots()
        self.undo_btn.setEnabled(self.canvas.can_undo())
        self.redo_btn.setEnabled(self.canvas.can_redo())

    # --- 그리기 입력 ---
    def press(self, p: QPointF) -> None:
        if self.tool == "picker":
            slot = self.canvas.pick((p.x(), p.y()))
            if slot is not None:
                self.set_slot(slot)
                self.set_tool("pen")
            return
        self.canvas.checkpoint()
        if self.tool == "fill":
            self.canvas.fill((p.x(), p.y()), self.slot)
            self.canvas.discard_checkpoint()
            self._refresh()
            return
        self._start = self._last = p
        self._base = self.canvas.pixels.copy()
        self.drag(p)

    def drag(self, p: QPointF) -> None:
        if self._start is None:
            return
        slot = BACKGROUND if self.tool == "eraser" else self.slot
        if self.tool in ("pen", "eraser"):
            self.canvas.stroke((self._last.x(), self._last.y()), (p.x(), p.y()), slot, self.width_px)
            self._last = p
        else:  # 직선·네모: 시작점 기준으로 다시 그리며 미리보기
            self.canvas.pixels[:] = self._base
            draw = self.canvas.line if self.tool == "line" else self.canvas.rect
            draw((self._start.x(), self._start.y()), (p.x(), p.y()), slot, self.width_px)
        self._refresh()

    def release(self, p: QPointF) -> None:
        if self._start is None:
            return
        self.drag(p)
        self._start = self._last = self._base = None
        self.canvas.discard_checkpoint()
        self._refresh()

    # --- 편집 ---
    def undo(self) -> None:
        if self.canvas.undo():
            self._refresh()

    def redo(self) -> None:
        if self.canvas.redo():
            self._refresh()

    def clear(self) -> None:
        self.canvas.checkpoint()
        self.canvas.clear()
        self.canvas.discard_checkpoint()
        self._refresh()

    def edit_slot(self, n: int) -> None:
        from .theme_panel import ColorPickerDialog

        self.set_slot(n)
        r, g, b = self.canvas.palette[n]
        dlg = ColorPickerDialog(f"{n + 1}번 칸 색", QColor(r, g, b).name(), self)
        if dlg.exec() != ColorPickerDialog.DialogCode.Accepted:
            return
        c = QColor(dlg.value())
        self.set_slot_color(n, (c.red(), c.green(), c.blue()))

    def set_slot_color(self, n: int, rgb) -> None:
        self.canvas.checkpoint()
        self.canvas.set_slot_color(n, rgb)
        self.canvas.discard_checkpoint()
        self.palette_combo.setCurrentIndex(self.palette_combo.findData("custom"))
        self._refresh()

    def _on_palette_combo(self, _index: int) -> None:
        self.apply_palette_mode(self.palette_combo.currentData())

    def apply_palette_mode(self, mode: str) -> None:
        """흑백 = 기본 4색(그린 곳은 칸 번호 그대로). 자동·선명 = 마지막에 불러온 그림을 그 방식으로 다시 바꾼다.
        직접 고르기 = 지금 칸의 색 바꾸기 창."""
        if mode == "custom":
            self.edit_slot(self.slot)
            return
        self.canvas.checkpoint()
        if mode == "gray":
            self.canvas.palette = list(GRAY_PALETTE)
        elif self._import is not None:
            s = self._import
            img = convert.adjust(convert.crop_resize(s["rgb"], s["box"]), s["brightness"], s["contrast"])
            indices, palette = convert.convert(img, mode, s["dither"])
            self.canvas.load(indices, palette)
        else:
            self.canvas.discard_checkpoint()
            self.palette_combo.setCurrentIndex(self.palette_combo.findData("gray"))
            self.result_label.setText("자동·선명은 이미지를 불러온 뒤에 쓸 수 있어요.")
            self.result_label.show()
            return
        self.canvas.discard_checkpoint()
        self._refresh()

    # --- 불러오기 ---
    def choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "이미지 불러오기", "",
                                              "이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if path:
            image = QImage(path)
            if not image.isNull():
                self.open_import(image)

    def paste(self) -> None:
        from PySide6.QtWidgets import QApplication

        image = _image_from_mime(QApplication.clipboard().mimeData())
        if image is not None:
            self.open_import(image)

    def open_import(self, image: QImage) -> None:
        dlg = SketchImportDialog(image, self.canvas.palette, self)
        if dlg.exec() != SketchImportDialog.DialogCode.Accepted:
            return
        self.apply_import(dlg)

    def apply_import(self, dlg: SketchImportDialog) -> None:
        self.canvas.checkpoint()
        self.canvas.load(dlg.result_indices, dlg.result_palette)
        self._import = dict(dlg.settings(), rgb=dlg.source_rgb)
        mode = dlg.mode.currentData()
        self.palette_combo.setCurrentIndex(self.palette_combo.findData(mode))
        self._refresh()

    # --- 저장 ---
    def refresh_signature(self) -> None:
        folder = sketch_dir()
        self.folder_label.set_full_text(_display_dir(folder))
        self.signature = read_signature_file(folder / RECENT_NAME)
        if self.signature is None:
            self.signature_label.setText(f"서명  <span style='color:{color('muted')}'>{NO_SIGNATURE}</span>")
        else:
            name = self.signature.author.replace("&", "&amp;").replace("<", "&lt;")
            self.signature_label.setText(
                f"서명  <b>{name}</b> · 마지막에 그린 그림대화(<b>{RECENT_NAME}</b>)에서 가져와요")
        self.save_btn.setEnabled(self.signature is not None)
        self.save_btn.setToolTip("" if self.signature else NO_SIGNATURE)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_signature()  # 게임에서 새로 그렸으면 다시 읽는다

    def change_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "그림대화 저장 위치", str(sketch_dir()))
        if folder:
            config.save_sketch_dir(None if Path(folder) == default_sketch_dir() else folder)
            self.refresh_signature()

    def save(self) -> Path | None:
        self.refresh_signature()
        if self.signature is None:
            return None
        answer = QMessageBox.question(self, "그림대화로 저장", f"이 서명으로 저장해요: {self.signature.author}")
        if answer != QMessageBox.StandardButton.Yes:
            return None
        return self.write_file(datetime.now())

    def write_file(self, when: datetime) -> Path | None:
        folder = sketch_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            name = chat_filename(self.signature.author, when, lambda n: (folder / n).exists())
            target = folder / name
            target.write_bytes(encode_png(self.canvas.pixels, self.canvas.palette, self.signature))
        except OSError as exc:
            self.result_label.setText(f"저장하지 못했어요: {exc}")
            self.result_label.show()
            return None
        self.result_label.setText(f"저장했어요: {name}")
        self.result_label.show()
        return target
