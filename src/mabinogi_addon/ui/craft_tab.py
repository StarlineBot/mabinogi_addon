"""제작 재료 계산기(docs/craft-material-calculator-spec.md, 0.50.0 모든 사용자).

왼쪽 시리즈 목록 · 무기/세트 드롭다운 · 제작 방법 · 남은 재료 합계 · 표(재료 | 필요 | 보유 | 남음 | 개당 최저가 | 남은 가격).
- 장비·재료 이름은 데이터 파일(assets/craft/*.json)에서만 온다. 파일의 kind로 모양을 고른다:
  simple(무기 — 재료 × 1), process(세트 — 부위 체크 4개 + 공정 횟수, 표는 '공정 재료'·'마감 재료' 묶음 줄로 나눔, 명세 5절).
- 보유 개수는 재료 이름별 저장(config craftOwned, 무기끼리 공유). 입력하면 바로 다시 계산하되 줄은 움직이지 않는다
  (남은 재료 위·다 모은 재료 아래 정렬은 무기를 바꿀 때·탭에 다시 들어올 때만).
- 시세는 작업 스레드(던전 입장 계산기와 같은 _fetch·_receive 구조 — 작업 스레드는 Qt 객체를 건드리지 않음), 재료별 10분 세션 캐시.
"""
from __future__ import annotations

import queue
import threading
import time
import urllib.request

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSpinBox,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..market import auction, craft
from .calculator_sidebar import calculator_sidebar, refresh_button
from .palette import color
from .widgets import FeatureHeader

TITLE = "제작 재료 계산기"
DESCRIPTION = "장비별 필요 재료를 보고, 가진 개수를 적어 두면 남은 재료와 경매장 가격 합계를 보여 줘요."
REFRESH_TIP = "최저가 기준이에요. 많이 사면 실제 비용은 더 들 수 있어요."
OWNED_NOTE = "보유 개수는 재료별로 저장돼 다른 무기에도 같이 적용돼요."
PROCESS_NOTE = "공정 횟수는 예상치예요. 99%가 되기까지 실제 횟수는 달라질 수 있어요."
NO_PARTS = "만들 부위를 골라 주세요."
PART_SLOTS = 4
NO_KEY = "넥슨 API 키가 없어 시세를 조회할 수 없어요."
LOADING = "시세 조회 중…"
FAILED_ALL = "시세 조회에 실패했어요. 다시 시도해 주세요."
COLUMNS = ["재료", "필요", "보유", "남음", "개당 최저가", "남은 가격"]
BEAD_COLUMNS = ["개당 구슬", "남은 구슬"]  # 두 시리즈 공통(명세 5절 '구슬 열', 사용자 요청 11-16) — 하위 줄에도 표시, 합계는 1단계만
ALL_COLUMNS = COLUMNS + BEAD_COLUMNS
# 좁을 때(글자가 크거나 금액이 길 때) 머리를 두 줄로 — 구슬 머리는 숫자보다 훨씬 넓다(0.51.0, '화면 안 넘치게')
NARROW_COLUMNS = ["재료", "필요", "보유", "남음", "개당\n최저가", "남은\n가격", "개당\n구슬", "남은\n구슬"]
_MATERIAL_MIN = 80  # 재료 칸이 이만큼은 남아야 한 줄 머리
SUB_NOTE = "▸ 표시 재료를 누르면 만드는 데 드는 재료가 펼쳐져요."
_ROLE = Qt.ItemDataRole.UserRole
_OWNED_COL = 2


_INDENT = 14  # 분류 머리 아래 장비 줄 들여쓰기(px)


class _MenuDelegate(QStyledItemDelegate):
    """드롭다운 펼친 목록: 분류 머리는 굵게·흐리게(고를 수 없음), 장비 줄은 들여쓰기. 줄 높이는 글자에 맞춰 넉넉히."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.indent = False

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        if index.data(Qt.ItemDataRole.UserRole) is None:  # 분류 머리
            option.font.setBold(True)
            option.palette.setColor(option.palette.ColorRole.Text, QColor(color("muted")))

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), option.fontMetrics.height() + 10))
        return size

    def paint(self, painter, option, index) -> None:
        if self.indent and index.data(Qt.ItemDataRole.UserRole) is not None:
            option.rect.adjust(_INDENT, 0, 0, 0)
        super().paint(painter, option, index)


class _RowDelegate(QStyledItemDelegate):
    """트리 표 줄 높이 — 보유 숫자 칸이 눌리지 않게(표 QTableWidget 때와 같은 높이)."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), option.fontMetrics.height() + 16))
        return size


