"""보스 패턴 경고 탭 (기획서 12). **베타 — 디스코드 로그인 사용자만.**

보스 HP바 영역을 한 번 지정하면, 그 안에서 왼쪽=이름 / 오른쪽=HP%를 읽어:
- 실시간으로 '식별된 보스 + 현재 HP%'를 표시(판독이 잘 되는지 눈으로 확인용)
- HP%가 임계의 T+5(1차)/T+1(2차)를 하강 교차하면 화면 중앙 큰 글씨 경고 + 소리

패턴 데이터(보스 이름 템플릿 + 임계%)는 번들(assets/boss). 투아림 탭과 같은 영역·캡처
방식이다.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config, paths
from ..detect.boss_hp_reader import read_percent
from ..detect.boss_name_matcher import identify, load_name_templates
from ..tracker.boss_catalog import load_bosses, make_tracker
from .pattern_overlay import PatternWarningOverlay
from .upcoming_overlay import UpcomingPatternsOverlay
from .widgets import checkbox, hint_label

_SOUND_DIR = paths.resource_dir() / "sounds"
_PRE_SOUND = _SOUND_DIR / "보스패턴 예고.mp3"
_NEAR_SOUND = _SOUND_DIR / "보스패턴 진입.mp3"

HIGHLIGHT_TITLE = "보스 HP바 영역"
HIGHLIGHT_SUB = "보스 이름 ~ HP% 가 다 들어오게"

# 기본 영역(2560×1440 기준, 하단 중앙 보스 HP바). 오른쪽 끝 = 바 오른쪽 끝.
# 다른 해상도면 '영역 수정'으로 바에 맞춘다(판독기가 박스 높이로 스케일 보정).
DEFAULT_BOX = {"x": 1017, "y": 1248, "w": 523, "h": 36}


class BossTab(QWidget):
    def __init__(self, watcher) -> None:
        super().__init__()
        self._watcher = watcher
        cfg = config.load_boss_pattern()
        # 기본으로 바 위치가 이미 잡힌 상태(사용자 해상도 2560×1440면 바로 작동).
        # 해상도가 다르면 '영역 수정'으로 맞춘다.
        self._region = cfg["box"] or dict(DEFAULT_BOX)
        self._sct = None
        self._last_frame = None
        self._bosses = load_bosses()
        self._name_templates = load_name_templates()
        self._tracker = None
        self._cur_boss: str | None = None
        self._stable_hp: int | None = None
        self._hp_cand: int | None = None  # 확정 대기 후보값
        self._hp_cand_n = 0  # 후보 연속 횟수
        self._unidentified = 0  # 이름이 연속으로 안 읽힌 프레임 수(보스 사라짐 판정)
        self._overlay = PatternWarningOverlay()
        self._overlay.moved.connect(self._on_warn_moved)
        self._notifier = None
        # 다음 패턴 목록 오버레이(왼쪽에 남은 패턴 % 나열). 위치/고정은 설정에 저장.
        self._upcoming = UpcomingPatternsOverlay()
        self._upcoming.moved.connect(self._on_upcoming_moved)
        self._upcoming.set_locked(cfg["upcomingLocked"])
        if cfg["upcomingPos"]:
            self._upcoming.move(
                int(cfg["upcomingPos"]["x"]), int(cfg["upcomingPos"]["y"])
            )
        else:
            self._place_upcoming_default()
        # 경고 오버레이 위치/고정 복원(목록과 동일 구조). 저장 위치 없으면 기본(상단 중앙).
        if cfg["warnPos"]:
            self._overlay.move(int(cfg["warnPos"]["x"]), int(cfg["warnPos"]["y"]))
        else:
            self._place_warn_default()
        self._overlay.set_locked(cfg["warnLocked"])

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)

        title = QLabel("보스 패턴 알림  ·  [BETA]")
        title.setStyleSheet("font-size:14px; font-weight:700;")
        v.addWidget(title)
        v.addWidget(
            hint_label(
                "보스 HP%가 패턴 진입점에 다가오면 화면 중앙에 크게 알립니다. "
                "각 %의 5% 전(예고)과 1% 전(진입), 두 번 알려요."
            )
        )
        v.addWidget(self._supported_label())

        prev_btn = QPushButton("경고 위치 미리보기")
        prev_btn.setToolTip("경고가 화면 어디에 어떻게 뜨는지 한 번 띄워 봅니다")
        prev_btn.clicked.connect(self._preview_warning)
        v.addWidget(prev_btn)

        # 디스코드 로그인 안내(게이트) — 미로그인 시만 보임
        self._gate = hint_label(
            "🔒 디스코드 로그인 하면 사용할 수 있는 [BETA] 기능이에요. (설정 탭에서 로그인)"
        )
        self._gate.setStyleSheet("color:#e67e22; font-size:12px;")
        v.addWidget(self._gate)

        # 실제 컨트롤 묶음(로그인 시만 보임)
        self._controls = QWidget()
        cv = QVBoxLayout(self._controls)
        cv.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self.region_btn = QPushButton("보스 영역 수정")
        self.region_btn.setToolTip(
            "기본 위치(2560×1440)로 이미 잡혀 있습니다. 해상도가 다르거나 안 맞으면 "
            "눌러서 보스 HP바(이름~%)에 박스를 맞춥니다."
        )
        self.region_btn.clicked.connect(self._on_region)
        row.addWidget(self.region_btn)
        self.region_label = hint_label("")
        row.addWidget(self.region_label, 1)
        self.view_region_btn = QPushButton("영역 보기")
        self.view_region_btn.clicked.connect(self._flash_region)
        row.addWidget(self.view_region_btn)
        cv.addLayout(row)

        prev_row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedHeight(40)
        self.preview.setMinimumWidth(160)
        self.preview.setStyleSheet("background:#202227; border:1px solid #3a3d44;")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_row.addWidget(self.preview)
        self.status_label = QLabel("식별: —   HP: —")
        self.status_label.setStyleSheet("font-size:14px; font-weight:600;")
        prev_row.addWidget(self.status_label, 1)
        cv.addLayout(prev_row)

        self.enable = checkbox("보스 패턴 경고 사용")
        self.enable.setChecked(cfg["enabled"])
        self.enable.toggled.connect(self._save)
        cv.addWidget(self.enable)
        cv.addWidget(
            hint_label("영역을 맞춘 뒤 위의 '식별'과 'HP'가 실제와 맞는지 먼저 확인하세요.")
        )

        # 경고 위치 이동/고정(다음 패턴 목록과 동일 구조).
        warn_row = QHBoxLayout()
        self.warn_lock_btn = QPushButton()
        self.warn_lock_btn.clicked.connect(self._toggle_warn_lock)
        warn_row.addWidget(self.warn_lock_btn)
        warn_row.addWidget(
            hint_label("해제=끌어서 경고 위치 이동 · 고정=게임 위 표시(클릭 통과)"), 1
        )
        cv.addLayout(warn_row)
        self._sync_warn_btn()

        # 다음 패턴 목록(왼쪽에 남은 패턴 % 나열) — 준비(5% 전) 알림이 뜨면 그 %가 빠짐.
        self.show_upcoming = checkbox("다음 패턴 보기 (왼쪽에 남은 패턴 % 나열)")
        self.show_upcoming.setChecked(cfg["showUpcoming"])
        self.show_upcoming.toggled.connect(self._on_show_upcoming)
        cv.addWidget(self.show_upcoming)
        up_row = QHBoxLayout()
        self.upcoming_lock_btn = QPushButton()
        self.upcoming_lock_btn.clicked.connect(self._toggle_upcoming_lock)
        up_row.addWidget(self.upcoming_lock_btn)
        up_row.addWidget(
            hint_label("해제=끌어서 위치 이동 · 고정=게임 위 표시(클릭 통과)"), 1
        )
        cv.addLayout(up_row)
        self._sync_upcoming_btn()
        v.addWidget(self._controls)
        v.addStretch(1)

        self._update_region_label()
        self._apply_gate()
        self._timer = QTimer(self)
        self._timer.setInterval(300)  # HP는 천천히 변함 — 300ms면 충분
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _supported_label(self) -> QLabel:
        lines = ["지원 보스 & 알림 %:"]
        for b in self._bosses.values():
            if b.thresholds:
                pct = ", ".join(f"{t}%" for t in b.thresholds)
                lines.append(f"  • {b.name} — {pct}")
        lbl = hint_label("\n".join(lines))
        lbl.setStyleSheet("color:#9aa0aa; font-size:12px;")
        return lbl

    def _preview_warning(self) -> None:
        # 실제 경고처럼 소리까지 같이 내 어떻게 보이고 들리는지 보여준다. 위치 조정(해제)
        # 중이면 샘플이 이미 떠 있으므로 소리만 난다(show_message는 고정 상태에서만).
        self._overlay.show_message("고목의 페타크 85% 패턴 준비  (미리보기)", 2500)
        self._play("pre")

    # ---- 게이팅 ----
    @staticmethod
    def _logged_in() -> bool:
        return config.load_discord_user() is not None

    def _apply_gate(self) -> None:
        logged = self._logged_in()
        self._gate.setVisible(not logged)
        self._controls.setVisible(logged)

    # ---- 영역 지정 ----
    def _on_region(self) -> None:
        from .region_selector import RegionSelector

        # 보스 HP바는 넓은 가로 띠 → 자유 드래그로 이름~% 를 감싸게 그린다.
        self._selector = RegionSelector()
        self._selector.selected.connect(self._on_selected)
        self._selector.start()

    def _on_selected(self, x: int, y: int, w: int, h: int) -> None:
        self._region = {"x": x, "y": y, "w": w, "h": h}
        self._update_region_label()
        self._save()
        self._flash_region()

    def _flash_region(self) -> None:
        if not self._region:
            return
        from .region_highlight import RegionHighlight

        self._highlight = RegionHighlight()
        r = self._region
        self._highlight.flash(r["x"], r["y"], r["w"], r["h"], HIGHLIGHT_TITLE, HIGHLIGHT_SUB)

    def _update_region_label(self) -> None:
        if self._region:
            r = self._region
            self.region_label.setText(f"영역: {r['w']}×{r['h']}  ✓")
        else:
            self.region_label.setText("영역 미지정")

    def _save(self) -> None:
        config.save_boss_pattern(
            {
                "enabled": self.enable.isChecked(),
                "box": self._region,
                "showUpcoming": self.show_upcoming.isChecked(),
                "upcomingLocked": self._upcoming.locked,
                "warnLocked": self._overlay.locked,
            }
        )

    # ---- 경고 위치 ----
    def _place_warn_default(self) -> None:
        """기본 위치: 화면 상단 중앙(기존 경고 위치와 비슷하게)."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        g = screen.geometry()
        self._overlay._relayout()  # 샘플 크기로 폭 확정 후 중앙 정렬
        x = int((g.width() - self._overlay.width()) / 2)
        self._overlay.move(max(0, x), int(g.height() * 0.14))

    def _sync_warn_btn(self) -> None:
        self.warn_lock_btn.setText(
            "경고 위치 이동" if self._overlay.locked else "경고 위치 고정"
        )

    def _toggle_warn_lock(self) -> None:
        self._overlay.set_locked(not self._overlay.locked)
        self._sync_warn_btn()
        self._save()

    def _on_warn_moved(self) -> None:
        pos = self._overlay.pos()
        config.save_boss_pattern({"warnPos": {"x": pos.x(), "y": pos.y()}})

    # ---- 다음 패턴 목록 ----
    def _place_upcoming_default(self) -> None:
        """기본 위치: 화면 정중앙에서 왼쪽 1/4 지점, 세로 중간 위쪽."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        g = screen.geometry()
        self._upcoming.move(int(g.width() * 0.25), int(g.height() * 0.40))

    def _sync_upcoming_btn(self) -> None:
        self.upcoming_lock_btn.setText(
            "목록 위치 이동" if self._upcoming.locked else "목록 위치 고정"
        )

    def _on_show_upcoming(self, checked: bool) -> None:
        self._save()
        if not checked:
            self._upcoming.hide()

    def _toggle_upcoming_lock(self) -> None:
        self._upcoming.set_locked(not self._upcoming.locked)
        self._sync_upcoming_btn()
        self._save()

    def _on_upcoming_moved(self) -> None:
        pos = self._upcoming.pos()
        config.save_boss_pattern({"upcomingPos": {"x": pos.x(), "y": pos.y()}})

    def _update_upcoming(self, hp: int | None) -> None:
        """남은 패턴 목록을 오버레이에 반영. 고정 상태면 실제 남은 패턴이 있을 때만
        표시하고, 해제 상태면 위치 지정을 위해 항상 보인다(비면 샘플)."""
        if not self.show_upcoming.isChecked():
            self._upcoming.hide()
            return
        items = self._tracker.upcoming(hp) if self._tracker is not None else []
        self._upcoming.set_items(items)
        if self._upcoming.locked and not items:
            self._upcoming.hide()
        else:
            self._upcoming.show()
            self._upcoming.raise_()

    # ---- 읽기 루프 ----
    def _tick(self) -> None:
        self._apply_gate()
        if not self._logged_in():
            self._upcoming.hide()
            return
        active = self._watcher.is_game_active() or self._watcher.is_self_active()
        if not self._region or not active:
            self._upcoming.hide()
            return
        from .dpi import to_physical

        px, py, pw, ph = to_physical(self._region)
        frame = self._grab_rect(px, py, pw, ph)
        if frame is None:
            return
        self._show_preview(frame)
        self._last_frame = frame

        w = frame.shape[1]
        name_reg = frame[:, : int(w * 0.60)]  # 왼쪽=이름
        pct_reg = frame[:, int(w * 0.58) :]  # 오른쪽=HP%(가운데 빈 띠는 글자 없음)
        boss_id = identify(name_reg, self._name_templates)

        # 보스 식별/소멸 관리. **HP 판독·경고는 보스가 '이번 프레임' 식별됐을 때만**
        # 처리한다 — 보스가 없으면 영역이 길바닥/UI라 HP가 garbage로 읽히는데, 그걸
        # 트래커에 넣으면 옛 보스 경고가 거짓 발동한다(보스 없는데 40% 알림 버그).
        #  - 식별되면 그 보스 트래커로. 깜빡임으로 1~수 프레임 미식별돼도 _stable_hp는
        #    유지되고, 이름이 한참(=_GONE_FRAMES) 안 읽히면 '사라짐'으로 보고 해제.
        if boss_id is not None:
            self._unidentified = 0
            if boss_id != self._cur_boss:
                self._cur_boss = boss_id
                self._tracker = (
                    make_tracker(self._bosses[boss_id])
                    if boss_id in self._bosses
                    else None
                )
                self._reset_hp()  # 새 보스 → HP 상태 초기화
            self._accept_hp(read_percent(pct_reg))  # 식별된 프레임만 HP 반영
        else:
            self._unidentified += 1
            if self._unidentified > self._GONE_FRAMES and self._tracker is not None:
                self._cur_boss = None
                self._tracker = None
                self._reset_hp()
        hp = self._stable_hp

        # 실시간 상태 표시(현재 프레임 기준)
        if boss_id in self._bosses:
            name = self._bosses[boss_id].name
        elif boss_id is not None:
            name = "미등록 보스"
        else:
            name = "미식별"
        hp_txt = f"{hp}%" if hp is not None else "—"
        self.status_label.setText(f"식별: {name}   HP: {hp_txt}")

        # 트래커 상태 갱신: 보스가 이번 프레임 식별됐을 때만(garbage 발동 차단).
        # 관측은 '경고 사용'과 무관하게 돌려 '다음 패턴 목록'도 최신으로 유지하고,
        # 중앙 경고·소리만 '경고 사용'일 때 낸다.
        alerts = []
        if boss_id is not None and self._tracker is not None and hp is not None:
            alerts = self._tracker.observe(hp)
        if self.enable.isChecked():
            for alert in alerts:
                self._overlay.show_message(alert.text, 3000)
                self._play(alert.sound)

        self._update_upcoming(hp)

    # 큰 점프(진입 애니메이션·오판독)와 완만한 감소를 구분해 확정.
    _SMALL_STEP = 12  # 이 이하 변화면 '완만' (2연속으로 확정)
    _CONFIRM_SMALL = 2
    _CONFIRM_JUMP = 3  # 큰 점프·첫 확정은 3연속 필요(글리치 차단)
    # 틱 300ms 기준. 보스 바는 '패턴 중'에도 사라지므로, 패턴이 길어도 잠금이
    # 유지되게 넉넉히 둔다. 이보다 오래 미식별이면 전투 종료로 보고 트래커 해제.
    _GONE_FRAMES = 60  # ~18초

    def _reset_hp(self) -> None:
        self._stable_hp = None
        self._hp_cand = None
        self._hp_cand_n = 0

    def _accept_hp(self, raw: int | None) -> None:
        """판독값을 확정 HP(self._stable_hp)로 반영할지 결정. 못 읽은 프레임(None)은
        후보를 리셋하고 직전 확정값을 유지한다."""
        if raw is None:
            self._hp_cand = None
            self._hp_cand_n = 0
            return
        self._hp_cand_n = self._hp_cand_n + 1 if raw == self._hp_cand else 1
        self._hp_cand = raw
        gradual = (
            self._stable_hp is not None
            and abs(raw - self._stable_hp) <= self._SMALL_STEP
        )
        need = self._CONFIRM_SMALL if gradual else self._CONFIRM_JUMP
        if self._hp_cand_n >= need:
            self._stable_hp = raw

    def _grab_rect(self, x: int, y: int, w: int, h: int):
        try:
            if self._sct is None:
                import mss

                self._sct = mss.mss()
            shot = self._sct.grab({"left": x, "top": y, "width": w, "height": h})
            return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
                shot.height, shot.width, 4
            )[:, :, :3]
        except Exception:  # noqa: BLE001 — 캡처 불가 → 이번 틱 건너뜀
            return None

    def _show_preview(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        img = QImage(rgb.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888)
        self.preview.setPixmap(
            QPixmap.fromImage(img).scaledToHeight(38, Qt.TransformationMode.FastTransformation)
        )

    def _play(self, stage: str) -> None:
        from .notifier import SoundNotifier

        if self._notifier is None:
            self._notifier = SoundNotifier(
                {"pre": _PRE_SOUND, "near": _NEAR_SOUND}, volume=0.8
            )
        if not self._notifier.play(stage):
            from PySide6.QtWidgets import QApplication

            QApplication.beep()

    def shutdown(self) -> None:
        self._timer.stop()
        self._upcoming.close()
        self._overlay.close()
