"""투아림 관리 탭 (기획서 3.3 변형).

화면의 투아림 % 게이지 영역을 '영역 지정'으로 한 번 잡아두면, 그 화면 좌표를 직접
읽어(오버레이로 가리지 않음) 지정한 임계(예 95/98) 이상이 될 때 소리로 알린다.

제대로 읽는지 확인용으로, 탭에 '캡처된 영역 미리보기 + 현재 값'을 실시간 표시한다.
숫자 템플릿(detect/templates/tuarim)이 아직 없으면 판독은 None('현재 값: —')이지만,
미리보기 이미지로 영역이 숫자에 맞았는지 눈으로 확인할 수 있다.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config, image_io, paths
from ..detect.tuarim_reader import read_percent
from ..tracker import TuarimTracker
from .help_dialog import tab_header
from .widgets import CapturePathLabel, checkbox, hint_label


# 숫자 두 자리+% 를 덮는 고정 박스 크기(px). 스샷 측정: 한 글자 ~16px, '0%'=32×19.
# 2자리+% ≈ 48×19 → 여유를 둔 기본값. (해상도/UI 배율 다르면 추후 조정)
TUARIM_BOX_SIZE = (58, 28)

# 영역에 꼭 들어가야 하는 것(앱 라벨 ↔ 화면 점선 라벨이 같은 기준을 공유).
HIGHLIGHT_TITLE = "투아림 영역 확인"
# 100%일 때 '100'의 앞 '1'이 잘리면 "00"으로 오인될 수 있어, 100%까지 다 들어가게 안내.
HIGHLIGHT_SUB = "숫자와 % 가 다 보이나요? (100%일 때 '100%'까지 들어가게 넉넉히)"

# 투아림 관리 사용법(? 아이콘 → 새 창).
HELP_TITLE = "투아림 트래커 사용법"
HELP_HTML = """
<h3>투아림 트래커란?</h3>
<p>화면의 투아림 <b>% 게이지</b>(작은 원 안 숫자 아래 %)를 읽어, 지정한 %(예: 95·98)
이상이 되면 소리로 알립니다. 100%가 되면 다시 0%부터 시작합니다.
오버레이로 화면을 가리지 않고 <b>읽기만</b> 합니다.</p>
<p><b>영역은 100%일 때 "100%"가 다 들어가게</b> 넉넉히 잡으세요. 앞 숫자가 잘리면
100%를 잘못 읽을 수 있습니다.</p>

<h3>사용 순서</h3>
<ol>
<li><b>영역 지정</b> — 버튼을 누르면 박스가 커서를 따라옵니다.
<b>마우스 휠로 크기를 숫자에 맞게</b> 조절하고, 투아림 <b>%(숫자 두 자리)</b> 위에
올려 클릭해 배치합니다. 선택 중 화면에 '박스 미리보기'로 실제 잡는 영역이 보입니다.</li>
<li><b>알림 기준</b> — 1차·2차 %를 정하고, 각각 <b>소리</b> 알림을 켤 수 있습니다.</li>
</ol>