def _fetch(result, names, key, cancelled):
    """작업 스레드: 재료 시세 → result 큐에 {재료: 최저가|None(매물 없음)|FAILED}. Qt 객체를 건드리지 않는다."""
    try:
        deadline = time.monotonic() + 30

        def open_page(request, timeout):
            remaining = deadline - time.monotonic()
            if cancelled.is_set() or remaining <= 0:
                raise TimeoutError("market request cancelled or expired")
            return urllib.request.urlopen(request, timeout=min(timeout, remaining))

        prices = auction.fetch_min_prices(names, key, urlopen=open_page, failed=craft.FAILED)
        for name, price in prices.items():
            if price is not None and price != craft.FAILED and (type(price) is not int or price <= 0):
                prices[name] = craft.FAILED
        result.put(prices)
    except Exception:  # noqa: BLE001
        result.put({name: craft.FAILED for name in names})


class CraftTab(QWidget):
    def __init__(self, series: list[craft.Series] | None = None, *, clock=time.monotonic):
        super().__init__()
        self._series = craft.load_series() if series is None else list(series)
        self._cache = craft.PriceCache(clock=clock)
        self._stamp: dict[str, str] = {}  # 재료 → 조회 HH:MM
        self._failed: set[str] = set()  # 이번 세션에 조회 실패한 재료(캐시 안 함)
        self._status_override: str | None = None  # 키 없음·조회 중·전부 실패
        self._pending = None
        self._pending_names: list[str] = []
        self._cancelled = threading.Event()
        self._order: list[tuple[str, str]] = []  # 지금 표의 줄 ("head", 묶음) | ("row", 재료) — 입력 중에는 그대로
        self._spins: dict[str, list[QSpinBox]] = {}
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._receive)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.addWidget(FeatureHeader(TITLE, DESCRIPTION))
        layout = QHBoxLayout()
        root.addLayout(layout, 1)
        self.series_list = calculator_sidebar([s.name for s in self._series])
        layout.addWidget(self.series_list)
        right = QVBoxLayout()
        right.setSpacing(10)
        layout.addLayout(right, 1)

        head = QHBoxLayout()
        self.item_label = QLabel("무기")
        self.item_label.setStyleSheet("font-size:15px;font-weight:800;")
        head.addWidget(self.item_label)
        self.weapon = QComboBox()
        self.weapon.setMinimumContentsLength(8)  # 글자가 커도 가로 넘침 없게(넓으면 늘어남)
        self.weapon.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.weapon.setMaximumWidth(360)
        self._menu_model = QStandardItemModel(self)
        self.weapon.setModel(self._menu_model)
        self._menu_delegate = _MenuDelegate(self.weapon)
        self.weapon.setItemDelegate(self._menu_delegate)
        self.weapon.setMaxVisibleItems(20)  # 분류 머리까지 33줄 — 펼치면 20줄, 나머지는 스크롤
        head.addWidget(self.weapon, 1)
        head.addStretch(0)
        self.refresh = refresh_button(REFRESH_TIP)
        self.refresh.clicked.connect(lambda: self._request(force=True))
        head.addWidget(self.refresh)
        right.addLayout(head)
        # 공정형(세트): 둘째 줄에 부위 체크 4개 + 공정 [7회] — simple 시리즈는 이 줄 없음.
        # 0.50.1(사용자 실화면 11-16): 윗줄 한 줄에 다 넣으면 탭 최소 폭이 창보다 넓어져 새로고침·가격 칸이 잘렸다.
        self.choice_row = QWidget()
        choice = QHBoxLayout(self.choice_row)
        choice.setContentsMargins(0, 0, 0, 0)
        self.part_checks = []
        for _ in range(PART_SLOTS):
            box = QCheckBox()
            box.toggled.connect(self._on_choice)
            choice.addWidget(box)
            self.part_checks.append(box)
        self.process_label = QLabel("공정")
        choice.addSpacing(10)
        choice.addWidget(self.process_label)
        self.processes = QSpinBox()
        self.processes.setRange(craft.PROCESS_MIN, craft.PROCESS_MAX)
        self.processes.setSuffix("회")
        self.processes.valueChanged.connect(self._on_choice)
        choice.addWidget(self.processes)
        choice.addStretch(1)
        right.addWidget(self.choice_row)

        skill_row = QHBoxLayout()
        skill_label = QLabel("제작 방법")
        skill_label.setStyleSheet(f"color:{color('muted')};")
        skill_row.addWidget(skill_label)
        self.skill = QLabel()
        self.skill.setStyleSheet("font-size:17px;font-weight:800;")  # 일반 글자색(민트는 합계만)
        skill_row.addWidget(self.skill)
        skill_row.addStretch(1)
        right.addLayout(skill_row)

        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        right.addWidget(self.summary)
        self.beads = QLabel()  # 구슬 합계(두 시리즈 공통, 1단계 재료 기준 — 명세 5절)
        self.beads.setTextFormat(Qt.TextFormat.RichText)
        right.addWidget(self.beads)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{color('muted')};")
        right.addWidget(self.status)

        # 0.51.0(명세 6절): 트리 표 — 만들 수 있는 재료(▸)를 누르면 하위 재료가 아래로 펼쳐짐(최대 깊이 2)
        self.table = QTreeWidget()
        self.table.setColumnCount(len(ALL_COLUMNS))
        self.table.setHeaderLabels(ALL_COLUMNS)
        self.table.setRootIsDecorated(True)
        self.table.setItemDelegate(_RowDelegate(self.table))
        self.table.setIndentation(14)
        self.table.setExpandsOnDoubleClick(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumWidth(0)
        # 0.50.1: 재료 칸은 남는 폭만 — 숫자 칸이 먼저 자리를 잡고, 긴 재료 이름은 말줄임 + 툴팁
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setWordWrap(False)
        header = self.table.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(ALL_COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
            self.table.headerItem().setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)
        self._narrow = False
        self.table.viewport().installEventFilter(self)
        self.table.itemClicked.connect(self._on_item_clicked)
        self.table.itemExpanded.connect(self._on_expanded)
        self.table.itemCollapsed.connect(self._on_collapsed)
        self._expanded: set[tuple[str, ...]] = set()  # 펼친 줄(재료 경로) — 무기를 바꾸면 비움
        right.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.hide_done = QCheckBox("다 모은 재료 숨기기")
        self.hide_done.setChecked(config.load_craft_hide_done())
        self.hide_done.toggled.connect(self._on_hide_done)
        foot.addWidget(self.hide_done, 0, Qt.AlignmentFlag.AlignTop)
        self.note = QLabel(OWNED_NOTE)
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.note.setStyleSheet(f"color:{color('muted')};")
        foot.addWidget(self.note, 1)
        right.addLayout(foot)

        self.series_list.currentRowChanged.connect(self._on_series)
        self.weapon.currentIndexChanged.connect(self._on_weapon)
        if self._series:
            last_series, _ = config.load_craft_last()  # 마지막으로 본 시리즈·장비를 그대로
            names = [s.name for s in self._series]
            self.series_list.setCurrentRow(names.index(last_series) if last_series in names else 0)

    # ---- 선택 ----
    def current_series(self) -> craft.Series | None:
        row = self.series_list.currentRow()
        return self._series[row] if 0 <= row < len(self._series) else None

    def current_item(self) -> craft.Item | None:
        series = self.current_series()
        i = self.weapon.currentData(Qt.ItemDataRole.UserRole)
        return series.items[i] if series is not None and isinstance(i, int) and 0 <= i < len(series.items) else None

    def select_item(self, name: str) -> bool:
        """장비 이름으로 고르기(분류 머리는 건너뜀)."""
        series = self.current_series()
        for row in range(self._menu_model.rowCount()):
            i = self._menu_model.item(row).data(Qt.ItemDataRole.UserRole)
            if isinstance(i, int) and series.items[i].name == name:
                self.weapon.setCurrentIndex(row)
                return True
        return False

    def _fill_menu(self, series: craft.Series) -> None:
        """드롭다운: 분류가 있으면 고를 수 없는 머리 줄(근접·마법…) + 들여쓴 장비 줄."""
        self._menu_model.clear()
        for text, index in series.menu():
            entry = QStandardItem(text)
            if index is None:
                entry.setFlags(Qt.ItemFlag.NoItemFlags)  # 고를 수 없음 — 키보드 위아래도 건너뜀
                entry.setData(None, Qt.ItemDataRole.UserRole)
            else:
                entry.setData(index, Qt.ItemDataRole.UserRole)
            self._menu_model.appendRow(entry)
        self._menu_delegate.indent = bool(series.categories)

    def is_process(self) -> bool:
        series = self.current_series()
        return series is not None and series.kind == craft.PROCESS

    def _on_series(self, _row: int) -> None:
        series = self.current_series()
        self.weapon.blockSignals(True)
        if series is not None:
            self._fill_menu(series)
            self.item_label.setText(series.item_label)
            _, last_items = config.load_craft_last()
            if not self.select_item(last_items.get(series.name, "")):
                first = next(r for r in range(self._menu_model.rowCount())
                             if self._menu_model.item(r).data(Qt.ItemDataRole.UserRole) is not None)
                self.weapon.setCurrentIndex(first)
        self.weapon.blockSignals(False)
        process = self.is_process()
        self.choice_row.setVisible(process)  # 부위·공정 줄은 공정형만
        self.note.setText(PROCESS_NOTE if process else SUB_NOTE if series is not None and series.crafts else OWNED_NOTE)
        self._expanded.clear()
        self._on_weapon()

    def parts_checked(self) -> list[bool]:
        item = self.current_item()
        return [box.isChecked() for box in self.part_checks[:len(item.parts)]] if item is not None else []

    def _choice(self) -> tuple[int, int]:
        """(체크한 부위 수, 공정 횟수). simple은 (1, 1)."""
        if not self.is_process():
            return 1, 1
        return sum(self.parts_checked()), self.processes.value()

    def _load_choice(self, item: craft.Item) -> None:
        """세트별로 기억한 체크 부위·공정 횟수를 칸에 넣는다(신호는 내보내지 않음)."""
        series = self.current_series()
        checked, processes = config.load_craft_choice(series.name, item.name, len(item.parts), series.default_processes)
        for i, box in enumerate(self.part_checks):
            box.blockSignals(True)
            if i < len(item.parts):
                box.setText(item.parts[i][0])
                box.setToolTip(item.parts[i][1])
                box.setChecked(checked[i])
                box.setVisible(True)
            else:
                box.setVisible(False)
            box.blockSignals(False)
        self.processes.blockSignals(True)
        self.processes.setValue(processes)
        self.processes.blockSignals(False)

    def _on_choice(self, *_):
        item = self.current_item()
        if item is None or not self.is_process():
            return
        config.set_craft_choice(self.current_series().name, item.name, self.parts_checked(), self.processes.value())
        self._resort()  # 필요 수량이 바뀌므로 다시 늘어놓는다(보유 입력 중이 아님)

    def _on_weapon(self, *_):
        item = self.current_item()
        if item is None:
            row = self.weapon.currentIndex()
            nxt = next((r for r in range(row + 1, self._menu_model.rowCount())
                        if self._menu_model.item(r).data(Qt.ItemDataRole.UserRole) is not None), None)
            if row >= 0 and nxt is not None:  # 분류 머리가 골라졌으면(코드에서) 그 아래 첫 장비로
                self.weapon.setCurrentIndex(nxt)
            return
        config.set_craft_last(self.current_series().name, item.name)
        self._expanded.clear()  # 무기를 바꾸면 모두 접힘
        self.skill.setText(item.skill)
        if self.is_process():
            self._load_choice(item)
        self._resort()
        names = item.material_names()
        if self._cache.missing(names):
            self._request(force=False)
        else:
            self._status_override = None
            self._update()

    def showEvent(self, event):  # 탭에 다시 들어오면 남은 재료 위로 다시 정렬
        super().showEvent(event)
        if self.current_item() is not None:
            self._resort()

    def _on_hide_done(self, on: bool) -> None:
        config.set_craft_hide_done(on)
        self._resort()

    # ---- 계산·표 ----
    def _prices_for(self, names) -> dict:
        out = {}
        for material in names:
            hit, value = self._cache.get(material)
            if hit:
                out[material] = value
            elif material in self._failed:
                out[material] = craft.FAILED
        return out

    def _prices(self, item: craft.Item) -> dict:
        return self._prices_for(item.material_names())

    def summary_now(self) -> craft.Summary | None:
        item = self.current_item()
        if item is None:
            return None
        parts, processes = self._choice()
        return craft.compute(item, config.load_craft_owned(), self._prices(item), parts=parts, processes=processes)

    def _group_title(self, group: str) -> str:
        parts, processes = self._choice()
        if group == craft.GROUP_PROCESS:
            return f"공정 재료 · 1공정 수량 × 공정 {processes}회 × {parts}부위"
        if group == craft.GROUP_FINISH:
            return f"마감 재료 · 부위마다 1번 × {parts}부위"
        return ""

    def _span_item(self, parent, kind: str, key, bold: bool = True) -> QTreeWidgetItem:
        """칸 합친 한 줄(묶음 줄·만들기 비교 줄)."""
        entry = QTreeWidgetItem()
        entry.setData(0, _ROLE, (kind, key))
        entry.setFlags(Qt.ItemFlag.ItemIsEnabled)
        font = entry.font(0)
        font.setBold(bold)
        entry.setFont(0, font)
        (parent.addChild if parent is not None else self.table.addTopLevelItem)(entry)
        entry.setFirstColumnSpanned(True)
        return entry

    def _row_item(self, parent, material: str, owned: int, depth: int, path: tuple[str, ...]) -> QTreeWidgetItem:
        entry = QTreeWidgetItem()
        entry.setData(0, _ROLE, ("row", material, depth, path))
        entry.setFlags(Qt.ItemFlag.ItemIsEnabled)
        for col in range(1, len(ALL_COLUMNS)):
            entry.setTextAlignment(col, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        series = self.current_series()
        if series.recipe(material) is not None and depth < craft.MAX_DEPTH:
            entry.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        (parent.addChild if parent is not None else self.table.addTopLevelItem)(entry)
        spin = QSpinBox()
        spin.setRange(0, craft.OWNED_MAX)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        spin.setValue(owned)
        spin.valueChanged.connect(lambda value, m=material, w=spin: self._on_owned(m, value, w))
        self.table.setItemWidget(entry, _OWNED_COL, spin)
        self._spins.setdefault(material, []).append(spin)
        return entry

    def _resort(self) -> None:
        """남은 재료 위·다 모은 재료 아래로 다시 늘어놓고 표를 새로 만든다(장비·부위·공정 변경, 탭 진입, 숨기기 토글 때만).
        공정형은 묶음 줄('공정 재료'·'마감 재료')을 칸 합쳐 넣는다. 펼쳐 둔 재료는 다시 펼친다(무기를 바꿨으면 모두 접힘)."""
        summary = self.summary_now()
        if summary is None:
            return
        rows = [r for r in summary.rows if not (self.hide_done.isChecked() and r.done)]
        layout: list[tuple[str, str]] = []
        group = None
        for r in rows:  # summary.rows는 묶음 순서대로 — 묶음이 바뀌면 묶음 줄
            if r.group and r.group != group:
                layout.append(("head", r.group))
            group = r.group
            layout.append(("row", r.material))
        self._order = layout
        self._spins = {}
        expanded = set(self._expanded)
        self.table.clear()
        by_name = {r.material: r for r in rows}
        for kind, key in layout:
            if kind == "head":
                self._span_item(None, "head", key)
            else:
                self._row_item(None, key, by_name[key].owned, 0, (key,))
        self._expanded = set()
        self._reexpand(expanded)
        self._update()

    def _reexpand(self, paths: set) -> None:
        """경로가 짧은 것부터(부모가 먼저 펼쳐져야 자식 줄이 생김)."""
        for path in sorted(paths, key=len):
            entry = self._find(path)
            if entry is not None:
                entry.setExpanded(True)

    def _find(self, path: tuple[str, ...]) -> QTreeWidgetItem | None:
        items = [self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount())]
        for depth in range(len(path)):
            hit = next((e for e in items if (e.data(0, _ROLE) or ("",))[0] == "row" and e.data(0, _ROLE)[3] == path[:depth + 1]), None)
            if hit is None:
                return None
            if depth == len(path) - 1:
                return hit
            items = [hit.child(i) for i in range(hit.childCount())]
        return None

    def eventFilter(self, obj, event):
        if obj is self.table.viewport() and event.type() == event.Type.Resize:
            self._fit_headers()
        return super().eventFilter(obj, event)

    def _fit_headers(self) -> None:
        """숫자 칸이 다 들어가지 않으면 머리를 두 줄로(재료 칸이 _MATERIAL_MIN 이상 남게). 넓으면 한 줄."""
        header = self.table.header()

        def need(labels) -> int:
            total = 0
            for col in range(1, len(ALL_COLUMNS)):
                if header.isSectionHidden(col):
                    continue
                text_w = max(header.fontMetrics().horizontalAdvance(line) for line in labels[col].split("\n")) + 24
                total += max(text_w, self.table.sizeHintForColumn(col))
            return total + _MATERIAL_MIN + self.table.indentation()

        narrow = need(ALL_COLUMNS) > self.table.viewport().width()
        if narrow != self._narrow:
            self._narrow = narrow
            self.table.setHeaderLabels(NARROW_COLUMNS if narrow else ALL_COLUMNS)
            for col in range(1, len(ALL_COLUMNS)):
                self.table.headerItem().setTextAlignment(col, Qt.AlignmentFlag.AlignCenter)

    def _on_item_clicked(self, entry: QTreeWidgetItem, _col: int) -> None:
        if entry.childIndicatorPolicy() == QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator:
            entry.setExpanded(not entry.isExpanded())  # 줄을 눌러도 펼침/접힘

    def _on_expanded(self, entry: QTreeWidgetItem) -> None:
        data = entry.data(0, _ROLE)
        if not data or data[0] != "row":
            return
        _kind, material, depth, path = data
        self._expanded.add(path)
        if entry.childCount() == 0:  # 처음 펼칠 때 하위 줄을 만든다: 만들기 비교 줄 + 하위 재료
            series = self.current_series()
            self._span_item(entry, "cmp", path)
            owned = config.load_craft_owned()
            for name, _per in series.recipe(material)[1]:
                self._row_item(entry, name, craft.clamp_owned(owned.get(name, 0)), depth + 1, path + (name,))
        self._update()
        names = [n for n, _ in self.current_series().recipe(material)[1] if n not in self.current_series().shop]
        if self._cache.missing(n for n in names if n not in self._failed):
            self._request(force=False)  # 하위 시세는 펼칠 때만

    def _on_collapsed(self, entry: QTreeWidgetItem) -> None:
        data = entry.data(0, _ROLE)
        if data and data[0] == "row":
            self._expanded = {p for p in self._expanded if p[:len(data[3])] != data[3]}

    def _on_owned(self, material: str, value: int, source=None) -> None:
        config.set_craft_owned(material, value)
        for spin in self._spins.get(material, []):  # 같은 재료가 여러 줄(1단계·하위)에 있으면 같이
            if spin is not source and spin.value() != value:
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
        self._update()  # 줄 순서는 그대로

    def _fill_row(self, entry: QTreeWidgetItem, r: craft.Row) -> None:
        muted, accent, warn = QColor(color("muted")), QColor(color("accent")), QColor(color("warn"))
        default = self.table.palette().text().color()
        if r.done:
            price_text, cost_text, price_color = "—", "", muted
        elif r.price == craft.SHOP:
            price_text, cost_text, price_color = "상점", "—", muted
        elif r.price is None:
            price_text, cost_text, price_color = "매물 없음", "—", warn
        elif r.price == craft.FAILED:
            price_text, cost_text, price_color = "조회 실패", "—", warn
        elif r.price == "":
            price_text, cost_text, price_color = "—", "—", default
        else:
            price_text, cost_text, price_color = f"{r.price:,}", auction.korean_gold(r.cost), default
        coin = craft.coin_of(r.material)
        bead_one = str(coin[1]) if coin else ""
        bead_left = f"{r.left * coin[1]:,}" if coin and not r.done else ""
        texts = [r.material, str(r.need), None, "✓" if r.done else str(r.left), price_text, cost_text, bead_one, bead_left]
        for col, text in enumerate(texts):
            if text is None:
                continue
            entry.setText(col, text)
            if col == 0:
                entry.setToolTip(0, text)  # 좁으면 말줄임 — 전체 이름은 툴팁
            if r.done:
                entry.setForeground(col, muted)
            elif col == 4:
                entry.setForeground(col, price_color)
            elif col == 5 and r.cost is not None:
                entry.setForeground(col, accent)
            else:
                entry.setForeground(col, default)
        font = entry.font(7)
        font.setBold(True)
        entry.setFont(7, font)

    def _update_children(self, entry: QTreeWidgetItem, parent_row: craft.Row, owned: dict) -> None:
        series = self.current_series()
        names = [n for n, _ in series.recipe(parent_row.material)[1]]
        children = craft.sub_rows(series, parent_row.material, parent_row.left, owned, self._prices_for(names))
        by_name = {c.material: c for c in children}
        for i in range(entry.childCount()):
            child = entry.child(i)
            data = child.data(0, _ROLE)
            if data[0] == "cmp":
                child.setText(0, self._compare_text(craft.make_compare(series, parent_row, children)))
                child.setForeground(0, QColor(color("accent")))
                font = child.font(0)
                font.setBold(True)
                child.setFont(0, font)
            elif data[0] == "row":
                row = by_name[data[1]]
                self._fill_row(child, row)
                if child.childCount():
                    self._update_children(child, row, owned)

    @staticmethod
    def _compare_text(c: craft.MakeCompare) -> str:
        make = auction.korean_gold(c.make) if c.known else "—"
        buy = auction.korean_gold(c.buy) if c.buy is not None else "—"
        text = f"만들기 · {c.skill} · 직접 만들면 약 {make} (사면 {buy})"
        if c.shop_left_out:
            text += " · 상점 재료 제외"
        if c.no_listing_left_out:
            text += " · 매물 없는 재료 제외"
        return text

    def _update(self) -> None:
        """표 글자·합계·상태만 다시(줄 순서는 _order 그대로). 위쪽 합계는 1단계 재료 기준(펼친 하위는 넣지 않음)."""
        summary = self.summary_now()
        if summary is None:
            return
        by_name = {r.material: r for r in summary.rows}
        owned = config.load_craft_owned()
        muted = QColor(color("muted"))
        for i in range(self.table.topLevelItemCount()):
            entry = self.table.topLevelItem(i)
            data = entry.data(0, _ROLE)
            if data[0] == "head":
                entry.setText(0, self._group_title(data[1]))
                entry.setForeground(0, muted)
                font = entry.font(0)
                font.setBold(True)
                entry.setFont(0, font)
                continue
            r = by_name.get(data[1])
            if r is None:
                continue
            self._fill_row(entry, r)
            if entry.childCount():
                self._update_children(entry, r, owned)
        total = auction.korean_gold(summary.total) if summary.total or self._known(summary) else "—"
        self.refresh.setEnabled(self._pending is None)
        self._fit_headers()
        bead = self._bead_text(summary)
        self.beads.setText(bead)
        self.beads.setVisible(bool(bead))  # 교환표 재료가 하나도 안 남았으면 줄 없음
        if not summary.rows and self.is_process():  # 부위 0개
            self.summary.setText(NO_PARTS)
            self.status.setText(self._status_text(summary))
            return
        self.summary.setText(
            f"남은 재료 {summary.left_kinds}종 · 경매장 최저가 합계 "
            f"<span style='color:{color('accent')};font-size:17px;font-weight:800;'>{total}</span> 골드")
        self.status.setText(self._status_text(summary))

    @staticmethod
    def _bead_text(summary: craft.Summary) -> str:
        """'구슬로 바꾸면 탈라가흐 구슬 N개 · 구슬 교환 재료 K종 기준'(교환표에 없는 재료는 표시 없이 제외)."""
        totals, kinds = craft.bead_total(summary)
        if not kinds:
            return ""
        parts = " · ".join(f"{region} 구슬 <span style='font-size:16px;font-weight:800;'>{n:,}개</span>"
                           for region, n in totals.items())
        return f"구슬로 바꾸면 {parts} <span style='color:{color('muted')};'>· 구슬 교환 재료 {kinds}종 기준</span>"

    @staticmethod
    def _known(summary: craft.Summary) -> bool:
        return any(r.cost is not None for r in summary.rows if not r.done)

    def _status_text(self, summary: craft.Summary) -> str:
        if self._status_override:
            return self._status_override
        item = self.current_item()
        stamps = sorted(self._stamp[m] for m in item.material_names() if m in self._stamp)
        if not stamps:
            return ""
        text = f"조회 {stamps[0]} · 경매 시세는 약 10분 지연돼요."
        if summary.no_listing:
            text += f" 매물 없는 재료 {summary.no_listing}종은 합계에서 빠졌어요."
        if summary.failed:
            text += f" 조회에 실패한 재료 {summary.failed}종은 합계에서 빠졌어요."
        return text

    # ---- 시세 ----
    def _wanted(self) -> list[str]:
        """조회할 재료: 장비 재료 전부 + 펼친 줄의 하위 재료(상점 재료 제외)."""
        item = self.current_item()
        series = self.current_series()
        names = list(item.material_names()) if item is not None else []
        for path in sorted(self._expanded, key=len):
            recipe = series.recipe(path[-1])
            if recipe is not None:
                names += [n for n, _ in recipe[1] if n not in series.shop]
        return list(dict.fromkeys(names))

    def _request(self, *, force: bool) -> None:
        if self._cancelled.is_set():
            return
        item = self.current_item()
        if item is None:
            return
        if self._pending is not None:  # 조회 중: 끝나면 _receive가 지금 빠진 것을 다시 조회
            self._status_override = LOADING
            self._update()
            return
        names = self._wanted()
        if force:
            self._cache.drop(names)
        else:
            names = self._cache.missing(names)
        if not names:
            return
        key = config.get_nexon_api_key()
        if not key:
            self._status_override = NO_KEY
            self._update()
            return
        self._failed.difference_update(names)
        self._status_override = LOADING
        self._pending = queue.Queue(maxsize=1)
        self._pending_names = names
        threading.Thread(target=_fetch, args=(self._pending, names, key, self._cancelled), daemon=True).start()
        self._poll.start()
        self._update()

    def _receive(self) -> None:
        if self._cancelled.is_set() or self._pending is None:
            return
        try:
            prices = self._pending.get_nowait()
        except queue.Empty:
            return
        self._pending = None
        self._poll.stop()
        stamp = time.strftime("%H:%M")
        for name in self._pending_names:
            value = prices.get(name, craft.FAILED)
            if value == craft.FAILED:
                self._failed.add(name)
                continue
            self._cache.put(name, value)
            self._stamp[name] = stamp
        all_failed = bool(self._pending_names) and all(prices.get(n, craft.FAILED) == craft.FAILED for n in self._pending_names)
        self._status_override = FAILED_ALL if all_failed else None
        if self.current_item() is not None and self._cache.missing(m for m in self._wanted() if m not in self._failed):
            self._request(force=False)  # 조회 중에 무기를 바꾸거나 펼쳤으면 이어서
            return
        self._update()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        self._cancelled.set()
        self._poll.stop()
        self._pending = None
