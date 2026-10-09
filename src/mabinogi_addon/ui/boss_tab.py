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
from PySide6.QtGui import QImage, QPixmap
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
        self._notifier = None

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
        self._overlay.show_message("고목의 페타크 85% 패턴 준비  (미리보기)", 2500)

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
        config.save_boss_pattern({"enabled": self.enable.isChecked(), "box": self._region})

    # ---- 읽기 루프 ----
    def _tick(self) -> None:
        self._apply_gate()
        if not self._logged_in():
            return
        active = self._watcher.is_game_active() or self._watcher.is_self_active()
        if not self._region or not active:
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

        # 경고 발동: 보스가 이번 프레임 식별됐을 때만(garbage 발동 차단).
        if (
            boss_id is not None
            and self.enable.isChecked()
            and self._tracker is not None
            and hp is not None
        ):
            for alert in self._tracker.observe(hp):
                self._overlay.show_message(alert.text, 3000)
                self._play(alert.sound)

    # 큰 점프(진입 애니메이션·오판독)와 완만한 감소를 구분해 확정.
    _SMALL_STEP = 12  # 이 이하 변화면 '완만' (2연속으로 확정)
    _CONFIRM_SMALL = 2
    _CONFIRM_JUMP = 3  # 큰 점프·첫 확정은 3연속 필요(글리치 차단)
    # 틱 300ms 기준. 이름이 이보다 오래 안 읽히면 보스 사라짐으로 보고 트래커 해제.
    _GONE_FRAMES = 10  # ~3초

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
