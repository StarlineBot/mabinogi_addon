"""디버프 탭 (기획서 5.1 하단 / 3.2).

버프 탭과 같은 관리 방식이되 더 단순하다: 이름, 매칭 아이콘(파일 선택), 오버레이 노출.
지속시간·알림·앵커 없음. 목록·설정은 debuffTracker 섹션에 저장.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import catalog as catalog_mod
from .. import config
from ..catalog import DEFAULT_DEBUFF_ICON_DIR, BuffDef, load_debuff_catalog
from .buff_tab import _pixmap
from .widgets import hint_label, icon_slot, section_label


class DebuffTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._catalog: dict[str, BuffDef] = {
            b.id: b for b in load_debuff_catalog()
        }
        self._settings, self._order = self._load_state()
        self._current: str | None = None
        self._name_id: str | None = None
        self._loading = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(14)
        outer.addWidget(self._build_list_panel(), 1)
        outer.addWidget(self._build_form_panel(), 1)

        self._rebuild_list()
        if self.debuff_list.count():
            self.debuff_list.setCurrentRow(0)

    # ---- 상태 ----
    def _load_state(self) -> tuple[dict[str, config.BuffSettings], list[str]]:
        saved = config.load_debuff_settings()
        settings = {s.id: s for s in saved}
        for did in self._catalog:
            settings.setdefault(did, config.BuffSettings(id=did))
        order = [s.id for s in saved if s.id in self._catalog]
        for did in self._catalog:
            if did not in order:
                order.append(did)
        return settings, order

    def _save(self) -> None:
        config.save_debuff_settings([self._settings[i] for i in self._order])

    def _display_name(self, did: str) -> str:
        s = self._settings.get(did)
        if s is not None and s.name:
            return s.name
        buff = self._catalog.get(did)
        return buff.name if buff else did

    # ---- 목록 ----
    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        v.addWidget(QPushButton("디버프 줄 영역 지정"))
        v.addWidget(hint_label("영역 미지정 — 버튼으로 디버프 줄 영역을 지정하세요"))

        self.debuff_list = QListWidget()
        self.debuff_list.setIconSize(QSize(28, 28))
        self.debuff_list.currentRowChanged.connect(self._on_select)
        v.addWidget(self.debuff_list, 1)

        order_row = QHBoxLayout()
        order_row.setSpacing(4)
        add_btn = QPushButton("＋")
        add_btn.setToolTip("새 디버프 등록")
        add_btn.clicked.connect(self._on_register)
        del_btn = QPushButton("－")
        del_btn.setToolTip("선택한 디버프 삭제")
        del_btn.clicked.connect(self._on_delete)
        up_btn = QPushButton("▲")
        up_btn.clicked.connect(lambda: self._move(-1))
        down_btn = QPushButton("▼")
        down_btn.clicked.connect(lambda: self._move(1))
        for b in (add_btn, del_btn, up_btn, down_btn):
            order_row.addWidget(b, 1)
        v.addLayout(order_row)
        return panel

    def _rebuild_list(self) -> None:
        keep = self._current
        self.debuff_list.blockSignals(True)
        self.debuff_list.clear()
        for did in self._order:
            item = QListWidgetItem(self._display_name(did))
            item.setData(Qt.ItemDataRole.UserRole, did)
            buff = self._catalog.get(did)
            if buff is not None:
                pm = _pixmap(buff.match_icon, 28)
                if pm is not None:
                    item.setIcon(QIcon(pm))
            self.debuff_list.addItem(item)
        self.debuff_list.blockSignals(False)
        if keep in self._order:
            self.debuff_list.setCurrentRow(self._order.index(keep))
        elif self.debuff_list.count():
            self.debuff_list.setCurrentRow(0)

    def _current_id(self) -> str | None:
        item = self.debuff_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # ---- 등록/삭제/순서 ----
    def _new_id(self) -> str:
        n = 1
        while f"debuff_{n}" in self._catalog:
            n += 1
        return f"debuff_{n}"

    def _on_register(self) -> None:
        """빈 아이콘·이름 '-'로 하단에 추가, 오른쪽에서 설정."""
        new_id = self._new_id()
        catalog_mod.register_buff(
            new_id,
            catalog_mod.NONE_MATCH_ICON,
            None,
            icon_dir=DEFAULT_DEBUFF_ICON_DIR,
            image_dir=DEFAULT_DEBUFF_ICON_DIR,
        )
        self._catalog = {b.id: b for b in load_debuff_catalog()}
        self._settings, self._order = self._load_state()
        self._settings[new_id].name = "-"
        self._current = new_id
        self._save()
        self._rebuild_list()

    def _on_delete(self) -> None:
        did = self._current_id()
        if did is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("디버프 삭제")
        box.setText(f"'{did}' 디버프를 삭제할까요?\n(매칭 아이콘 파일이 삭제됩니다)")
        yes = box.addButton("예", QMessageBox.ButtonRole.YesRole)
        box.addButton("아니오", QMessageBox.ButtonRole.NoRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        catalog_mod.delete_buff(
            did, icon_dir=DEFAULT_DEBUFF_ICON_DIR, image_dir=DEFAULT_DEBUFF_ICON_DIR
        )
        self._settings.pop(did, None)
        if did in self._order:
            self._order.remove(did)
        self._current = None
        self._reload()

    def _reload(self, select: str | None = None) -> None:
        self._catalog = {b.id: b for b in load_debuff_catalog()}
        self._settings, self._order = self._load_state()
        self._current = select
        self._save()
        self._rebuild_list()

    def _move(self, delta: int) -> None:
        did = self._current_id()
        if did is None or did not in self._order:
            return
        i = self._order.index(did)
        j = i + delta
        if not (0 <= j < len(self._order)):
            return
        self._order[i], self._order[j] = self._order[j], self._order[i]
        self._current = did
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
        self.name_edit.editingFinished.connect(self._save_name)
        v.addWidget(self.name_edit)

        v.addWidget(section_label("매칭 아이콘"))
        match_row = QHBoxLayout()
        self.match_slot = icon_slot()
        match_row.addWidget(self.match_slot)
        match_row.addWidget(QPushButton("영역에서 가져오기"))
        file_btn = QPushButton("파일 선택")
        file_btn.clicked.connect(self._pick_match_icon)
        match_row.addWidget(file_btn)
        match_row.addStretch(1)
        v.addLayout(match_row)

        v.addSpacing(6)
        self.display_check = QCheckBox("오버레이에 표시")
        self.display_check.toggled.connect(self._form_changed)
        v.addWidget(self.display_check)

        v.addWidget(
            hint_label("디버프는 '아직 걸리지 않은 것'만 오버레이에 나열됩니다.")
        )
        v.addStretch(1)
        return panel

    def _on_select(self, _row: int) -> None:
        did = self._current_id()
        self._current = did
        if did is None:
            return
        s = self._settings[did]
        buff = self._catalog.get(did)
        self._loading = True
        self._name_id = did
        self.name_edit.setText(self._display_name(did))
        self._set_slot(self.match_slot, buff.match_icon if buff else None, "▣")
        self.display_check.setChecked(not s.hidden)
        self._loading = False

    def _form_changed(self) -> None:
        if self._loading or self._current is None:
            return
        self._settings[self._current].hidden = not self.display_check.isChecked()
        self._save()

    def _save_name(self) -> None:
        if self._loading or self._name_id is None:
            return
        s = self._settings.get(self._name_id)
        if s is None or s.name == self.name_edit.text().strip():
            return
        s.name = self.name_edit.text().strip()
        self._save()
        self._rebuild_list()

    def _pick_match_icon(self) -> None:
        did = self._current
        if did is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "매칭 아이콘 선택", "", "이미지 (*.png)"
        )
        if not path:
            return
        catalog_mod.set_match_icon(did, Path(path), icon_dir=DEFAULT_DEBUFF_ICON_DIR)
        self._reload(select=did)

    def _set_slot(self, slot, path: Path | None, placeholder: str) -> None:
        pm = _pixmap(path, 40)
        if pm is not None:
            slot.setPixmap(pm)
        else:
            slot.setText(placeholder)
