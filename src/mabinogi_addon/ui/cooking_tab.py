"""요리 계산기 탭(편의기능 › 계산기, docs/cooking-spec.md 3·5·6절).

[검색 종류 ▼] [검색어] [N개 요리] / [카테고리 16] [요리 목록(이름만)] [상세]
- 검색 = 필터: 카테고리 옆 맞는 수, 0개 카테고리·안 맞는 요리는 회색·선택 불가, 상세에서 검색한 재료/능력치 줄 강조.
  검색어를 지우면 숫자·회색만 사라지고 선택은 그대로.
- 재료가 요리면 ▸ + 강조색, 누르면 그 요리로(카테고리·목록·상세·게임 위 바), `← 바로 앞 요리`로 들어간 순서를 거꾸로.
- 상세 비율 그림(요리창 + 게이지 + 경계 점선)과 `게임 위에 이 바 띄우기`(끌어서 맞추기·휠 크기·잠금, 위치·배율 저장).

런타임: 데이터는 앱 자산 JSON(네트워크 없음). 게임 위 바를 켠 동안만 0.5초 타이머로 게임 활성 여부를 보고 숨김/표시.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QFontInfo, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from .. import config, cooking
from .cooking_gauge import CookingBarOverlay, color, detail_pixmap
from .palette import color as pcolor
from .widgets import FeatureHeader, divider

TITLE = "요리"
# 글자 위계(사용자 피드백 11-19): 본문 글꼴 기준 +px — 타이틀 > 조리방법·능력치 > 본문. 큰 글꼴에서도 위계 유지(스타일시트 px 고정 안 씀)
TITLE_UP, SUB_UP, SECTION_UP = 4, 2, 1  # 기본 13px → 17·15·14
GAUGE_VIEW_W = 400  # 상세 요리창 그림 표시 너비(원본 패널 530px을 줄여 상세 칸에 맞춤 — 시안 detail_gauge_mock.png)
DESCRIPTION = "요리를 찾아 재료·비율·능력치를 보고, 비율 바를 게임 위에 띄워 요리창 바에 맞출 수 있어요."
_DISH = Qt.ItemDataRole.UserRole
_VALUE = Qt.ItemDataRole.UserRole + 1  # 능력치 검색 때 줄 오른쪽에 그릴 수치('+300')


class _ValueDelegate(QStyledItemDelegate):
    """능력치 수치를 줄 오른쪽에 따로 그린다 — 요리 이름이 길어 잘려도 수치는 늘 보이게(이름만 말줄임).

    글자 색은 델리게이트가 고르지 않고 스타일이 그린다(0.54.0 QA 반려: Windows 11 스타일은 선택 줄을 옅은 칸 + Text 글자로
    그려, HighlightedText로 직접 칠한 글자가 묻혔다). 이름 = drawControl 한 번(배경·선택·이름), 수치 = 수치 칸에만 잘라
    같은 옵션으로 drawControl 한 번 더(같은 배경이라 겉보기 같음)."""

    def paint(self, painter, option, index) -> None:
        value = index.data(_VALUE)
        if not value:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        rect = QRect(opt.rect)
        if widget is not None and hasattr(widget, "viewport"):  # 줄 너비가 보이는 칸보다 넓어도 수치는 보이는 오른쪽 끝에
            rect.setRight(min(rect.right(), widget.viewport().width() - 1))
        opt.rect = rect
        fm = opt.fontMetrics
        value_w = fm.horizontalAdvance(value) + 12
        name_w = max(0, rect.width() - value_w - 12)
        name = fm.elidedText(opt.text, Qt.TextElideMode.ElideRight, name_w)
        opt.text = name
        opt.textElideMode = Qt.TextElideMode.ElideNone
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)   # 배경·선택·이름
        number = QStyleOptionViewItem(opt)
        number.text = value
        number.displayAlignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        painter.save()
        painter.setClipRect(QRect(rect.right() - value_w, rect.top(), value_w + 1, rect.height()))
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, number, painter, widget)  # 수치(스타일 글자색)
        painter.restore()


class CookingTab(QWidget):
    def __init__(self, watcher=None, dishes=None) -> None:
        super().__init__()
        self._watcher = watcher
        self._dishes = tuple(dishes) if dishes is not None else cooking.load()
        self._by_name = {d.name: d for d in self._dishes}
        self._index = cooking.dish_index(self._dishes)
        self._hits: set[str] | None = None
        self._category: str | None = None
        self._selected: cooking.Dish | None = None
        self.history = cooking.History()
        self.overlay: CookingBarOverlay | None = None
        self._overlay_on = False

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.addWidget(FeatureHeader(TITLE, DESCRIPTION))

        # 검색 줄
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(cooking.SEARCH_KINDS)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        row.addWidget(self.kind)
        self.query_stack = QStackedWidget()
        self.query = QLineEdit()
        self.query.setPlaceholderText("요리 이름으로 찾기")
        self.query.setClearButtonEnabled(True)
        self.query.textChanged.connect(self._search)
        self.stat = QComboBox()
        self.stat.addItem("능력치 고르기", "")
        for name in cooking.stat_names(self._dishes):
            self.stat.addItem(name, name)
        self.stat.currentIndexChanged.connect(self._search)
        self.query_stack.addWidget(self.query)
        self.query_stack.addWidget(self.stat)
        self.query_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.query_stack.setFixedHeight(self.query.sizeHint().height())
        row.addWidget(self.query_stack, 1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{pcolor('muted')};")
        row.addWidget(self.count)
        v.addLayout(row)

        # 카테고리 · 요리 목록 · 상세
        body = QHBoxLayout()
        self.category_list = QListWidget()
        self.category_list.setFixedWidth(130)
        self.favorites = cooking.normalize_favorites(config.load_cooking_favorites(), self._dishes)
        fav_item = QListWidgetItem(cooking.FAVORITES)  # 맨 위 가상 카테고리(사용자 결정 11-21)
        fav_item.setData(_DISH, cooking.FAVORITES)
        self.category_list.addItem(fav_item)
        for name in cooking.categories(self._dishes):
            item = QListWidgetItem(name)
            item.setData(_DISH, name)
            self.category_list.addItem(item)
        self.category_list.currentItemChanged.connect(self._category_changed)
        body.addWidget(self.category_list)
        self.dish_list = QListWidget()
        self.dish_list.setFixedWidth(170)
        self.dish_list.setItemDelegate(_ValueDelegate(self.dish_list))
        self.dish_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # 긴 이름은 말줄임(가로 스크롤 없음)
        self.dish_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.dish_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)  # 오른쪽 클릭 = 즐겨찾기 넣기·빼기
        self.dish_list.customContextMenuRequested.connect(self._dish_menu)
        self.dish_list.itemClicked.connect(self._dish_clicked)
        body.addWidget(self.dish_list)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self.detail = QWidget()
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(14, 12, 14, 12)
        self.detail_layout.setSpacing(8)
        self.detail_scroll.setWidget(self.detail)
        body.addWidget(self.detail_scroll, 1)
        v.addLayout(body, 1)

        self._timer = QTimer(self)  # 게임 위 바를 켠 동안만
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._sync_overlay)
        # 요리창 자동 찾기(명세 7절, 0.54.0): 바를 켠 동안 + 게임이 앞일 때만 1초마다
        from .cooking_autofind import CookingAutoFind
        self.autofind = CookingAutoFind()
        self.auto_state = "manual"  # manual(손으로 맞추기) · found(찾은 자리) · closed(요리창 꺼짐 → 숨김)
        self._find_timer = QTimer(self)
        self._find_timer.setInterval(1000)
        self._find_timer.timeout.connect(self._auto_tick)
        self._refresh_lists()
        self._render_detail()
        self._restore_last()

    def _restore_last(self) -> None:
        """지난 실행의 고른 요리·'게임 위에 이 바 띄우기' 켬 상태(사용자 보고 11-21). 요리가 데이터에 없으면 바도 안 켬."""
        try:
            name, on = config.load_cooking_last_dish(), config.load_cooking_overlay_on()
        except OSError:
            return
        if name not in self._by_name:
            return
        self.select(name)
        if on:
            self.set_overlay(True)
            self._render_detail()  # 버튼 체크 상태 맞춤

    # ---- 검색 ----
    def _kind_changed(self) -> None:
        stat = self.kind.currentText() == "능력치"
        self.query_stack.setCurrentWidget(self.stat if stat else self.query)
        self.query.setPlaceholderText(f"{self.kind.currentText()}으로 찾기" if self.kind.currentText() == "재료"
                                      else "요리 이름으로 찾기")
        self._search()

    def query_text(self) -> str:
        if self.kind.currentText() == "능력치":
            return self.stat.currentData() or ""
        return self.query.text()

    def _search(self, *_args) -> None:
        self._hits = cooking.search(self._dishes, self.kind.currentText(), self.query_text())
        self._refresh_lists()
        self._render_detail()  # 검색한 재료·능력치 줄 강조

    def _stat_query(self) -> str:
        """능력치 검색 중이면 그 능력치 이름, 아니면 ''."""
        return self.query_text() if self.kind.currentText() == "능력치" else ""

    def _refresh_lists(self) -> None:
        counts = cooking.category_counts(self._dishes, self._hits)
        searching = self._hits is not None
        stat = self._stat_query()
        # 능력치 검색: 전체 요리 중 최고값 요리(동점 모두)와 그 카테고리에만 ★(사용자 결정 11-21)
        self._stars = cooking.top_dishes(self._dishes, stat) if stat else set()
        star_methods = {self._by_name[n].method for n in self._stars}
        self.count.setText(f"{len(self._hits)}개 요리" if searching else f"{len(self._dishes)}개 요리")
        muted = QBrush(QColor(pcolor("muted")))
        if self._stars & set(self.favorites):
            star_methods.add(cooking.FAVORITES)
        for i in range(self.category_list.count()):
            item = self.category_list.item(i)
            name = item.data(_DISH)
            if name == cooking.FAVORITES:
                n = cooking.favorites_count(self.favorites, self._hits)
                text = f"{name} ({n})" if searching or not self.favorites else name
                item.setToolTip("" if self.favorites else "요리를 오른쪽 클릭해 추가")
            else:
                n = counts.get(name, 0)
                text = f"{name} ({n})" if searching else name
            item.setText(f"★ {text}" if name in star_methods else text)
            enabled = n > 0
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if enabled else Qt.ItemFlag.NoItemFlags)
            item.setForeground(QBrush() if enabled else muted)
        self._fill_dishes()

    def _fill_dishes(self) -> None:
        """요리 목록 다시 채우기 — 같은 카테고리면 스크롤 자리 그대로(검색 회색 갱신 등), 고른 요리가 화면 밖이면 가운데로.
        (0.53.2: 내린 목록에서 누를 때마다 다시 채워 스크롤이 0이 되고 누른 줄이 아래로 튀던 문제)"""
        bar = self.dish_list.verticalScrollBar()
        stat = self._stat_query()
        # 같은 카테고리·같은 검색일 때만 스크롤 유지(검색이 바뀌면 순서가 바뀌므로 맨 위로)
        query = (self.kind.currentText(), cooking.norm(self.query_text()))
        same = (self._category is not None and self._category == getattr(self, "_filled_category", None)
                and query == getattr(self, "_filled_query", None))
        scroll = bar.value()
        current = None
        self.dish_list.blockSignals(True)
        self.dish_list.clear()
        muted = QBrush(QColor(pcolor("muted")))
        if self._category is not None:
            dishes = self._category_dishes(self._category)
            if stat:
                rows = cooking.ranked(dishes, stat)
            elif self._hits is not None:  # 이름·재료 검색: 맞는 요리 위(이름순), 안 맞는 요리 회색 아래(사용자 결정 11-21)
                rows = ([(d, None) for d in dishes if d.name in self._hits]
                        + [(d, None) for d in dishes if d.name not in self._hits])
            else:
                rows = [(d, None) for d in dishes]
            stars = getattr(self, "_stars", set())
            for dish, value in rows:
                # 능력치 검색: 수치 높은 순, 수치는 줄 오른쪽(_ValueDelegate). 앞 표시: 최고 ★, 즐겨찾기 ♥ — 글자로(색은 스타일이)
                mark = ("★" if dish.name in stars else "") + ("♥" if dish.name in self.favorites else "")
                item = QListWidgetItem(f"{mark} {dish.name}" if mark else dish.name)
                if value is not None:
                    item.setData(_VALUE, f"{value:+g}")
                item.setData(_DISH, dish.name)
                hit = self._hits is None or dish.name in self._hits
                if not hit:
                    item.setFlags(Qt.ItemFlag.NoItemFlags)  # 회색·선택 불가(지금 고른 요리여도 선택은 그대로 둠)
                    item.setForeground(muted)
                self.dish_list.addItem(item)
                if self._selected is not None and dish.name == self._selected.name and hit:
                    current = item
        if current is not None:
            current.setSelected(True)
            self.dish_list.setCurrentItem(current)
        self.dish_list.blockSignals(False)
        self._filled_category = self._category
        self._filled_query = query
        bar.setValue(scroll if same else 0)
        if current is not None:
            self._center_if_hidden(current)

    def _category_dishes(self, category: str) -> list:
        if category == cooking.FAVORITES:
            return cooking.favorite_dishes(self._dishes, self.favorites)
        return cooking.in_category(self._dishes, category)

    # ---- 즐겨찾기(사용자 결정 11-21) ----
    def is_favorite(self, name: str) -> bool:
        return name in self.favorites

    def toggle_favorite(self, name: str) -> None:
        """추가·빼기 → 저장 → 목록·카테고리 다시(같은 카테고리·검색이면 스크롤 유지)."""
        if name not in self._by_name:
            return
        if name in self.favorites:
            self.favorites.remove(name)
        else:
            self.favorites.append(name)
        try:
            config.save_cooking_favorites(self.favorites)
        except OSError:
            pass
        self._refresh_lists()

    def _favorite_menu(self, name: str) -> QMenu:
        menu = QMenu(self.dish_list)
        action = menu.addAction("즐겨찾기에서 빼기" if self.is_favorite(name) else "즐겨찾기에 추가")
        action.triggered.connect(lambda _=False, n=name: self.toggle_favorite(n))
        return menu

    def _dish_menu(self, pos) -> None:
        """요리 목록 오른쪽 클릭 — 회색(검색에 안 맞는) 줄도 넣기·빼기 가능."""
        item = self.dish_list.itemAt(pos)
        if item is None or item.data(_DISH) not in self._by_name:
            return
        self.menu = self._favorite_menu(item.data(_DISH))
        self._exec_menu(self.menu, self.dish_list.viewport().mapToGlobal(pos))

    def _exec_menu(self, menu: QMenu, global_pos) -> None:
        menu.exec(global_pos)

    def _center_if_hidden(self, item) -> None:
        rect = self.dish_list.visualItemRect(item)
        if rect.top() < 0 or rect.bottom() > self.dish_list.viewport().height():  # 세로로만 본다(가로 넘침 무관)
            self.dish_list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _mark_selected(self) -> None:
        """같은 카테고리 안 선택 — 목록을 다시 만들지 않고 표시만(스크롤 그대로, 화면 밖이면 가운데로)."""
        bar = self.dish_list.verticalScrollBar()
        scroll = bar.value()
        self.dish_list.blockSignals(True)
        target = None
        for i in range(self.dish_list.count()):
            item = self.dish_list.item(i)
            if self._selected is not None and item.data(_DISH) == self._selected.name and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                target = item
        if target is not None:
            self.dish_list.setCurrentItem(target)
            target.setSelected(True)
        else:
            self.dish_list.clearSelection()
        self.dish_list.blockSignals(False)
        bar.setValue(scroll)
        if target is not None:
            self._center_if_hidden(target)

    # ---- 선택 ----
    def _category_changed(self, current, _previous=None) -> None:
        if current is None:
            return
        self._category = current.data(_DISH)
        self._fill_dishes()

    def _dish_clicked(self, item) -> None:
        dish = self._by_name.get(item.data(_DISH))
        if dish is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        self.history.clear()  # 목록에서 직접 고름 → 되돌아가기 기록 지움
        # 즐겨찾기 카테고리 안에서 고르면 그 요리의 조리방법으로 옮기지 않고 즐겨찾기에 머묾
        self.select(dish.name, stay=self._category == cooking.FAVORITES and dish.name in self.favorites)

    def select(self, name: str, stay: bool = False) -> None:
        """요리 선택 — 카테고리·목록 선택·상세·게임 위 바가 그 요리로. stay면 지금 카테고리(즐겨찾기) 그대로."""
        dish = self._by_name.get(name)
        if dish is None:
            return
        if self._selected is not dish:
            try:
                config.save_cooking_last_dish(dish.name)  # 다음 실행에 그대로(사용자 보고 11-21)
            except OSError:
                pass
        self._selected = dish
        category = self._category if stay else dish.method
        refill = category != getattr(self, "_filled_category", None) or self.dish_list.count() == 0
        self._category = category
        for i in range(self.category_list.count()):
            item = self.category_list.item(i)
            if item.data(_DISH) == category:
                self.category_list.blockSignals(True)
                self.category_list.setCurrentItem(item)
                self.category_list.blockSignals(False)
        if refill:
            self._fill_dishes()
        else:
            self._mark_selected()
        self._render_detail()
        if self.overlay is not None:
            self.overlay.set_dish(dish)

    @property
    def selected(self):
        return self._selected

    def open_ingredient(self, name: str) -> None:
        """재료가 요리면 그 요리로(들어간 순서를 기억)."""
        target = cooking.ingredient_dish(name, self._index)
        if target is None or self._selected is None:
            return
        self.history.enter(self._selected.name, target.name)
        self.select(target.name)

    def go_back(self) -> None:
        name = self.history.back()
        if name is not None:
            self.select(name)

    # ---- 상세 ----
    def _clear_detail(self) -> None:
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()  # deleteLater는 다음 이벤트 처리 때 지워지므로 그 전까지 겹쳐 보이지 않게
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                _drop_layout(item.layout())

    def _render_detail(self) -> None:
        self._clear_detail()
        lay = self.detail_layout
        self.back_btn = self.overlay_btn = self.lock_btn = None
        self.ingredient_rows: list[QWidget] = []
        dish = self._selected
        if dish is None:
            hint = QLabel("요리를 골라 주세요")
            hint.setStyleSheet(f"color:{pcolor('muted')};")
            lay.addWidget(hint)
            lay.addStretch(1)
            return
        if self.history.peek():
            self.back_btn = QPushButton(f"← {self.history.peek()}")
            self.back_btn.setFlat(True)
            self.back_btn.setFont(self._font(0, QFont.Weight.Normal))  # 스타일시트를 줘도 큰 글꼴 그대로
            self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.back_btn.setStyleSheet(f"text-align:left; color:{pcolor('accent')}; padding:0;")
            self.back_btn.clicked.connect(self.go_back)
            lay.addWidget(self.back_btn, 0, Qt.AlignmentFlag.AlignLeft)
        name = QLabel(dish.name)
        name.setFont(self._font(TITLE_UP, QFont.Weight.Bold))
        lay.addWidget(name)
        self.method_label = QLabel(f"조리방법 · {dish.method}")
        self.method_label.setFont(self._font(SUB_UP, QFont.Weight.Bold))  # 타이틀보다 작고 본문보다 크게(중요 정보)
        lay.addWidget(self.method_label)
        lay.addWidget(divider())
        lay.addWidget(self._section_title("재료"))
        kind, query = self.kind.currentText(), self.query_text()
        for i, ing in enumerate(dish.recipe):
            lay.addWidget(self._ingredient_row(i, ing, highlight=kind == "재료" and cooking.norm(query) != ""
                                               and cooking.norm(query) in cooking.norm(ing.name)))
        lay.addWidget(divider())
        lay.addWidget(self._section_title("비율 — 점선 위치에서 농도 조절을 멈추기"))
        self.gauge = QLabel()
        self.gauge.setPixmap(detail_pixmap(dish).scaledToWidth(GAUGE_VIEW_W, Qt.TransformationMode.SmoothTransformation))
        self.gauge.setFixedSize(self.gauge.pixmap().size())  # 칸이 낮아도 그림이 눌려 잘리지 않게(상세는 스크롤)
        lay.addWidget(self.gauge, 0, Qt.AlignmentFlag.AlignHCenter)
        # 비율 그림 바로 아래, 그림 폭 안에 두 버튼(사용자 피드백 11-19: 재료 → 그림 → 버튼 → 능력치)
        self.overlay_buttons = QWidget()
        self.overlay_buttons.setFixedWidth(GAUGE_VIEW_W)
        buttons = QHBoxLayout(self.overlay_buttons)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.overlay_btn = QPushButton("게임 위에 이 바 띄우기")
        self.overlay_btn.setCheckable(True)
        self.overlay_btn.setChecked(self._overlay_on)
        self.overlay_btn.toggled.connect(self.set_overlay)
        buttons.addWidget(self.overlay_btn, 3)
        self.lock_btn = QPushButton("위치 잠금")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setChecked(config.load_cooking_overlay()["locked"])
        self.lock_btn.setToolTip("잠그면 바를 클릭해도 게임으로 통과해요. 풀면 끌어서 옮기고 휠로 크기를 바꿔요.")
        self.lock_btn.toggled.connect(self._set_locked)
        buttons.addWidget(self.lock_btn, 2)
        lay.addWidget(self.overlay_buttons, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(divider())
        lay.addWidget(self._section_title("능력치"))
        parts = []
        for stat, value in dish.status:
            text = f"{stat} {value:+g}"
            if kind == "능력치" and query and cooking.norm(stat) == cooking.norm(query):
                text = f"<span style='color:{pcolor('accent')}; font-weight:800;'>{text}</span>"
            parts.append(text)
        self.stats = QLabel("&nbsp;&nbsp;&nbsp;".join(parts) or "없음")
        self.stats.setTextFormat(Qt.TextFormat.RichText)
        self.stats.setWordWrap(True)
        self.stats.setFont(self._font(SUB_UP, QFont.Weight.DemiBold))  # 능력치 값이 잘 보이게(h3 정도)
        lay.addWidget(self.stats)
        lay.addStretch(1)

    def _font(self, up: int, weight: QFont.Weight) -> QFont:
        """이 탭 글꼴(사용자 큰 글꼴 포함) 기준으로 +up px·굵기."""
        font = QFont(self.font())
        font.setPixelSize(QFontInfo(self.font()).pixelSize() + up)
        font.setWeight(weight)
        return font

    def _section_title(self, text: str) -> QLabel:
        """구역 제목 — 음악 버프 계산기와 같은 14px·700(ui-rules 계산기 예외), 탭 글꼴 기준이라 큰 글꼴에서도 본문보다 큼."""
        label = QLabel(text)
        label.setFont(self._font(SECTION_UP, QFont.Weight.Bold))
        return label

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and hasattr(self, "detail_layout"):
            self._render_detail()  # 글꼴 크기가 바뀌면 위계를 새 기준으로

    def _ingredient_row(self, i: int, ing: cooking.Ingredient, highlight: bool) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color(i).name()};")
        h.addWidget(dot)
        target = cooking.ingredient_dish(ing.name, self._index)
        strong = self._font(0, QFont.Weight.Bold)
        if target is not None:
            btn = QPushButton(f"▸ {ing.name}")
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"{target.name}(으)로 이동")
            btn.setFont(strong)
            btn.setStyleSheet(f"text-align:left; color:{pcolor('accent')}; padding:0;")
            btn.clicked.connect(lambda _=False, n=ing.name: self.open_ingredient(n))
            h.addWidget(btn)
        else:
            label = QLabel(ing.name)
            if highlight:
                label.setFont(strong)
            h.addWidget(label)
        h.addStretch(1)
        number = QLabel(f"{ing.ratio:g}")
        if highlight:
            number.setFont(strong)
        h.addWidget(number)
        if highlight:  # 검색한 재료 줄 강조
            row.setStyleSheet("background: rgba(0,201,162,0.14); border-radius:4px;")
        row.setProperty("searchHit", highlight)
        self.ingredient_rows.append(row)
        return row

    # ---- 게임 위 비율 바 ----
    def set_overlay(self, on: bool) -> None:
        if bool(on) != self._overlay_on:
            try:
                config.save_cooking_overlay(on=bool(on))  # 켬 상태 저장(사용자 보고 11-21)
            except OSError:
                pass
        self._overlay_on = bool(on)
        if on:
            if self.overlay is None:
                saved = config.load_cooking_overlay()
                self.overlay = CookingBarOverlay(first_scale() if saved["scale"] is None else saved["scale"])
                self.overlay.moved.connect(self._save_position)
                self.overlay.scaled.connect(self._save_position)
                pos = saved["pos"]
                self.overlay.move(*self._first_position() if pos is None else self._on_screen(pos["x"], pos["y"]))
                self.overlay.set_locked(saved["locked"])
            self.overlay.set_dish(self._selected)
            self._timer.start()
            self._find_timer.start()
            self._sync_overlay()
        else:
            self._timer.stop()
            self._find_timer.stop()  # 끈 동안 캡처·찾기 0
            self.autofind.release()  # 라이브 카메라·mss 놓기
            self._apply_auto(None, reset=True)
            if self.overlay is not None:
                self.overlay.hide()

    def _first_position(self) -> tuple[int, int]:
        """화면 가운데 아래쪽(요리창이 뜨는 가운데 근처)."""
        screen = QGuiApplication.primaryScreen().availableGeometry()
        return (screen.x() + (screen.width() - self.overlay.width()) // 2,
                screen.y() + int(screen.height() * 0.6))

    def _on_screen(self, x: int, y: int) -> tuple[int, int]:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = max(screen.left(), min(x, screen.right() - self.overlay.width()))
        y = max(screen.top(), min(y, screen.bottom() - self.overlay.height()))
        return x, y

    def _save_position(self) -> None:
        if self.overlay is None or self.auto_state == "found":  # 자동 자리는 저장 위치를 덮지 않음
            return
        try:
            config.save_cooking_overlay(pos={"x": self.overlay.x(), "y": self.overlay.y()}, scale=self.overlay.scale)
        except OSError:
            pass

    def _set_locked(self, locked: bool) -> None:
        if self.overlay is not None and self.auto_state != "found":  # 찾은 자리는 늘 클릭 통과
            self.overlay.set_locked(locked)
        try:
            config.save_cooking_overlay(locked=bool(locked))
        except OSError:
            pass

    def _game_visible(self) -> bool:
        """게임이 앞일 때, 또는 애드온이 앞이면서 요리 탭이 실제로 보일 때(위치 맞추는 중)만 — 커스텀 오버레이와 같은 규칙
        (사용자 결정 11-19). 바를 누르면 애드온이 앞이 되므로 끄는 중·바가 활성 창일 때는 유지(끄다 사라지지 않게)."""
        if self._watcher is None:
            return True
        if self.overlay is not None and (self.overlay.dragging or self.overlay.isActiveWindow()):
            return True
        try:
            return self._watcher.is_game_active() or (self._watcher.is_self_active() and self.isVisible())
        except Exception:  # noqa: BLE001
            return True

    # ---- 요리창 자동 찾기 ----
    def _auto_tick(self) -> None:
        run = self._overlay_on and self._selected is not None and self._game_front()
        state = self.autofind.tick(run)
        if state is not None:
            self._apply_auto(state)

    def _game_front(self) -> bool:
        if self._watcher is None:
            return False
        try:
            return bool(self._watcher.is_game_active())
        except Exception:  # noqa: BLE001
            return False

    def _apply_auto(self, state, reset: bool = False) -> None:
        """찾은 자리면 바를 그 자리에(잠금·저장 안 함), 요리창이 꺼지면 숨김, 못 찾으면 손으로 맞춘 자리로."""
        if reset:
            self.autofind.reset()
        kind = "manual" if state is None else state.kind
        before, self.auto_state = self.auto_state, kind
        if self.overlay is None:
            return
        if kind == "found":
            from . import dpi
            ratio = dpi.screen_scale() or 1.0
            ox, oy = self.autofind.origin
            bx, by, _bw, bh = state.bar
            self.overlay.set_scale(first_scale())          # 물리 245×10(사용자 배율은 저장값 그대로)
            self.overlay.set_locked(True)                   # 찾은 자리는 클릭 통과(끌어서 저장 위치를 덮지 않게)
            x = round((ox + bx) / ratio)
            bottom = round((oy + by + bh) / ratio)
            self.overlay.move(x, bottom - self.overlay.height())
        elif kind == "manual" and before in ("found", "closed"):
            self._restore_manual()  # 못 알아보면(신호는 있음) 손으로 맞춘 자리·배율·잠금으로 — 숨기지 않음
        self._sync_overlay()

    def _restore_manual(self) -> None:
        """자동 자리에서 벗어나면 손으로 맞춘 저장 위치·배율·잠금으로."""
        saved = config.load_cooking_overlay()
        self.overlay.set_scale(first_scale() if saved["scale"] is None else saved["scale"])
        pos = saved["pos"]
        self.overlay.move(*self._first_position() if pos is None else self._on_screen(pos["x"], pos["y"]))
        self.overlay.set_locked(self.lock_btn.isChecked() if self.lock_btn is not None else saved["locked"])

    def _sync_overlay(self) -> None:
        """게임(또는 이 앱)이 앞에 있을 때만 — 다른 오버레이와 같은 규칙. 전투 보조 일시정지와는 무관(편의기능)."""
        if self.overlay is None:
            return
        want = (self._overlay_on and self._selected is not None and self._game_visible()
                and self.auto_state != "closed")  # 요리창이 꺼지면 숨김(자동 찾기)
        if want and not self.overlay.isVisible():
            self.overlay.show()
        elif not want and self.overlay.isVisible():
            self.overlay.hide()

    def shutdown(self) -> None:
        self._timer.stop()
        self._find_timer.stop()
        self.autofind.shutdown()
        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None


def first_scale() -> float:
    """첫 바 배율 — 명세 6절 245×10은 게임 화면(물리 픽셀) 측정값인데 Qt 위젯 크기는 논리 픽셀이라
    Windows 배율 125%·150%면 그만큼 커진다(QA 반려 11-19). 물리 245×10이 되게 1/배율로 시작. 사용자가 맞춘 저장 배율은 그대로."""
    from . import dpi
    return 1.0 / (dpi.screen_scale() or 1.0)


def _drop_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()
            item.widget().setParent(None)
            item.widget().deleteLater()
        elif item.layout() is not None:
            _drop_layout(item.layout())
