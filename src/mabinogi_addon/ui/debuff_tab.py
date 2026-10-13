"""디버프 탭 (기획서 5.1 하단 / 3.2).

버프 탭과 같은 관리 방식이되 더 단순하다: 이름, 매칭 아이콘(파일 선택), 오버레이 노출.
지속시간·알림·앵커 없음. 목록·설정은 debuffTracker 섹션에 저장.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
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

# 영역에 꼭 들어가야 하는 것(앱 힌트 ↔ 화면 점선 라벨이 같은 기준을 공유).
REGION_CRITERION = "디버프 아이콘 줄이 점선 안에 들어오게 드래그하세요"
HIGHLIGHT_TITLE = "디버프 영역 확인"
HIGHLIGHT_SUB = "디버프 아이콘이 점선 안에 다 들어왔나요?"

# 디버프 트래커 사용법(? 아이콘 → 새 창).
HELP_TITLE = "디버프 트래커 사용법"
HELP_HTML = """
<h3>디버프 트래커란?</h3>
<p>보스 체력바 위의 <b>디버프 줄</b>을 읽어, 아직 걸지 않은 디버프를
화면 위 오버레이로 보여줍니다. 화면을 <b>읽기만</b> 하며 키 입력·클릭은 하지 않습니다.</p>

<h3>사용 순서</h3>
<ol>
<li><b>디버프 줄 영역 지정</b> — 보스 체력바 위, 디버프가 표시되는 영역을 먼저
드래그로 잡습니다. (돋보기로 픽셀 단위 조정)
<br><b>※ 영역을 아래로 넓혀 보스 체력바까지 포함</b>하면, 체력바가 보일 때만
탐지해 <b>마을·풀밭 오탐이 사라집니다</b>(선택). 안 넣으면 지금처럼 동작합니다.</li>
<li><b>디버프 등록 (＋)</b> — 보고 싶은 디버프를 추가하고, 그 아이콘을
<b>영역에서 바로 집거나</b> 이미지 파일로 등록합니다.
(－ 삭제 / ▲▼ 표시 순서)</li>
<li><b>오버레이 배치</b> — 드래그로 원하는 위치에 옮기고 마우스 휠로 <b>배율</b>을
조절합니다. <b>위치 잠금</b>을 누르면 위치가 고정되고 클릭도 통과해
게임에 방해되지 않습니다.</li>
</ol>

