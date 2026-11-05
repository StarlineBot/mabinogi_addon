"""전투 보조 › 보스의 '보스바 오버레이' 구역(보스바 오버레이 명세, **제작자 테스트**).

제작자(`feature_access.is_creator()`)에게만 보인다. 다른 사용자는 구역·판독 추가·오버레이가 전혀 없다.

흐름(코드 → 동작):
- 켜면 보스 탭에 `set_bar_overlay`로 연결 → 보스 탭 작업 스레드(0.3초)가 등록 영역을 위아래로 조금 늘려 한 번 찍고,
  등록 보스는 숫자 칸 판독, 미등록 보스는 존재 확인에서 이미 읽는 %를 넘긴다(높이·한 칸 위 보스바 확인 포함).
- 화면 스레드는 받은 값을 `tracker.boss_bar_value`(오르는 값 2회 확인·못 읽으면 흐림→1.8초 뒤 숨김)에 넣고,
  그릴 내용이 바뀔 때만 오버레이를 다시 그린다.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout

from .. import config
from ..tracker.boss_bar_value import BossBarValue
from .widgets import hint_label, switch


class BossBarSection(QGroupBox):
    def __init__(self, boss_tab, parent=None) -> None:
        super().__init__("보스바 오버레이 (제작자 테스트)", parent)
        self._tab = boss_tab
        self._cfg = config.load_boss_bar_overlay()
        self.value = BossBarValue()
        self._overlay = None
        self._paused = False
        self._shutting_down = False
        self._allowed = None

        v = QVBoxLayout(self)
        v.addWidget(hint_label("보스 체력 %를 읽어 원하는 자리에 보스 체력바를 따로 그려요. 못 읽으면 흐리게 두었다가 숨겨요."))
        self.enable = switch("보스바 오버레이 사용")
        self.enable.setChecked(self._cfg["enabled"])
        self.enable.toggled.connect(self._on_enable)
        v.addWidget(self.enable)
        opts = QHBoxLayout()
        opts.addWidget(QLabel("배율"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(self._cfg["scale"])
        self.scale_spin.valueChanged.connect(self._on_scale)
        opts.addWidget(self.scale_spin)
        opts.addWidget(QLabel("불투명도"))
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(30, 100)
        self.opacity_spin.setSingleStep(5)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.setValue(self._cfg["opacity"])
        self.opacity_spin.valueChanged.connect(self._on_opacity)
        opts.addWidget(self.opacity_spin)
        from .settings_layout import lock_button
        self.lock_btn = lock_button(self._cfg["locked"])
        self.lock_btn.clicked.connect(self._on_lock)
        opts.addWidget(self.lock_btn)
        opts.addStretch(1)
        v.addLayout(opts)
        if not self.allowed():
            self.hide()  # 제작자가 아니면 처음부터 숨김(부모에 붙기 전이라 show는 하지 않는다)

        boss_tab.set_bar_overlay(self.wanted, self.feed)
        self._timer = QTimer(self)
        self._timer.setInterval(250)  # 보이기·숨김 시각만(가벼움) — 판독은 보스 탭 작업 스레드
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---- 상태 ----
    def allowed(self) -> bool:
        """제작자만. 설정 파일 읽기라 1초 재사용(feature_access.Recheck)."""
        if self._allowed is None:
            from .. import feature_access
            self._allowed = feature_access.Recheck(lambda: feature_access.is_creator())
        return bool(self._allowed())

    def wanted(self) -> bool:
        """보스 탭이 오버레이용 판독(늘린 캡처·존재 확인 %)을 할지. 작업 스레드 계획 단계(화면 스레드)에서 부른다."""
        return not self._shutting_down and not self._paused and self._cfg["enabled"] and self.allowed()

    def _game_active(self) -> bool:
        try:
            return bool(self._tab._watcher.is_game_active())
        except Exception:  # noqa: BLE001
            return False

    def _display_active(self) -> bool:
        """표시는 다른 오버레이 탭과 같은 규칙: 게임이 앞이거나, 우리 앱이 앞이고(구역이 보이거나·고정 해제 중이거나·끄는 중).
        오버레이를 누르면 같은 프로세스인 우리 창이 앞이 된다 — 그때 숨기면 끌기가 끊긴다."""
        if self._game_active():
            return True
        try:
            self_active = bool(self._tab._watcher.is_self_active())
        except Exception:  # noqa: BLE001
            self_active = False
        dragging = self._overlay is not None and getattr(self._overlay, "_drag", None) is not None
        return self_active and (self.isVisible() or not self._cfg["locked"] or dragging)

    # ---- 판독 반영(화면 스레드) ----
    def feed(self, reading: dict):
        """판독 한 번 반영. 그린 상태(Shown)를 돌려준다(보스 탭 수집이 표시값·이유 태그로 씀). 꺼져 있으면 None."""
        if not self.wanted():
            return None
        value = reading.get("value") if reading.get("seen") else None
        shown = self.value.update(value, reading.get("boss"), time.monotonic())
        # 소수는 표시용: 이번 판독 정수가 그린 값과 같고 흐림이 아닐 때만(값 규칙은 정수 기준, 틀린 소수 금지)
        self._frac = reading.get("frac") if (value is not None and shown.value == value and not shown.stale) else None
        self._show(shown)
        return shown

    def _show(self, shown=None) -> None:
        shown = shown or self.value.shown()
        visible = self.wanted() and self._display_active() and (shown.value is not None or not self._cfg["locked"])
        if not visible:
            if self._overlay is not None and self._overlay.isVisible():
                self._overlay.hide()
            return
        ov = self._ensure_overlay()
        boss = self._tab._bosses.get(shown.boss) if shown.boss else None
        frac = getattr(self, "_frac", None) if not shown.stale else None
        ov.set_state(boss.name if boss else "보스", shown.value, shown.stale, boss.thresholds if boss else (), frac)
        if not ov.isVisible():
            ov.show()

    def _tick(self) -> None:
        allowed = self.allowed()
        if self.isHidden() == allowed:  # 로그인이 바뀌면 다음 틱에 반영
            self.setVisible(allowed)
        if not self.wanted() or not self._display_active():
            self.value.reset()
        else:
            self.value.tick(time.monotonic())  # 판독이 멈춰도(영역 없음 등) 1.8초 뒤 숨김
        self._show()

    # ---- 오버레이 ----
    def _ensure_overlay(self):
        if self._overlay is None:
            from .boss_bar_overlay import BossBarOverlay
            ov = BossBarOverlay(self._cfg["scale"])
            ov.set_opacity(self._cfg["opacity"])
            ov.set_locked(self._cfg["locked"])
            pos = self._cfg.get("pos")
            if pos:
                ov.move(pos["x"], pos["y"])
            else:
                self._default_position(ov)
            ov.moved.connect(lambda: self._save(pos={"x": ov.x(), "y": ov.y()}))
            self._overlay = ov
        return self._overlay

    @staticmethod
    def _default_position(ov) -> None:
        """처음 위치: 화면 위쪽 가운데(게임 보스바는 아래쪽) — 화면 좌표로 저장."""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.geometry()
            ov.move(g.x() + (g.width() - ov.width()) // 2, g.y() + int(g.height() * 0.12))

    # ---- 옵션 ----
    def _save(self, **data) -> None:
        self._cfg.update(data)
        config.save_boss_bar_overlay(data)

    def _on_enable(self, on: bool) -> None:
        self._save(enabled=bool(on))
        self.value.reset()
        self._show()

    def _on_scale(self, value: int) -> None:
        self._save(scale=int(value))
        if self._overlay is not None:
            self._overlay.set_scale(value)

    def _on_opacity(self, value: int) -> None:
        self._save(opacity=int(value))
        if self._overlay is not None:
            self._overlay.set_opacity(value)

    def _on_lock(self) -> None:
        locked = not self._cfg["locked"]
        self._save(locked=locked)
        from .settings_layout import set_lock_text
        set_lock_text(self.lock_btn, locked)
        if self._overlay is not None:
            self._overlay.set_locked(locked)
        self._show()

    # ---- 메인 연동 ----
    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if paused:
            self.value.reset()
        self._show()

    def shutdown(self) -> None:
        self._shutting_down = True
        self._timer.stop()
        if self._overlay is not None:
            self._overlay.close()
