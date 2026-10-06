"""버프 탭 (기획서 5.1 상단).

목록 = 등록된 버프(카탈로그, 아이콘·이미지 폴더 기반). 앵커(premium_battle)는 최상단 고정.
버프별 설정(지속시간 표시·종료 알림)과 표시 순서를 config.local.json에 저장한다.
- − : 오버레이에서 숨김(목록에서 빠짐) / + : 숨긴 버프 다시 표시 / ▲▼ : 표시 순서
- 새 버프는 아이콘·이미지 파일을 추가하면 목록에 자동 등장한다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import catalog as catalog_mod
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
    lock_toggled = Signal(bool)  # 오버레이 고정 토글 → main이 오버레이에 적용
    tracking_changed = Signal()  # 순서·노출·지속시간·알림 변경 → 라이브 반영(재시작 X)
    catalog_changed = Signal()  # 버프 추가·삭제·아이콘 변경 → 엔진 재구성 필요
    scale_changed = Signal(int)  # 오버레이 배율(%) 변경

    def __init__(self) -> None:
        super().__init__()
        self._catalog: dict[str, BuffDef] = {b.id: b for b in load_catalog()}
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

        top = QHBoxLayout()
        top.setSpacing(6)
        region_btn = QPushButton("버프 영역 지정")
        region_btn.clicked.connect(self._pick_region)
        top.addWidget(region_btn, 1)
        self.lock_btn = QPushButton("오버레이 고정")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setStyleSheet(
            "QPushButton:checked { background:#00B894; color:white; font-weight:600; }"
        )
        self.lock_btn.toggled.connect(self._on_lock_toggled)
        top.addWidget(self.lock_btn, 1)
        v.addLayout(top)

        self.region_hint = hint_label("")
        self._update_region_hint()
        v.addWidget(self.region_hint)

        self.buff_list = QListWidget()
        self.buff_list.setIconSize(QSize(32, 32))
        self.buff_list.currentRowChanged.connect(self._on_select)
        v.addWidget(self.buff_list, 1)

        order_row = QHBoxLayout()
        order_row.setSpacing(4)
        self.add_btn = QPushButton("＋")
        self.add_btn.setToolTip("새 버프 등록")
        self.add_btn.clicked.connect(self._on_register)
        self.del_btn = QPushButton("－")
        self.del_btn.setToolTip("선택한 버프 삭제")
        self.del_btn.clicked.connect(self._on_delete)
        self.up_btn = QPushButton("▲")
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton("▼")
        self.down_btn.clicked.connect(lambda: self._move(1))
        # 목록 폭에 꽉 차게 4등분(균등 신축)
        for b in (self.add_btn, self.del_btn, self.up_btn, self.down_btn):
            order_row.addWidget(b, 1)
        v.addLayout(order_row)

        scale_row = QHBoxLayout()
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setPrefix("오버레이 배율  ")
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(config.load_overlay_scales()[0])
        self.scale_spin.valueChanged.connect(self._on_scale)
        scale_row.addWidget(self.scale_spin)
        scale_row.addStretch(1)
        v.addLayout(scale_row)
        return panel

    def _on_scale(self, pct: int) -> None:
        config.set_buff_scale(pct)
        self.scale_changed.emit(pct)

    def _rows(self) -> list[str]:
        """목록에 표시되는 id 순서: 앵커 먼저, 그다음 표시 순서."""
        return [ANCHOR_ID, *self._order]

    def _on_lock_toggled(self, locked: bool) -> None:
        self.lock_btn.setText("오버레이 고정됨" if locked else "오버레이 고정")
        self.lock_toggled.emit(locked)

    def set_lock_state(self, locked: bool) -> None:
        """저장된 고정 상태 복원(버튼 UI 동기화 + 적용)."""
        self.lock_btn.blockSignals(True)
        self.lock_btn.setChecked(locked)
        self.lock_btn.blockSignals(False)
        self._on_lock_toggled(locked)  # 텍스트 갱신 + lock_toggled 방출(→ 오버레이 적용)

    # ---- 영역 지정 ----
    def _update_region_hint(self) -> None:
        region = config.load_capture_region("buffTracker")
        if region:
            self.region_hint.setText(
                f"영역: {region['x']},{region['y']}  "
                f"{region['w']}×{region['h']}  ✔"
            )
            self.region_hint.setStyleSheet("color:#2ecc71;")
        else:
            self.region_hint.setText("영역 미지정 — 버튼으로 상태창 영역을 지정하세요")
            self.region_hint.setStyleSheet("color:#8a8f98;")

    def _pick_region(self) -> None:
        from .region_selector import RegionSelector

        self._selector = RegionSelector()  # 참조 유지(GC 방지)
        self._selector.selected.connect(self._on_region_selected)
        self._selector.start()

    def _on_region_selected(self, x: int, y: int, w: int, h: int) -> None:
        config.save_capture_region(x, y, w, h, "buffTracker")
        self._update_region_hint()

    def _display_name(self, bid: str) -> str:
        s = self._settings.get(bid)
        if s is not None and s.name:
            return s.name
        buff = self._catalog.get(bid)
        return buff.name if buff else bid

    def _rebuild_list(self) -> None:
        keep = self._current
        self.buff_list.blockSignals(True)
        self.buff_list.clear()
        for bid in self._rows():
            buff = self._catalog.get(bid)
            name = self._display_name(bid)
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

    # ---- 등록/삭제/순서 ----
    def _new_id(self) -> str:
        n = 1
        while f"buff_{n}" in self._catalog:
            n += 1
        return f"buff_{n}"

    def _on_register(self) -> None:
        """새 버프 추가: 빈 아이콘·이름 '-'로 목록 하단에 넣고, 오른쪽에서 설정."""
        new_id = self._new_id()
        catalog_mod.register_buff(
            new_id, catalog_mod.NONE_MATCH_ICON, catalog_mod.NONE_DISPLAY_IMAGE
        )
        self._catalog = {b.id: b for b in load_catalog()}
        self._settings, self._order = self._load_state()
        self._settings[new_id].name = "-"  # 미설정 표시
        self._current = new_id
        self._save()
        self._rebuild_list()
        self.catalog_changed.emit()

    def _on_delete(self) -> None:
        bid = self._current_id()
        if bid is None or bid == ANCHOR_ID:
            return
        box = QMessageBox(self)
        box.setWindowTitle("버프 삭제")
        box.setText(f"'{bid}' 버프를 삭제할까요?\n(매칭 아이콘·표시 이미지 파일이 삭제됩니다)")
        yes = box.addButton("예", QMessageBox.ButtonRole.YesRole)
        box.addButton("아니오", QMessageBox.ButtonRole.NoRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        catalog_mod.delete_buff(bid)
        self._settings.pop(bid, None)
        if bid in self._order:
            self._order.remove(bid)
        self._current = None
        self._reload_catalog()

    def _reload_catalog(self, select: str | None = None) -> None:
        """파일 변경(등록/삭제) 후 카탈로그·상태 재적재."""
        self._catalog = {b.id: b for b in load_catalog()}
        self._settings, self._order = self._load_state()
        self._current = select
        self._save()
        self._rebuild_list()
        self.catalog_changed.emit()

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
        self.tracking_changed.emit()

    # ---- 폼 ----
    def _build_form_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        v.addWidget(section_label("이름"))
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._save_name)  # 포커스 아웃·엔터 시 저장
        v.addWidget(self.name_edit)

        v.addWidget(section_label("매칭 아이콘"))
        match_row = QHBoxLayout()
        self.match_slot = icon_slot()
        match_row.addWidget(self.match_slot)
        match_row.addWidget(QPushButton("상태창에서 가져오기"))
        self.match_file_btn = QPushButton("파일 선택")
        self.match_file_btn.clicked.connect(self._pick_match_icon)
        match_row.addWidget(self.match_file_btn)
        match_row.addStretch(1)
        v.addLayout(match_row)

        v.addWidget(section_label("보여줄 아이콘"))
        show_row = QHBoxLayout()
        self.display_slot = icon_slot("—")
        show_row.addWidget(self.display_slot)
        self.display_file_btn = QPushButton("파일 선택")
        self.display_file_btn.clicked.connect(self._pick_display_image)
        self.display_clear_btn = QPushButton("초기화")
        self.display_clear_btn.clicked.connect(self._clear_display_image)
        show_row.addWidget(self.display_file_btn)
        show_row.addWidget(self.display_clear_btn)
        show_row.addStretch(1)
        v.addLayout(show_row)
        v.addWidget(hint_label("└ 비워두면 매칭 아이콘 사용"))

        v.addSpacing(6)
        self.display_check = QCheckBox("오버레이에 표시")
        self.display_check.toggled.connect(self._form_changed)
        v.addWidget(self.display_check)
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

        # 2차 알림: 놓침·오독 대비 재알림(소리·점멸은 1차 설정을 그대로 재사용).
        alert_row2 = QHBoxLayout()
        self.alert2_check = QCheckBox("2차 알림")
        self.before2_spin = QSpinBox()
        self.before2_spin.setRange(1, 300)
        self.before2_spin.setValue(5)  # 기본 5초 전
        self.before2_spin.setSuffix(" 초 전")
        alert_row2.addWidget(self.alert2_check)
        alert_row2.addWidget(self.before2_spin)
        alert_row2.addStretch(1)
        v.addLayout(alert_row2)
        self.alert2_check.toggled.connect(self._on_alert2_toggled)
        self.before2_spin.valueChanged.connect(self._form_changed)
        v.addWidget(hint_label("└ 1차를 놓치거나 시간을 잘못 읽었을 때 한 번 더 알림"))

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
        self._name_id = bid  # name_edit이 편집 중인 버프(포커스 아웃 저장 기준)
        self.name_edit.setText(self._display_name(bid))
        self._set_slot(self.match_slot, buff.match_icon if buff else None, "▣")
        self._set_slot(
            self.display_slot, buff.display_image if buff else None, "—"
        )
        self.display_check.setChecked(not s.hidden)
        self.show_duration.setChecked(s.show_duration)
        self.alert_check.setChecked(s.alert.enabled)
        self.before_spin.setValue(s.alert.before_sec)
        self.blink_check.setChecked(s.alert.blink)
        self.sound_check.setChecked(s.alert.sound)
        self.alert2_check.setChecked(s.alert.enabled2)
        self.before2_spin.setValue(s.alert.before_sec2)
        self._apply_alert_enabled(s.alert.enabled)
        # 앵커는 오버레이 표시·지속시간·알림 없음 → 편집 비활성
        for wdg in (self.display_check, self.show_duration, self.alert_check,
                    self.before_spin, self.blink_check, self.sound_check,
                    self.alert2_check, self.before2_spin):
            wdg.setEnabled(not is_anchor)
        self._loading = False

    def _on_alert_toggled(self, enabled: bool) -> None:
        self._apply_alert_enabled(enabled)
        if not enabled:
            self.blink_check.setChecked(False)
            self.sound_check.setChecked(False)
            self.alert2_check.setChecked(False)  # 1차 끄면 2차도 해제(→ 초기화)
        self._form_changed()

    def _on_alert2_toggled(self, _enabled: bool) -> None:
        # 체크 시 보이는 그대로(기본 5초 전) 등록, 해제 시 기본값 5로 초기화.
        if not self._loading and not self.alert2_check.isChecked():
            self.before2_spin.setValue(5)
        self._apply_alert_enabled(self.alert_check.isChecked())
        self._form_changed()

    def _apply_alert_enabled(self, enabled: bool) -> None:
        on = enabled and self._current != ANCHOR_ID
        for wdg in (self.before_spin, self.blink_check, self.sound_check,
                    self.alert2_check):
            wdg.setEnabled(on)
        # 2차 초 입력은 '종료 알림'과 '2차 알림'이 모두 켜졌을 때만
        self.before2_spin.setEnabled(on and self.alert2_check.isChecked())

    def _form_changed(self) -> None:
        if self._loading or self._current is None:
            return
        s = self._settings[self._current]
        s.hidden = not self.display_check.isChecked()  # 오버레이 노출 여부
        s.show_duration = self.show_duration.isChecked()
        s.alert = config.AlertConfig(
            enabled=self.alert_check.isChecked(),
            before_sec=self.before_spin.value(),
            blink=self.blink_check.isChecked(),
            sound=self.sound_check.isChecked(),
            enabled2=self.alert2_check.isChecked(),
            before_sec2=self.before2_spin.value(),
        )
        self._save()
        self.tracking_changed.emit()

    # ---- 이름·아이콘 편집 ----
    def _save_name(self) -> None:
        if self._loading or self._name_id is None:
            return
        s = self._settings.get(self._name_id)
        if s is None:
            return
        new = self.name_edit.text().strip()
        if s.name == new:
            return
        s.name = new
        self._save()
        self._rebuild_list()
        self.tracking_changed.emit()

    def _pick_match_icon(self) -> None:
        bid = self._current
        if bid is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "매칭 아이콘 선택", "", "이미지 (*.png)"
        )
        if not path:
            return
        catalog_mod.set_match_icon(bid, Path(path))
        self._reload_catalog(select=bid)

    def _pick_display_image(self) -> None:
        bid = self._current
        if bid is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "표시 이미지 선택", "", "이미지 (*.png)"
        )
        if not path:
            return
        catalog_mod.set_display_image(bid, Path(path))
        self._reload_catalog(select=bid)

    def _clear_display_image(self) -> None:
        bid = self._current
        if bid is None:
            return
        catalog_mod.clear_display_image(bid)
        self._reload_catalog(select=bid)

    def _set_slot(self, slot, path: Path | None, placeholder: str) -> None:
        pm = _pixmap(path, 40)
        if pm is not None:
            slot.setPixmap(pm)
        else:
            slot.setText(placeholder)