<p>※ 디버프는 <b>아직 걸리지 않은 것</b>만 오버레이에 나열됩니다.</p>
"""


class DebuffTab(QWidget):
    lock_toggled = Signal(bool)  # 디버프 오버레이 고정 토글
    tracking_changed = Signal()  # 순서·노출 변경 → 라이브 반영
    catalog_changed = Signal()  # 디버프 추가·삭제·아이콘 변경 → 엔진 재구성
    scale_changed = Signal(int)  # 디버프 오버레이 배율(%) 변경
    gate_mode_changed = Signal(str)  # 탐지 방식(1/2/3차) 변경 또는 바 영역 변경 → 재시작
    bar_region_changed = Signal()  # 보스 HP바 영역 지정 → 보스패턴알림도 반영(공유)

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
        # 메인이 부팅 때 effective_gate_mode()로 엔진을 만드므로, 첫 showEvent가 불필요하게
        # 재시작하지 않도록 마지막 통지값을 현재 실제 방식으로 맞춰둔다.
        self._last_effective = self.effective_gate_mode()

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
        shown = [self._settings[i] for i in self._order]
        # 아이콘이 (일시적으로) 없어 목록에 없는 설정도 보존한다. 업데이트 중 카탈로그가
        # 잠깐 비어도 자동저장이 사용자의 디버프를 영구 삭제하지 않도록(아이콘이 다시
        # 생기면 그대로 복원). 삭제(－)는 self._settings에서 직접 빼므로 의도대로 사라진다.
        others = [s for i, s in self._settings.items() if i not in self._order]
        config.save_debuff_settings([*shown, *others])

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
        self.lock_btn = QPushButton("위치 잠금")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setToolTip(
            "잠그면 오버레이 위치가 고정되고, 클릭이 통과돼 게임을 가리지 않습니다.\n"
            "해제하면 드래그로 위치를 옮길 수 있어요."
        )
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

        hint_row = QHBoxLayout()
        hint_row.setSpacing(6)
        self.region_hint = hint_label("")
        hint_row.addWidget(self.region_hint, 1)
        self.view_region_btn = QPushButton("영역 보기")
        self.view_region_btn.setToolTip("잡힌 영역을 화면에 점선으로 잠깐 표시")
        self.view_region_btn.clicked.connect(self._flash_region)
        hint_row.addWidget(self.view_region_btn)
        self.auto_find_btn = QPushButton("🧪 자동 찾기")
        self.auto_find_btn.setToolTip(
            "보스 체력바를 찾아 그 위 디버프 영역을 자동 지정 — Discord 베타"
        )
        self.auto_find_btn.clicked.connect(self._on_auto_find)
        hint_row.addWidget(self.auto_find_btn)
        self._update_region_hint()
        v.addLayout(hint_row)

        self.status_label = hint_label("")  # 진단 상태(추적 중/게임 비활성 등)
        v.addWidget(self.status_label)

        # 탐지 방식: 1차(항상 탐지·기본) / 2차(보스 바 인식·띠) / 3차(보스 바 %판독).
        # 2·3차는 베타 — 디코 로그인 필요.
        method_row = QHBoxLayout()
        method_row.setSpacing(6)
        method_row.addWidget(section_label("탐지 방식"))
        self.method_combo = QComboBox()
        for text, mode in (
            ("1차 · 항상 탐지 (기본)", "off"),
            ("2차 · 보스 바 인식 (띠)", "band"),
            ("3차 · 보스 바 %판독 (실험)", "percent"),
        ):
            self.method_combo.addItem(text, mode)
        self.method_combo.setToolTip(
            "1차: 항상 탐지(기존). 바닥 오탐이 있을 수 있으나 보스 바 인식에 비의존.\n"
            "2차: 디버프 영역 안의 '평평한 띠'로 보스가 있을 때만 탐지.\n"
            "3차: 보스 HP바 영역의 퍼센트 숫자를 읽어 보스가 있을 때만 탐지(가장 정확)."
        )
        cur = config.load_debuff_gate_mode()
        idx = self.method_combo.findData(cur)
        self.method_combo.blockSignals(True)
        self.method_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.method_combo.blockSignals(False)
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        method_row.addWidget(self.method_combo, 1)
        v.addLayout(method_row)

        # 3차용: 보스 HP바 영역 지정(보스패턴알림과 공유).
        self._bar_region_row = QWidget()
        brl = QHBoxLayout(self._bar_region_row)
        brl.setContentsMargins(0, 0, 0, 0)
        brl.setSpacing(6)
        self.bar_region_btn = QPushButton("보스 HP바 영역 지정")
        self.bar_region_btn.setToolTip(
            "보스 이름~퍼센트가 다 들어오게 HP바를 가로로 감싸 드래그하세요.\n"
            "보스패턴알림과 같은 영역을 공유합니다(한쪽에서 지정하면 양쪽이 사용)."
        )
        self.bar_region_btn.clicked.connect(self._pick_bar_region)
        brl.addWidget(self.bar_region_btn)
        self.bar_region_status = hint_label("")
        brl.addWidget(self.bar_region_status, 1)
        v.addWidget(self._bar_region_row)

        self._bar_gating_notice = hint_label(
            "🧪 개발 중인 기능 — 설정 탭에서 Discord 로그인 후 가장 먼저 써볼 수 있어요."
        )
        self._bar_gating_notice.setStyleSheet("color:#e67e22; font-size:12px;")
        v.addWidget(self._bar_gating_notice)
        self._apply_login_gate()
        self._refresh_method_ui()

        self.debuff_list = QListWidget()
        self.debuff_list.setIconSize(QSize(28, 28))
        self.debuff_list.currentRowChanged.connect(self._on_select)
        v.addWidget(self.debuff_list, 1)

        order_row = QHBoxLayout()
        order_row.setSpacing(4)
        add_btn = QPushButton("＋ 추가")
        add_btn.setToolTip("새 디버프 등록")
        add_btn.clicked.connect(self._on_register)
        del_btn = QPushButton("－ 삭제")
        del_btn.setToolTip("선택한 디버프 삭제")
        del_btn.clicked.connect(self._on_delete)
        up_btn = QPushButton("▲")
        up_btn.setToolTip("위로 (표시 순서)")
        up_btn.clicked.connect(lambda: self._move(-1))
        down_btn = QPushButton("▼")
        down_btn.setToolTip("아래로 (표시 순서)")
        down_btn.clicked.connect(lambda: self._move(1))
        for b in (add_btn, del_btn, up_btn, down_btn):
            order_row.addWidget(b, 1)
        v.addLayout(order_row)
        return panel

    def _on_scale(self, pct: int) -> None:
        config.set_debuff_scale(pct)
        self.scale_changed.emit(pct)

    # ---- 탐지 방식(1/2/3차) ----
    @staticmethod
    def _logged_in() -> bool:
        return config.load_discord_user() is not None

    def _selected_mode(self) -> str:
        return self.method_combo.currentData() or "off"

    def effective_gate_mode(self) -> str:
        """실제 적용할 방식. 2·3차는 베타라 디코 로그인 없으면 1차(off)로 내린다."""
        mode = self._selected_mode()
        if mode in ("band", "percent") and not self._logged_in():
            return "off"
        return mode

    def _apply_login_gate(self) -> None:
        """베타: 디코 로그인 사용자만 2·3차를 고를 수 있게 한다(미로그인=선택 잠금)."""
        ok = self._logged_in()
        self.method_combo.setEnabled(ok)
        # 미로그인인데 2·3차가 선택돼 있으면 안내를 띄운다(선택은 보존, 적용은 1차).
        self._bar_gating_notice.setVisible(not ok and self._selected_mode() != "off")

    def _bar_region_status_text(self) -> tuple[str, str]:
        r = config.load_boss_bar_region()
        if r:
            return f"공유됨 ✓  {r['w']}×{r['h']}", "#2ecc71"
        return "미지정 — 보스 HP바 영역을 지정하세요", "#e67e22"

    def _refresh_method_ui(self) -> None:
        """선택 방식에 맞게 3차용 바 영역 행 표시/숨김 + 상태 갱신."""
        is_percent = self._selected_mode() == "percent"
        self._bar_region_row.setVisible(is_percent and self._logged_in())
        if is_percent:
            txt, color = self._bar_region_status_text()
            self.bar_region_status.setText(txt)
            self.bar_region_status.setStyleSheet(f"color:{color}; font-size:12px;")

    def _emit_gate_mode(self) -> None:
        """현재 실제 방식을 엔진 쪽에 통지(재시작)하고, 마지막 통지값을 기록."""
        self._last_effective = self.effective_gate_mode()
        self.gate_mode_changed.emit(self._last_effective)

    def _on_method_changed(self, _idx: int) -> None:
        config.save_debuff_gate_mode(self._selected_mode())
        self._apply_login_gate()
        self._refresh_method_ui()
        self._emit_gate_mode()

    def _pick_bar_region(self) -> None:
        from .region_selector import RegionSelector

        self._bar_selector = RegionSelector()  # 참조 유지(GC 방지)
        self._bar_selector.selected.connect(self._on_bar_region_selected)
        self._bar_selector.start()

    def _on_bar_region_selected(self, x: int, y: int, w: int, h: int) -> None:
        config.save_boss_bar_region(x, y, w, h)  # 보스패턴알림과 공유 저장
        self._refresh_method_ui()
        from .region_highlight import RegionHighlight

        self._bar_highlight = RegionHighlight()  # 참조 유지
        self._bar_highlight.flash(x, y, w, h, "보스 HP바 영역", "이름~퍼센트가 다 들어왔나요?")
        self._emit_gate_mode()  # 새 영역으로 디버프 3차 재시작(영역이 실제로 바뀜)
        self.bar_region_changed.emit()  # 보스패턴알림도 새 영역 반영(양방향 공유)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        super().showEvent(event)
        # 탭이 보일 때 로그인 상태·공유 영역 표시만 갱신한다. 재시작(gate_mode_changed)은
        # '실제 방식이 바뀌었을 때만' — 매번 재시작하면 디버프가 0.3초 깜빡이고 사라짐 경고
        # 대기가 취소되며 바 캡처 소스가 새로 열린다(누수·끊김). 로그아웃으로 effective가
        # 내려간 경우 등 변화가 있을 때만 통지한다.
        self._apply_login_gate()
        self._refresh_method_ui()
        if self.effective_gate_mode() != self._last_effective:
            self._emit_gate_mode()

    def set_status(self, text: str, color: str) -> None:
        """진단 상태 한 줄 갱신(메인의 주기 폴링에서 호출)."""
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};")

    # ---- 영역 지정 / 고정 ----
    def refresh_region_hint(self) -> None:
        """외부(보스 탭 자동 찾기 등)에서 디버프 영역이 바뀐 뒤 표시를 갱신한다."""
        self._update_region_hint()

    def _update_region_hint(self) -> None:
        region = config.load_capture_region("debuffTracker")
        if region:
            self.region_hint.setText(
                f"영역: {region['x']},{region['y']}  "
                f"{region['w']}×{region['h']}  ✔"
            )
            self.region_hint.setStyleSheet("color:#2ecc71;")
            self.view_region_btn.setEnabled(True)
        else:
            self.region_hint.setText(f"영역 미지정 — {REGION_CRITERION}")
            self.region_hint.setStyleSheet("color:#8a8f98;")
            self.view_region_btn.setEnabled(False)

    def _pick_region(self) -> None:
        from .region_selector import RegionSelector

        self._selector = RegionSelector()  # 참조 유지(GC 방지)
        self._selector.selected.connect(self._on_region_selected)
        self._selector.start()

    def _on_region_selected(self, x: int, y: int, w: int, h: int) -> None:
        config.save_capture_region(x, y, w, h, "debuffTracker")
        self._update_region_hint()
        self._flash_region()  # 잡힌 영역을 화면에 점선으로 바로 확인
        self.catalog_changed.emit()  # 영역 생기면 추적 (재)시작

    def _on_auto_find(self) -> None:
        """보스 체력바를 찾아 그 위 디버프 영역을 자동 지정(Discord 베타). 확인 후에만 저장."""
        if not self._logged_in():
            QMessageBox.information(
                self,
                "자동 찾기 — 베타",
                "자동 찾기는 Discord 로그인 사용자만 쓸 수 있는 베타 기능입니다.\n"
                "설정 탭에서 로그인한 뒤 사용하세요.",
            )
            return
        from ..detect.boss_bar import locate_boss_bar, make_validator
        from .dpi import to_logical
        from .screen_grab import capture_for_autofind

        frame, ox, oy = capture_for_autofind()  # 앱 창 숨기고 캡처
        if frame is None:
            QMessageBox.warning(self, "자동 찾기", "화면 캡처에 실패했습니다.")
            return
        box = locate_boss_bar(frame, make_validator())  # 판독 검증 통과한 박스만
        if box is None:
            QMessageBox.information(
                self,
                "자동 찾기 — 못 찾음",
                "디버프 영역의 기준인 보스 체력바를 찾지 못했습니다.\n\n"
                "• 보스 체력바가 지금 화면에 노출돼 있나요? (보스전 중 시도)\n"
                "• 하단 메뉴바가 최소화돼 있지 않나요?\n\n"
                "다시 시도하거나 '디버프 줄 영역 지정'으로 직접 잡으세요.",
            )
            return
        x, y, w, h = box
        # 전역 물리픽셀 → 논리좌표.
        lx, ly, lw, lh = to_logical(x + ox, y + oy, w, h)
        strip = max(12, int(lh * 1.4))  # 디버프 띠 높이
        dy = max(0, ly - strip)
        # 디버프 영역 = 띠 + 보스바(dy ~ 바 아래). 바 포함해야 사라짐 경고·2차(띠) 동작.
        db = (lx, dy, lw, (ly + lh) - dy)
        from .region_highlight import RegionHighlight

        self._highlight = RegionHighlight()
        self._highlight.flash(
            db[0], db[1], db[2], db[3], "자동 찾기 결과",
            "디버프 영역 + 보스 HP바(3차 판독용) — 이 영역으로 지정할까요?", msec=4000,
        )
        ans = QMessageBox.question(
            self,
            "자동 찾기 — 확인",
            "민트 점선 영역으로 **디버프 영역 + 보스 HP바 영역**을 지정할까요?\n\n"
            "(디버프 3차 판독은 보스 HP바 영역도 필요해 함께 지정합니다.)\n"
            "'아니오'를 누르면 기존 설정이 그대로 유지됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        # 디버프 영역(띠+바) 저장 + 추적 재시작
        config.save_capture_region(db[0], db[1], db[2], db[3], "debuffTracker")
        self._update_region_hint()
        self.catalog_changed.emit()
        # 디버프 3차가 쓰는 보스 HP바 영역도 함께 저장(공유) + 3차 재시작
        config.save_boss_bar_region(lx, ly, lw, lh)
        self._refresh_method_ui()
        self._emit_gate_mode()
        self.bar_region_changed.emit()

    def _flash_region(self) -> None:
        """저장된 디버프 영역을 화면에 굵은 점선으로 잠깐 표시(아이콘 확인용)."""
        region = config.load_capture_region("debuffTracker")
        if not region:
            return
        from .region_highlight import RegionHighlight

        self._highlight = RegionHighlight()  # 참조 유지(GC 방지)
        self._highlight.flash(
            region["x"], region["y"], region["w"], region["h"],
            HIGHLIGHT_TITLE, HIGHLIGHT_SUB,
        )

    def _on_lock_toggled(self, locked: bool) -> None:
        self.lock_btn.setText("위치 잠금됨" if locked else "위치 잠금")
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
        v.setSpacing(10)

        # --- 그룹 1: 아이콘(이름 + 매칭 아이콘) ---
        icon_box = QGroupBox("아이콘")
        iv = QVBoxLayout(icon_box)
        iv.setSpacing(6)
        iv.addWidget(section_label("이름"))
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._save_name)
        iv.addWidget(self.name_edit)

        iv.addWidget(section_label("매칭 아이콘"))
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
        iv.addLayout(match_row)
        v.addWidget(icon_box)

        # --- 그룹 2: 표시 ---
        show_box = QGroupBox("표시")
        sv = QVBoxLayout(show_box)
        sv.setSpacing(6)
        self.display_check = checkbox("오버레이에 표시")
        self.display_check.toggled.connect(self._form_changed)
        sv.addWidget(self.display_check)
        sv.addWidget(
            hint_label("디버프는 '아직 걸리지 않은 것'만 오버레이에 나열됩니다.")
        )
        self.warn_gone_check = checkbox("사라짐 경고 (보스에서 떨어지면 알림)")
        self.warn_gone_check.setToolTip(
            "걸어둔 디버프가 보스에서 떨어지면 오버레이에 빨간 테두리+X로 표시하고 "
            "소리로 알려요.\n※ 영역에 보스 체력바가 보여야 작동합니다."
        )
        self.warn_gone_check.toggled.connect(self._form_changed)
        sv.addWidget(self.warn_gone_check)
        self.bar_status = hint_label("")
        sv.addWidget(self.bar_status)
        v.addWidget(show_box)

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
        self.warn_gone_check.setChecked(s.alert.warn_gone)
        self._loading = False

    def _form_changed(self) -> None:
        if self._loading or self._current is None:
            return
        s = self._settings[self._current]
        s.hidden = not self.display_check.isChecked()
        s.alert.warn_gone = self.warn_gone_check.isChecked()
        self._save()
        self.tracking_changed.emit()

    def set_bar_status(self, seen: bool) -> None:
        """사라짐 경고 가능 여부(영역에 보스 체력바가 인식됐는지)를 안내."""
        if seen:
            self.bar_status.setText("✓ 보스 체력바 인식됨 — 사라짐 경고 작동")
            self.bar_status.setStyleSheet("color:#2ecc71; font-size:12px;")
        else:
            self.bar_status.setText(
                "체력바가 안 보여요 — 사라짐 경고를 쓰려면 영역에 보스 체력바를 포함하세요."
            )
            self.bar_status.setStyleSheet("color:#e67e22; font-size:12px;")

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
