"""디버프 탭 (기획서 5.1 하단 / 3.2).

버프 탭과 같은 관리 방식이되 더 단순하다: 이름, 매칭 아이콘(파일 선택), 오버레이 노출.
지속시간·알림·앵커 없음. 목록·설정은 debuffTracker 섹션에 저장.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
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
from ..catalog import USER_DEBUFF_ICON_DIR, BuffDef, available_debuff_catalog
from .buff_tab import _capture_icon_to, _pixmap
from .help_dialog import tab_header
from .widgets import checkbox, hint_label, icon_slot, section_label

# 디버프 트래커 사용법(? 아이콘 → 새 창).
HELP_TITLE = "디버프 트래커 사용법"
HELP_HTML = """
<h3>디버프 트래커란?</h3>
<p>보스 체력바 위의 <b>디버프 줄</b>을 읽어, 아직 걸지 않은 디버프를
화면 위 오버레이로 보여줍니다. 화면을 <b>읽기만</b> 하며 키 입력·클릭은 하지 않습니다.</p>

<h3>사용 순서</h3>
<ol>
<li><b>디버프 줄 영역 지정</b> — 보스 체력바 위, 디버프가 표시되는 영역을 먼저
드래그로 잡습니다. (돋보기로 픽셀 단위 조정)</li>
<li><b>디버프 등록 (＋)</b> — 보고 싶은 디버프를 추가하고, 그 아이콘을
<b>영역에서 바로 집거나</b> 이미지 파일로 등록합니다.
(－ 삭제 / ▲▼ 표시 순서)</li>
<li><b>오버레이 배치</b> — 드래그로 원하는 위치에 옮기고 마우스 휠로 <b>배율</b>을
조절합니다. <b>오버레이 고정</b>을 누르면 위치가 잠기고 클릭도 통과해
게임에 방해되지 않습니다.</li>
</ol>

