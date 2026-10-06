"""버프 탭 (기획서 5.1 상단).

목록 = 등록된 버프(카탈로그, 아이콘·이미지 폴더 기반). 앵커(premium_battle)는 최상단 고정.
버프별 설정(지속시간 표시·종료 알림)과 표시 순서를 config.local.json에 저장한다.
- − : 오버레이에서 숨김(목록에서 빠짐) / + : 숨긴 버프 다시 표시 / ▲▼ : 표시 순서
- 새 버프는 아이콘·이미지 파일을 추가하면 목록에 자동 등장한다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..catalog import BuffDef, load_catalog
from .widgets import hint_label, icon_slot, section_label

# 앵커로 고정 사용할 버프(항상 존재, 지속시간 없음 → 판정 기준)
ANCHOR_ID = "premium_battle"


def _pixmap(path: Path | None, size: int) -> QPixmap | None:
    if path is None:
        return None
    pm = QPixmap(str(path))
    if pm.isNull():
        return None
    return pm.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


class BuffTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._catalog: dict[str, BuffDef] = {b.id: b for b in load_catalog()}
        self._settings, self._order = self._load_state()
        self._current: str | None = None
        self._loading = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(14)
        outer.addWidget(self._build_list_panel(), 1)
        outer.addWidget(self._build_form_panel(), 1)

        self._rebuild_list()
        self.buff_list.setCurrentRow(0)

    # ---- 상태(카탈로그 + 저장된 설정) ----
    def _load_state(self) -> tuple[dict[str, config.BuffSettings], list[str]]:
        saved = config.load_buff_settings()
        settings = {s.id: s for s in saved}
        # 모든 카탈로그 버프에 설정 보장
        settings.setdefault(
            ANCHOR_ID,
            config.BuffSettings(
                id=ANCHOR_ID,
                show_duration=False,
                alert=config.AlertConfig(enabled=False),
            ),
        )
        for bid in self._catalog:
            settings.setdefault(bid, config.BuffSettings(id=bid))

        # 표시 순서 = 저장 순서(숨김·앵커 제외) + 새 카탈로그 버프
        order: list[str] = []
        for s in saved:
            if s.id in self._catalog and s.id != ANCHOR_ID and not s.hidden:
                order.append(s.id)
        for bid in self._catalog:
            if bid != ANCHOR_ID and bid not in order and not settings[bid].hidden:
                order.append(bid)
        return settings, order

    def _save(self) -> None:
        shown = [self._settings[i] for i in self._order]
        hidden = [
            s
            for i, s in self._settings.items()
            if i != ANCHOR_ID and i not in self._order and i in self._catalog
        ]
        config.save_buff_settings([self._settings[ANCHOR_ID], *shown, *hidden])

    # ---- 목록 ----
    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        v.addWidget(QPushButton("버프 영역 지정"))
        v.addWidget(hint_label("영역 미지정 — 버튼으로 상태창 영역을 지정하세요"))

        self.buff_list = QListWidget()
        self.buff_list.setIconSize(QSize(32, 32))
        self.buff_list.currentRowChanged.connect(self._on_select)
        v.addWidget(self.buff_list, 1)

        order_row = QHBoxLayout()
        self.add_btn = QPushButton("＋")
        self.add_btn.setToolTip("숨긴 버프 다시 표시")
        self.add_btn.clicked.connect(self._on_add)
        self.del_btn = QPushButton("－")
        self.del_btn.setToolTip("오버레이에서 숨김")
        self.del_btn.clicked.connect(self._on_hide)
        self.up_btn = QPushButton("▲")
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton("▼")
        self.down_btn.clicked.connect(lambda: self._move(1))
        for b in (self.add_btn, self.del_btn, self.up_btn, self.down_btn):
            b.setFixedWidth(46)
            order_row.addWidget(b)
        order_row.addStretch(1)
        v.addLayout(order_row)
        return panel

    def _rows(self) -> list[str]:
        """목록에 표시되는 id 순서: 앵커 먼저, 그다음 표시 순서."""
        return [ANCHOR_ID, *self._order]

    def _rebuild_list(self) -> None:
        keep = self._current
        self.buff_list.blockSignals(True)
        self.buff_list.clear()
        for bid in self._rows():
            buff = self._catalog.get(bid)
            name = buff.name if buff else bid
            label = f"⚓ {name} (앵커)" if bid == ANCHOR_ID else name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, bid)
            if buff is not None:
                pm = _pixmap(buff.display_image or buff.match_icon, 32)
                if pm is not None:
                    item.setIcon(QIcon(pm))
            self.buff_list.addItem(item)
        self.buff_list.blockSignals(False)

        rows = self._rows()
        row = rows.index(keep) if keep in rows else 0
        self.buff_list.setCurrentRow(row)

    def _current_id(self) -> str | None:
        item = self.buff_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # ---- 순서/표시 ----
    def _on_add(self) -> None:
        hidden = [
            bid
            for bid in self._catalog
            if bid != ANCHOR_ID and bid not in self._order
        ]
        if not hidden:
            return
        menu = QMenu(self)
        for bid in sorted(hidden):
            act: QAction = menu.addAction(self._catalog[bid].name)
            act.setData(bid)
        chosen = menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))
        if chosen is None:
            return
        bid = chosen.data()
        self._settings[bid].hidden = False
        self._order.append(bid)
        self._current = bid
        self._save()
        self._rebuild_list()

    def _on_hide(self) -> None:
        bid = self._current_id()
        if bid is None or bid == ANCHOR_ID or bid not in self._order:
            return
        self._settings[bid].hidden = True
        self._order.remove(bid)
        self._current = None
        self._save()
        self._rebuild_list()

    def _move(self, delta: int) -> None:
        bid = self._current_id()
        if bid is None or bid == ANCHOR_ID or bid not in self._order:
            return
        i = self._order.index(bid)
        j = i + delta
        if not (0 <= j < len(self._order)):
            return
        self._order[i], self._order[j] = self._order[j], self._order[i]
        self._current = bid
        self._save()
        self._rebuild_list()

    # ---- 폼 ----
    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        v.addWidget(section_label("이름"))
        self.name_edit = QLineEdit()
        self.name_edit.setReadOnly(True)  # 이름은 파일(카탈로그) 기준
        v.addWidget(self.name_edit)

        v.addWidget(section_label("매칭 아이콘"))
        match_row = QHBoxLayout()
        self.match_slot = icon_slot()
        match_row.addWidget(self.match_slot)
        match_row.addWidget(QPushButton("상태창에서 가져오기"))
        match_row.addStretch(1)
        v.addLayout(match_row)

        v.addWidget(section_label("보여줄 아이콘"))
        show_row = QHBoxLayout()
        self.display_slot = icon_slot("—")
        show_row.addWidget(self.display_slot)
        show_row.addWidget(QPushButton("파일 선택"))
        show_row.addWidget(QPushButton("초기화"))
        show_row.addStretch(1)
        v.addLayout(show_row)
        v.addWidget(hint_label("└ 비워두면 매칭 아이콘 사용"))

        v.addSpacing(6)
        self.show_duration = QCheckBox("지속시간 표시")
        self.show_duration.toggled.connect(self._form_changed)
        v.addWidget(self.show_duration)

        alert_row = QHBoxLayout()
        self.alert_check = QCheckBox("종료 알림")
        self.before_spin = QSpinBox()
        self.before_spin.setRange(1, 300)
        self.before_spin.setSuffix(" 초 전")
        self.blink_check = QCheckBox("점멸")
        self.sound_check = QCheckBox("소리")
        for wdg in (self.alert_check, self.before_spin, self.blink_check, self.sound_check):
            alert_row.addWidget(wdg)
        alert_row.addStretch(1)
        v.addLayout(alert_row)
        self.alert_check.toggled.connect(self._on_alert_toggled)
        for wdg in (self.before_spin, self.blink_check, self.sound_check):
            if isinstance(wdg, QCheckBox):
                wdg.toggled.connect(self._form_changed)
            else:
                wdg.valueChanged.connect(self._form_changed)

        v.addStretch(1)
        return panel

    def _on_select(self, _row: int) -> None:
        bid = self._current_id()
        self._current = bid
        if bid is None:
            return
        buff = self._catalog.get(bid)
        s = self._settings[bid]
        is_anchor = bid == ANCHOR_ID

        self._loading = True
        self.name_edit.setText(buff.name if buff else bid)
        self._set_slot(self.match_slot, buff.match_icon if buff else None, "▣")
        self._set_slot(
            self.display_slot, buff.display_image if buff else None, "—"
        )
        self.show_duration.setChecked(s.show_duration)
        self.alert_check.setChecked(s.alert.enabled)
        self.before_spin.setValue(s.alert.before_sec)
        self.blink_check.setChecked(s.alert.blink)
        self.sound_check.setChecked(s.alert.sound)
        self._apply_alert_enabled(s.alert.enabled)
        # 앵커는 지속시간·알림 없음 → 편집 비활성
        for wdg in (self.show_duration, self.alert_check, self.before_spin,
                    self.blink_check, self.sound_check):
            wdg.setEnabled(not is_anchor)
        self._loading = False

    def _on_alert_toggled(self, enabled: bool) -> None:
        self._apply_alert_enabled(enabled)
        if not enabled:
            self.blink_check.setChecked(False)
            self.sound_check.setChecked(False)
        self._form_changed()

    def _apply_alert_enabled(self, enabled: bool) -> None:
        for wdg in (self.before_spin, self.blink_check, self.sound_check):
            wdg.setEnabled(enabled and self._current != ANCHOR_ID)

    def _form_changed(self) -> None:
        if self._loading or self._current is None:
            return
        s = self._settings[self._current]
        s.show_duration = self.show_duration.isChecked()
        s.alert = config.AlertConfig(
            enabled=self.alert_check.isChecked(),
            before_sec=self.before_spin.value(),
            blink=self.blink_check.isChecked(),
            sound=self.sound_check.isChecked(),
        )
        self._save()

    def _set_slot(self, slot, path: Path | None, placeholder: str) -> None:
        pm = _pixmap(path, 40)
        if pm is not None:
            slot.setPixmap(pm)
        else:
            slot.setText(placeholder)
