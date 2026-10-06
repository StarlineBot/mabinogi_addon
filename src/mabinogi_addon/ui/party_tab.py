"""파티 탭 (기획서 3.5).

넥슨 거뿔 API를 폴링해 파티모집현황을 리스트로 보여주고, 키워드 매칭 시 토스트.
키워드·파티장 제외 목록은 config.local.json에 저장된다.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..party.models import Recruit
from ..party.service import build_board, humanize_age
from ..party.worker import PartyWorker
from .notifier import PARTY_ALERT_FILE, SoundNotifier
from .toast import show_toast
from .widgets import hint_label

_DIM = QColor("#9aa0a6")
_ACCENT = QColor("#00D1A7")  # 키워드 매칭 강조색(왼쪽 바)
_MATCH_BG = QColor("#17352f")  # 매칭 행 배경 띠(어두운 초록 틴트)
_BAR_WIDTH = 4  # 왼쪽 강조 바 두께(px)


class _AccentBarDelegate(QStyledItemDelegate):
    """매칭 행 왼쪽 가장자리에 세로 바를 그린다. 셀(칸)이 아니라 그림이라
    별도 칸·마우스 오버 강조가 생기지 않는다. 테이블 전체 오버 강조도 끈다."""

    def __init__(self, is_matched, parent=None) -> None:
        super().__init__(parent)
        self._is_matched = is_matched  # callable(row) -> bool

    def paint(self, painter, option, index) -> None:
        option.state &= ~QStyle.StateFlag.State_MouseOver  # 오버 강조 제거
        super().paint(painter, option, index)
        if index.column() == 0 and self._is_matched(index.row()):
            painter.save()
            r = option.rect
            painter.fillRect(r.left(), r.top(), _BAR_WIDTH, r.height(), _ACCENT)
            painter.restore()


class _ChipRow(QWidget):
    """목록 한 줄: 텍스트 + (마우스 올리면 나타나는) 오른쪽 X 삭제 버튼."""

    deleted = Signal(str)

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 1, 4, 1)
        row.addWidget(QLabel(text), 1)

        self._x = QPushButton("✕")
        self._x.setFixedSize(18, 18)
        self._x.setFlat(True)
        self._x.setCursor(Qt.CursorShape.PointingHandCursor)
        self._x.setToolTip("삭제")
        self._x.setStyleSheet("QPushButton{border:none;color:#e06c75;}")
        self._x.clicked.connect(lambda: self.deleted.emit(self._text))
        self._x.setVisible(False)  # 평소 숨김, 호버/선택 시 표시
        row.addWidget(self._x)

    def set_x_visible(self, visible: bool) -> None:
        self._x.setVisible(visible)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        self._x.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        # 선택된 항목은 계속 X 유지(아래 _sync_x에서 관리)
        if not self.property("selected"):
            self._x.setVisible(False)
        super().leaveEvent(event)


class PartyTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._keywords, self._excludes = config.load_party_lists()
        self._worker: PartyWorker | None = None
        self._last_raw: list[dict] = []  # 마지막 거뿔 원본(즉시 재필터용)
        self._sound = SoundNotifier({"party": PARTY_ALERT_FILE})

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._build_board(), 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addWidget(self._build_keywords())
        bottom.addWidget(self._build_excludes())
        root.addLayout(bottom)

    # ---- 현황판 ----
    def _build_board(self) -> QGroupBox:
        box = QGroupBox("파티모집현황 (하프 서버)")
        v = QVBoxLayout(box)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["채널", "파티장", "제목", "인원", "시간"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        # 매칭 행 왼쪽 세로 바는 셀이 아니라 델리게이트로 직접 그린다(칸 아님 → 오버 강조 없음)
        self._matched_rows: set[int] = set()
        self.table.setItemDelegate(_AccentBarDelegate(lambda r: r in self._matched_rows, self.table))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setToolTip("파티장을 클릭하면 제외할 수 있어요")
        self.table.cellClicked.connect(self._on_cell_clicked)
        v.addWidget(self.table)

        self.status_label = hint_label("대기 중 · 탐지 시작 시 5초마다 갱신")
        v.addWidget(self.status_label)
        return box

    def _on_updated(self, raw: list[dict]) -> None:
        """워커가 준 원본을 캐시하고 현재 제외 목록으로 리스트를 그린다."""
        self._last_raw = raw
        self._refresh_board()

    def _refresh_board(self) -> None:
        """캐시된 원본으로 즉시 재필터·재표시(제외 목록 변경 시 바로 반영)."""
        self._populate(build_board(self._last_raw, self._excludes))

    def _on_cell_clicked(self, row: int, _col: int) -> None:
        """리스트의 파티장을 클릭 → 제외 확인 팝업."""
        leader_item = self.table.item(row, 1)  # 1 = 파티장 열(0=채널)
        if leader_item is None:
            return
        name = leader_item.text()
        if name in self._excludes:
            return
        # Qt 기본 버튼은 영어라 '예/아니오'로 직접 지정
        box = QMessageBox(self)
        box.setWindowTitle("파티장 제외")
        box.setText(
            f"'{name}'\n\n이 파티장을 제외하시겠습니까?\n"
            "이 파티장의 모집은 현황·알림에서 숨겨집니다."
        )
        yes = box.addButton("예", QMessageBox.ButtonRole.YesRole)
        no = box.addButton("아니오", QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(no)
        box.exec()
        if box.clickedButton() is yes:
            self._excludes.append(name)
            self._refresh_exclude_list()
            self._save()
            self._refresh_board()

    def _populate(self, recruits: list[Recruit]) -> None:
        self.table.setRowCount(0)
        self._matched_rows.clear()
        for recruit in recruits:
            row = self.table.rowCount()
            self.table.insertRow(row)

            matched = self._matches_keyword(recruit.content)
            if matched:
                self._matched_rows.add(row)  # 왼쪽 바는 델리게이트가 그린다

            channel = QTableWidgetItem(f"채널 {recruit.channel}")
            leader = QTableWidgetItem(recruit.character_name)
            title = QTableWidgetItem(("✅ " if recruit.done else "") + recruit.content)
            count = QTableWidgetItem(recruit.headcount)
            count.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            age = QTableWidgetItem(humanize_age(recruit.date_send))
            age.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            age.setForeground(QBrush(_DIM))  # 시각은 항상 흐리게(보조 정보)

            items = [channel, leader, title, count, age]
            for col, item in enumerate(items):
                if matched:
                    item.setBackground(QBrush(_MATCH_BG))  # 행 전체 밝은 띠
                    if col == 2:  # 제목 굵게
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                elif recruit.done:
                    item.setForeground(QBrush(_DIM))  # 완료 파티 흐리게
                self.table.setItem(row, col, item)

    def _matches_keyword(self, content: str) -> bool:
        return any(kw in content for kw in self._keywords)

    # ---- 목록 공통 (칩 행 + Ctrl/Shift 다중선택) ----
    def _make_chip_list(self) -> QListWidget:
        lst = QListWidget()
        lst.setMaximumHeight(110)
        # Ctrl=개별 토글, Shift=범위 선택(표준 동작)
        lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lst.itemSelectionChanged.connect(lambda target=lst: self._sync_x(target))
        return lst

    def _fill_chip_list(self, lst: QListWidget, items, on_delete) -> None:
        lst.clear()
        for text in items:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, text)
            row = _ChipRow(text)
            row.deleted.connect(on_delete)
            item.setSizeHint(row.sizeHint())
            lst.addItem(item)
            lst.setItemWidget(item, row)

    def _sync_x(self, lst: QListWidget) -> None:
        # 선택된 항목은 X를 계속 보이게(호버 외에도)
        for i in range(lst.count()):
            item = lst.item(i)
            row = lst.itemWidget(item)
            if isinstance(row, _ChipRow):
                row.setProperty("selected", item.isSelected())
                row.set_x_visible(item.isSelected())

    # ---- 키워드 ----
    def _build_keywords(self) -> QGroupBox:
        # 제목을 라벨로 만들어 그 '바로 옆'에 종 아이콘 토글을 둔다(테두리 제목 대신).
        box = QGroupBox("")
        v = QVBoxLayout(box)

        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        self._alert_sound = config.load_party_alert_sound()
        self.alert_bell = QPushButton()
        self.alert_bell.setFlat(True)
        self.alert_bell.setFixedSize(24, 22)
        self.alert_bell.setStyleSheet("QPushButton { font-size:15px; border:none; }")
        self.alert_bell.setToolTip("키워드 알림 효과음 켜기/끄기")
        self.alert_bell.clicked.connect(self._toggle_alert_sound)
        self._update_bell()
        title_row.addWidget(self.alert_bell)  # 타이틀 '앞'(왼쪽)에 종
        title = QLabel("키워드 알림")
        title.setStyleSheet("font-weight:600;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        v.addLayout(title_row)

        add_row = QHBoxLayout()
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("제목에 포함될 단어 (예: 브리, 글렌)")
        self.keyword_input.returnPressed.connect(self._add_keyword)
        add_button = QPushButton("등록")
        add_button.clicked.connect(self._add_keyword)
        add_row.addWidget(self.keyword_input, 1)
        add_row.addWidget(add_button)
        v.addLayout(add_row)

        self.keyword_list = self._make_chip_list()
        self._refresh_keyword_list()
        v.addWidget(self.keyword_list)

        remove_button = QPushButton("선택 삭제")
        remove_button.clicked.connect(self._remove_selected_keywords)
        btn_row = QHBoxLayout()
        btn_row.addWidget(remove_button)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        v.addWidget(
            hint_label(
                "키워드가 뜨면 화면 우측 하단에 토스트 + 효과음(트레이·게임 중에도) · 항목 위 X로 삭제\n"
                "위 종 아이콘(🔔/🔕)으로 효과음을 켜고 끌 수 있습니다."
            )
        )
        return box

    def _update_bell(self) -> None:
        self.alert_bell.setText("🔔" if self._alert_sound else "🔕")

    def _toggle_alert_sound(self) -> None:
        self._alert_sound = not self._alert_sound
        config.save_party_alert_sound(self._alert_sound)
        self._update_bell()
        state = "켜짐 🔔" if self._alert_sound else "꺼짐 🔕"
        show_toast("키워드 알림 효과음", state)

    def _refresh_keyword_list(self) -> None:
        self._fill_chip_list(self.keyword_list, self._keywords, self._delete_keyword)

    def _add_keyword(self) -> None:
        text = self.keyword_input.text().strip()
        self.keyword_input.clear()
        if not text or text in self._keywords:
            return
        self._keywords.append(text)
        self._refresh_keyword_list()
        self._save()

    def _delete_keyword(self, text: str) -> None:
        if text in self._keywords:
            self._keywords.remove(text)
            self._refresh_keyword_list()
            self._save()

    def _remove_selected_keywords(self) -> None:
        selected = {
            i.data(Qt.ItemDataRole.UserRole) for i in self.keyword_list.selectedItems()
        }
        if not selected:
            return
        self._keywords = [k for k in self._keywords if k not in selected]
        self._refresh_keyword_list()
        self._save()

    # ---- 파티장 제외 ----
    def _build_excludes(self) -> QGroupBox:
        box = QGroupBox("파티장 제외")
        v = QVBoxLayout(box)

        add_row = QHBoxLayout()
        self.exclude_input = QLineEdit()
        self.exclude_input.setPlaceholderText("제외할 파티장 캐릭터명")
        self.exclude_input.returnPressed.connect(self._add_exclude)
        add_button = QPushButton("등록")
        add_button.clicked.connect(self._add_exclude)
        add_row.addWidget(self.exclude_input, 1)
        add_row.addWidget(add_button)
        v.addLayout(add_row)

        self.exclude_list = self._make_chip_list()
        self._refresh_exclude_list()
        v.addWidget(self.exclude_list)

        remove_button = QPushButton("선택 삭제")
        remove_button.clicked.connect(self._remove_selected_excludes)
        btn_row = QHBoxLayout()
        btn_row.addWidget(remove_button)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        v.addWidget(hint_label("이 파티장의 모집은 현황·알림에서 숨깁니다 · 항목 위 X로 삭제"))
        return box

    def _refresh_exclude_list(self) -> None:
        self._fill_chip_list(self.exclude_list, self._excludes, self._delete_exclude)

    def _add_exclude(self) -> None:
        text = self.exclude_input.text().strip()
        self.exclude_input.clear()
        if not text or text in self._excludes:
            return
        self._excludes.append(text)
        self._refresh_exclude_list()
        self._save()
        self._refresh_board()  # 즉시 반영

    def _delete_exclude(self, text: str) -> None:
        if text in self._excludes:
            self._excludes.remove(text)
            self._refresh_exclude_list()
            self._save()
            self._refresh_board()

    def _remove_selected_excludes(self) -> None:
        selected = {
            i.data(Qt.ItemDataRole.UserRole) for i in self.exclude_list.selectedItems()
        }
        if not selected:
            return
        self._excludes = [e for e in self._excludes if e not in selected]
        self._refresh_exclude_list()
        self._save()
        self._refresh_board()  # 즉시 반영(제외 풀면 다시 나타남)

    def _save(self) -> None:
        config.save_party_lists(self._keywords, self._excludes)

    # ---- 폴링 ----
    def start_polling(self) -> None:
        if self._worker is not None:
            return
        self._worker = PartyWorker(
            get_api_key=config.get_nexon_api_key,
            get_keywords=lambda: list(self._keywords),
            get_excludes=lambda: list(self._excludes),
        )
        self._worker.updated.connect(self._on_updated)
        self._worker.alerted.connect(self._on_alert)
        self._worker.status.connect(self._on_status)
        self._worker.start()

    def stop_polling(self, wait_ms: int = 2000) -> None:
        if self._worker is None:
            return
        self._worker.stop()
        # HTTP 요청 중이면 그 요청이 끝나야 깬다 → 종료 시엔 짧게만 기다리고 넘어간다
        # (못 깨면 참조를 유지해 스레드가 요청을 마치고 스스로 종료하게 둔다).
        if self._worker.wait(wait_ms):
            self._worker = None

    def _on_alert(self, keyword: str, recruit: Recruit) -> None:
        meta = " · ".join(
            part
            for part in (
                recruit.character_name,
                f"채널 {recruit.channel}",
                recruit.headcount,
                humanize_age(recruit.date_send),
            )
            if part
        )
        show_toast(f"🔔 파티모집 · '{keyword}'", f"{recruit.content}\n{meta}")
        # 효과음: 파일 있으면 재생, 없으면 시스템 비프로 폴백(토스트와 함께 항상 알림).
        if self._alert_sound and not self._sound.play("party"):
            QApplication.beep()

    def _on_status(self, text: str) -> None:
        self.status_label.setText(text or "실행 중 · 5초마다 갱신")
