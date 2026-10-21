"""FPS text with a bold white fill and a dark glyph outline."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QFont,QPen,QTextCharFormat,QTextCursor
from .memo_overlay import MemoOverlay


class FrameOverlay(MemoOverlay):
    def set_font_size(self, px):
        super().set_font_size(px)
        self._format_text()

    def set_text(self, text):
        self._markdown=text or ''
        self._edit.setPlainText(self._markdown)
        self._format_text()

    def _format_text(self):
        font=self._edit.font()
        font.setWeight(QFont.Weight.Bold)
        self._edit.setFont(font)
        cursor=QTextCursor(self._edit.document())
        cursor.select(QTextCursor.SelectionType.Document)
        style=QTextCharFormat()
        style.setFontWeight(QFont.Weight.Bold)
        style.setForeground(QColor('white'))
        style.setTextOutline(QPen(QColor('black'),max(.75,font.pixelSize()*.06),
            Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        cursor.mergeCharFormat(style)
        self.autosize()