<p>※ 디버프는 <b>아직 걸리지 않은 것</b>만 오버레이에 나열됩니다.</p>
"""


class DebuffTab(QWidget):
    lock_toggled = Signal(bool)  # 디버프 오버레이 고정 토글
    tracking_changed = Signal()  # 순서·노출 변경 → 라이브 반영
    catalog_changed = Signal()  # 디버프 추가·삭제·아이콘 변경 → 엔진 재구성
    scale_changed = Signal(int)  # 디버프 오버레이 배율(%) 변경

    def __init__(self) -> None:
        super().__init__()
        self._catalog: dict[str, BuffDef] = {
            b.id: b for b in available_debuff_catalog()
        }
        self._settings, self._order = self._load_state()
        self._current: str | None = None
        self._name_id: str | None = None
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)
        outer.addWidget(tab_header(
            "아직 안 걸린 디버프만 오버레이로 표시", HELP_TITLE, HELP_HTML, self
        ))
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_list_panel(), 1)
        body.addWidget(self._build_form_panel(), 1)
        outer.addLayout(body, 1)

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

        top = QHBoxLayout()
        top.setSpacing(6)
        region_btn = QPushButton("디버프 줄 영역 지정")
        region_btn.clicked.connect(self._pick_region)
        top.addWidget(region_btn, 1)
        self.lock_btn = QPushButton("오버레이 고정")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setStyleSheet(
            "QPushButton:checked { background:#00B894; color:white; font-weight:600; }"
        )
        self.lock_btn.toggled.connect(self._on_lock_toggled)
        top.addWidget(self.lock_btn, 1)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setPrefix("배율 ")
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(config.load_overlay_scales()[1])
        self.scale_spin.valueChanged.connect(self._on_scale)
        top.addWidget(self.scale_spin, 1)
        v.addLayout(top)

        self.region_hint = hint_label("")
        self._update_region_hint()
        v.addWidget(self.region_hint)

        self.status_label = hint_label("")  # 진단 상태(추적 중/게임 비활성 등)
        v.addWidget(self.status_label)

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

    def _on_scale(self, pct: int) -> None:
        config.set_debuff_scale(pct)
        self.scale_changed.emit(pct)

    def set_status(self, text: str, color: str) -> None:
        """진단 상태 한 줄 갱신(메인의 주기 폴링에서 호출)."""
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};")

    # ---- 영역 지정 / 고정 ----
    def _update_region_hint(self) -> None:
        region = config.load_capture_region("debuffTracker")
        if region:
            self.region_hint.setText(
                f"영역: {region['x']},{region['y']}  "
                f"{region['w']}×{region['h']}  ✔"
            )
            self.region_hint.setStyleSheet("color:#2ecc71;")
        else:
            self.region_hint.setText(
                "영역 미지정 — 버튼으로 디버프 줄 영역을 지정하세요"
            )
            self.region_hint.setStyleSheet("color:#8a8f98;")

    def _pick_region(self) -> None:
        from .region_selector import RegionSelector

        self._selector = RegionSelector()  # 참조 유지(GC 방지)
        self._selector.selected.connect(self._on_region_selected)
        self._selector.start()

    def _on_region_selected(self, x: int, y: int, w: int, h: int) -> None:
        config.save_capture_region(x, y, w, h, "debuffTracker")
        self._update_region_hint()
        self.catalog_changed.emit()  # 영역 생기면 추적 (재)시작

    def _on_lock_toggled(self, locked: bool) -> None:
        self.lock_btn.setText("오버레이 고정됨" if locked else "오버레이 고정")
        self.lock_toggled.emit(locked)

    def set_lock_state(self, locked: bool) -> None:
        self.lock_btn.blockSignals(True)
        self.lock_btn.setChecked(locked)
        self.lock_btn.blockSignals(False)
        self._on_lock_toggled(locked)

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
            icon_dir=USER_DEBUFF_ICON_DIR,
            image_dir=USER_DEBUFF_ICON_DIR,
        )
        self._catalog = {b.id: b for b in available_debuff_catalog()}
        self._settings, self._order = self._load_state()
        self._settings[new_id].name = "-"
        self._current = new_id
        self._save()
        self._rebuild_list()
        self.catalog_changed.emit()

    def _on_delete(self) -> None:
        did = self._current_id()
        if did is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("디버프 삭제")
        is_default = did in catalog_mod.default_debuff_ids()
        box.setText(
            f"'{did}' 기본 디버프를 목록에서 뺄까요?\n(배포돼도 계속 숨겨집니다)"
            if is_default
            else f"'{did}' 디버프를 삭제할까요?\n(매칭 아이콘 파일이 삭제됩니다)"
        )
        yes = box.addButton("예", QMessageBox.ButtonRole.YesRole)
        box.addButton("아니오", QMessageBox.ButtonRole.NoRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        if is_default:
            config.add_removed_default(did, "debuffTracker")
        catalog_mod.delete_buff(did, dirs=catalog_mod.DEBUFF_DELETE_DIRS)
        self._settings.pop(did, None)
        if did in self._order:
            self._order.remove(did)
        self._current = None
        self._reload()

    def _reload(self, select: str | None = None) -> None:
        self._catalog = {b.id: b for b in available_debuff_catalog()}
        self._settings, self._order = self._load_state()
        self._current = select
        self._save()
        self._rebuild_list()
        self.catalog_changed.emit()

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
        self.tracking_changed.emit()

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
        self.match_capture_btn = QPushButton("영역에서 가져오기")
        self.match_capture_btn.setToolTip(
            "화면에서 아이콘을 드래그로 집어 매칭 아이콘으로 저장(돋보기 지원)"
        )
        self.match_capture_btn.clicked.connect(self._capture_match_icon)
        match_row.addWidget(self.match_capture_btn)
        file_btn = QPushButton("파일 선택")
        file_btn.clicked.connect(self._pick_match_icon)
        match_row.addWidget(file_btn)
        match_row.addStretch(1)
        v.addLayout(match_row)

        v.addSpacing(6)
        self.display_check = checkbox("오버레이에 표시")
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
        self.tracking_changed.emit()

    def _save_name(self) -> None:
        if self._loading or self._name_id is None:
            return
        s = self._settings.get(self._name_id)
        if s is None or s.name == self.name_edit.text().strip():
            return
        s.name = self.name_edit.text().strip()
        self._save()
        self._rebuild_list()
        self.tracking_changed.emit()

    def _pick_match_icon(self) -> None:
        did = self._current
        if did is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "매칭 아이콘 선택", "", "이미지 (*.png)"
        )
        if not path:
            return
        catalog_mod.set_match_icon(did, Path(path), icon_dir=USER_DEBUFF_ICON_DIR)
        self._reload(select=did)

    def _capture_match_icon(self) -> None:
        """화면에서 아이콘을 드래그로 집어(돋보기 지원) 매칭 아이콘으로 저장."""
        did = self._current
        if did is None:
            return
        _capture_icon_to(self, did, self._on_match_captured)

    def _on_match_captured(self, did: str, tmp: Path, ok: bool) -> None:
        if not ok or not tmp.exists():
            return
        catalog_mod.set_match_icon(did, tmp, icon_dir=USER_DEBUFF_ICON_DIR)
        self._reload(select=did)

    def _set_slot(self, slot, path: Path | None, placeholder: str) -> None:
        pm = _pixmap(path, 40)
        if pm is not None:
            slot.setPixmap(pm)
        else:
            slot.setText(placeholder)