<p>아래 <b>미리보기</b>와 <b>현재 값</b>으로 영역이 숫자에 잘 맞았는지 확인하세요.</p>
"""


class TuarimTab(QWidget):
    def __init__(self, watcher) -> None:
        super().__init__()
        self._watcher = watcher
        cfg = config.load_tuarim()
        self._thresholds = cfg["thresholds"]
        self._sounds = cfg["sounds"]
        self._region = cfg["box"]  # {x,y,w,h} 또는 None
        self._sct = None
        self._tracker = TuarimTracker(self._thresholds)
        self._notifier = None
        self._autofind_busy = False
        self._shutting_down = False
        self._autofind_highlight = None
        # 숫자 템플릿 수집용 상태
        self._last_frame = None  # 마지막으로 캡처한 영역(스냅샷 저장 대상)
        self._last_value: int | None = None  # 마지막 판독값(스냅샷 파일명 태그용)
        self._prev_raw: int | None = None  # 직전 원시 판독값(2연속 확정용)
        self._stable_value: int | None = None  # 표시용 마지막 확정값(새 관측과 분리)
        self._last_saved_frame = None  # 수집 모드: 직전 '저장한' 영상(변화 감지 기준)
        # 수집 영역 저장 폴더. 소스 실행은 git 추적 폴더(수집→푸시→템플릿 생성),
        # 배포본(exe)은 사용자가 찾아서 보낼 수 있게 %LOCALAPPDATA% 아래 폴더에 저장한다.
        if paths.is_frozen():
            self._shot_dir = paths.user_data_dir() / "tuarim_shots"
        else:
            self._shot_dir = paths.project_root() / "tests" / "data" / "tuarim_shots"
        self._shot_count = 0

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addWidget(tab_header(
            "투아림이 설정한 비율에 도달하면 소리로 알립니다.", HELP_TITLE, HELP_HTML, self
        ))
        v.addWidget(
            hint_label(
                "보라색 원과 오른쪽 아래 숫자·%가 보이는 상태에서 자동 찾기를 실행하세요."
                " 직접 지정할 때는 100%까지 숫자와 %가 잘리지 않게 맞추세요."
            )
        )

        row = QHBoxLayout()
        self.region_btn = QPushButton("직접 지정")
        self.region_btn.setToolTip("% 숫자에 휠로 크기 맞춰 클릭 배치(돋보기). 다시 누르면 재지정.")
        self.region_btn.clicked.connect(self._on_region)
        row.addWidget(self.region_btn)
        self.region_label = hint_label("")
        row.addWidget(self.region_label, 1)
        self.view_region_btn = QPushButton("지정 영역 보기")
        self.view_region_btn.setToolTip("잡힌 영역을 화면에 점선으로 잠깐 표시")
        self.view_region_btn.clicked.connect(self._flash_region)
        row.addWidget(self.view_region_btn)
        self.auto_find_btn = QPushButton("🧪 자동 찾기")
        self.auto_find_btn.setToolTip("투아림 원형 장식에서 숫자와 % 영역 찾기 — Discord 베타")
        self.auto_find_btn.clicked.connect(self._on_auto_find)
        row.addWidget(self.auto_find_btn)
        v.addLayout(row)

        # 확인용: 캡처 미리보기 + 현재 값
        prev_row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedHeight(40)
        self.preview.setMinimumWidth(80)
        self.preview.setStyleSheet("background:palette(base); border:1px solid palette(mid);")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_row.addWidget(self.preview)
        self.value_label = QLabel("현재 값: —")
        self.value_label.setStyleSheet("font-size:14px; font-weight:600;")
        prev_row.addWidget(self.value_label, 1)
        v.addLayout(prev_row)

        self.enable = checkbox("투아림 알림 사용")
        self.enable.setChecked(cfg["enabled"])
        self.enable.toggled.connect(self._save)
        v.addWidget(self.enable)

        v.addWidget(self._threshold_group())
        # 숫자 템플릿 수집: 판독이 틀릴 때 실제 캡처를 모아 템플릿을 고치기 위한 제보용
        # 도구. 디스코드 로그인한 사용자에게만 보인다(일반 사용자 화면은 깔끔하게).
        # 로그인 상태는 _tick에서 매번 반영한다(보스 탭 게이팅과 동일).
        self._collect_box = self._collect_group()
        v.addWidget(self._collect_box)
        self._apply_collect_gate()
        v.addStretch(1)

        self._update_region_label()
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._tick_enabled)
        self._timer.start()

    def _threshold_group(self) -> QGroupBox:
        box = QGroupBox("알림 기준 (% 이상)")
        grid = QGridLayout(box)
        self._spins: list[QSpinBox] = []
        self._sound_checks: list[QCheckBox] = []
        for i, name in enumerate(("첫 알림", "추가 알림")):
            grid.addWidget(QLabel(name), i, 0)
            spin = QSpinBox()
            spin.setRange(90, 99)  # % 판독은 90%대만 신뢰 가능 + 목적상 100% 직전 경고
            spin.setSuffix(" %")
            spin.setValue(self._thresholds[i] if i < len(self._thresholds) else 95)
            spin.valueChanged.connect(self._save)
            grid.addWidget(spin, i, 1)
            chk = checkbox("소리")
            chk.setChecked(self._sounds[i] if i < len(self._sounds) else True)
            chk.toggled.connect(self._save)
            grid.addWidget(chk, i, 2)
            self._spins.append(spin)
            self._sound_checks.append(chk)
        grid.setColumnStretch(3, 1)
        return box

    @staticmethod
    def _logged_in() -> bool:
        return config.load_discord_user() is not None

    def _apply_collect_gate(self) -> None:
        """수집(제보) 도구는 디스코드 로그인 사용자에게만 노출."""
        logged_in = self._logged_in()
        box = getattr(self, "_collect_box", None)
        if box is not None:
            box.setVisible(logged_in)
        self.auto_find_btn.setEnabled(logged_in and not self._autofind_busy)

    def _collect_group(self) -> QGroupBox:
        """숫자 템플릿 수집. 앱이 이미 캡처 중인 영역을 PNG로 저장만 한다.

        % 판독이 틀릴 때(특히 90%대처럼 배경이 밝은 구간), 실제 캡처를 모아 템플릿을
        고치는 데 쓴다. 저장 위치는 소스 실행이면 git 폴더, 배포본이면 사용자 폴더다.
        """
        box = QGroupBox("숫자 템플릿 수집 (% 오독 제보용)")
        g = QVBoxLayout(box)
        if paths.is_frozen():
            how = (
                "영역 지정 후 '수집 모드'를 켜면, 게이지 값이 바뀔 때마다 그 영역이\n"
                "PNG로 자동 저장됩니다(타이머 아님 — 숫자가 바뀔 때 1장). 0→100 한 바퀴\n"
                "(특히 90~99%) 돌린 뒤, 아래 '저장 위치' 폴더의 PNG들을 보내주세요."
            )
        else:
            how = (
                "영역 지정 후, 지금 캡처된 영역을 PNG로 저장합니다(전체화면 캡처 불필요).\n"
                "'수집 모드'를 켜면 값이 바뀔 때마다 자동 저장 → 0~100 한 바퀴면 숫자가 모입니다.\n"
                "저장 후 커밋·푸시하면 저장소에서 숫자 템플릿을 만들 수 있습니다."
            )
        g.addWidget(hint_label(how))
        row = QHBoxLayout()
        self.snap_btn = QPushButton("스냅샷 저장")
        self.snap_btn.setToolTip("지금 캡처된 영역 1장 저장")
        self.snap_btn.clicked.connect(self._save_snapshot)
        row.addWidget(self.snap_btn)
        self.open_dir_btn = QPushButton("폴더 열기")
        self.open_dir_btn.setToolTip("수집된 스냅샷이 저장되는 폴더를 탐색기로 엽니다")
        self.open_dir_btn.clicked.connect(lambda: paths.open_folder(self._shot_dir))
        row.addWidget(self.open_dir_btn)
        self.collect_chk = checkbox("수집 모드(값 바뀔 때 자동 저장)")
        row.addWidget(self.collect_chk, 1)
        g.addLayout(row)
        self.collect_label = CapturePathLabel()
        self._update_collect_label()
        g.addWidget(self.collect_label)
        return box

    def _update_collect_label(self) -> None:
        self.collect_label.setText(f"저장 위치: {self._shot_dir}  ·  수집 {self._shot_count}장")
        self.collect_label.setToolTip(str(self._shot_dir))

    def _save_snapshot(self) -> None:
        if self._last_frame is None:
            self.collect_label.setText("저장할 캡처가 없습니다 — 먼저 영역을 지정하세요")
            return
        self._write_shot(self._last_frame, self._last_value)

    def _write_shot(self, frame, value: int | None) -> None:
        try:
            self._shot_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        tag = f"v{value:02d}" if value is not None else "raw"
        path = self._shot_dir / f"{tag}_{self._shot_count:03d}.png"
        if image_io.imwrite(path, frame):
            self._shot_count += 1
            self._update_collect_label()

    # ---- 영역 지정 ----
    def _on_region(self) -> None:
        from .region_selector import RegionSelector

        # 고정 크기 박스를 커서에 붙여 % 위에 클릭 한 번으로 배치(돋보기, 휠로 크기 조절).
        # 이전에 지정한 적 있으면 그 크기로 시작(사용자가 맞춰 둔 크기 유지).
        if self._region:
            size = (int(self._region["w"]), int(self._region["h"]))
        else:
            size = TUARIM_BOX_SIZE
        self._selector = RegionSelector(fixed_size=size)
        self._selector.selected.connect(self._on_selected)
        self._selector.start()

    def _on_selected(self, x: int, y: int, w: int, h: int) -> None:
        self._apply_region(x, y, w, h)
        self._flash_region()

    def _apply_region(self, x: int, y: int, w: int, h: int) -> None:
        config.save_tuarim({"enabled": self.enable.isChecked(),
                            "box": {"x": x, "y": y, "w": w, "h": h},
                            "thresholds": self._thresholds, "sounds": self._sounds})
        self._region = {"x": x, "y": y, "w": w, "h": h}
        self._tracker.reset_observations()
        self._prev_raw = self._stable_value = self._last_value = None
        self._last_frame = self._last_saved_frame = None
        self.preview.clear()
        self.value_label.setText("현재 값: —")
        self._update_region_label()

    def _on_auto_find(self) -> None:
        from .autofind_confirm import confirm_autofind
        confirm_autofind(self, "tuarim", "투아림 숫자와 % (100%까지 포함)", self._apply_region)

    def _flash_region(self) -> None:
        """저장된 투아림 영역을 화면에 굵은 점선으로 잠깐 표시(숫자·% 확인용)."""
        if not self._region:
            return
        from .region_highlight import RegionHighlight

        r = self._region
        self._highlight = RegionHighlight()  # 참조 유지(GC 방지)
        self._highlight.flash(
            int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"]),
            HIGHLIGHT_TITLE, HIGHLIGHT_SUB,
        )

    def _update_region_label(self) -> None:
        if self._region:
            r = self._region
            self.region_label.setText(f"영역: {r['x']},{r['y']}  {r['w']}×{r['h']}  ✔")
            self.region_label.setStyleSheet("color:#2ecc71;")
            self.view_region_btn.setEnabled(True)
        else:
            self.region_label.setText("영역 미지정 — 숫자 두 자리와 % 가 보이게 지정하세요")
            self.region_label.setStyleSheet("color:#8a8f98;")
            self.view_region_btn.setEnabled(False)

    # ---- 저장 ----
    def _save(self) -> None:
        self._thresholds = [s.value() for s in self._spins]
        self._sounds = [c.isChecked() for c in self._sound_checks]
        self._tracker.set_thresholds(self._thresholds)
        config.save_tuarim(
            {
                "enabled": self.enable.isChecked(),
                "box": self._region,
                "thresholds": self._thresholds,
                "sounds": self._sounds,
            }
        )

    # ---- 읽기 루프 ----
    def _tick_enabled(self) -> None:
        self._apply_collect_gate()
        if self.enable.isChecked():
            self._tick()

    def _tick(self) -> None:
        self._apply_collect_gate()  # 로그인 상태에 따라 수집(제보) 도구 노출/숨김
        # 게임 '또는 우리 앱'이 활성일 때 읽는다. 앱을 보며 영역을 맞추거나 템플릿을
        # 수집할 때도 미리보기가 갱신되게(버프/미러와 동일 기준).
        active = (
            self._watcher.is_game_active() or self._watcher.is_self_active()
        )
        if not self._region or not active:
            return
        # 캡처(mss)는 물리픽셀 → 저장된 논리좌표를 배율만큼 변환(150% 등에서 어긋남 방지).
        from .dpi import to_physical

        px, py, pw, ph = to_physical(self._region)
        frame = self._grab_rect(px, py, pw, ph)
        if frame is None:
            return
        self._show_preview(frame)
        self._last_frame = frame  # 스냅샷 저장 대상
        raw = read_percent(frame)
        self._last_value = raw  # 스냅샷 파일명 태그용(원시값)
        # 안정화: 같은 값이 2번 연속 읽혀야 '확정'으로 채택한다. 게이지는 150ms당
        # 천천히 변하므로, 단발 오탐(한 프레임만 다른 값)은 걸러져 거짓/중복 알림을 막는다.
        value = self._stable_value
        observation = None
        if raw is not None and raw == self._prev_raw:
            value = raw
            self._stable_value = raw
            observation = raw
        self._prev_raw = raw
        self.value_label.setText(
            f"현재 값: {value}%" if value is not None else "현재 값: —"
        )
        # 수집 모드: 영상이 '눈에 띄게 바뀌면' 저장(중복 방지). 값(read_percent) 기준이
        # 아니라 영상 변화 기준이라, 템플릿이 아직 없어(value=None) 판독이 안 돼도 숫자가
        # 바뀔 때마다 모인다.
        # 수집 UI는 배포본(exe)에선 없으므로 존재할 때만(개발 모드).
        if (
            getattr(self, "collect_chk", None) is not None
            and self.collect_chk.isChecked()
            and self._frame_changed(frame)
        ):
            self._write_shot(frame, raw)
            self._last_saved_frame = frame
        if self.enable.isChecked():
            # 표시용 이전 값은 새 프레임의 발화/재무장 증거로 사용하지 않는다.
            for t in self._tracker.observe(observation):
                self._play(t)

    def _frame_changed(self, frame, threshold: float = 6.0) -> bool:
        """직전 저장 영상 대비 평균 밝기차가 threshold 이상이면 '바뀜'(새 숫자)."""
        prev = self._last_saved_frame
        if prev is None or prev.shape != frame.shape:
            return True
        diff = np.abs(frame.astype(np.int16) - prev.astype(np.int16))
        return float(diff.mean()) >= threshold

    def _show_preview(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        rgb = np.ascontiguousarray(frame[:, :, ::-1])  # BGR→RGB
        img = QImage(rgb.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888)
        pm = QPixmap.fromImage(img).scaledToHeight(
            38, Qt.TransformationMode.FastTransformation
        )
        self.preview.setPixmap(pm)

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

    def _play(self, threshold: int) -> None:
        idx = self._thresholds.index(threshold) if threshold in self._thresholds else 0
        if idx < len(self._sounds) and not self._sounds[idx]:
            return
        from .notifier import SoundNotifier, sound_path

        if self._notifier is None:
            self._notifier = SoundNotifier(
                {"tuarim": sound_path("투아림 부스트 발동 직전.mp3")}
            )
        if not self._notifier.play("tuarim"):
            from PySide6.QtWidgets import QApplication

            QApplication.beep()

    def refresh_sound(self) -> None:
        """목소리 팩이 바뀌면 재생기 소스를 새 팩으로 갱신(바로 적용)."""
        if self._notifier is not None:
            from .notifier import sound_path

            self._notifier.set_sounds(
                {"tuarim": sound_path("투아림 부스트 발동 직전.mp3")}
            )

    def shutdown(self) -> None:
        self._shutting_down = True
        if self._autofind_highlight is not None:
            self._autofind_highlight.close()
        self._timer.stop()
