"""미러 오버레이 관리 (커스텀 오버레이 / 기획서 3.6).

공유 캡처: 매 틱 전체 화면을 1회만 grab하고, 각 미러 오버레이가 자기 소스 영역만
crop해서 받는다(미러 개수와 무관하게 캡처 비용 일정). fps 캡으로 갱신 비용 상한.

캡처는 mss(크로스플랫폼). 실패(헤드리스 등) 시 조용히 건너뛴다. grab 함수는 테스트에서
주입 가능.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from .mirror_overlay import MirrorOverlay


def crop_region(frame: np.ndarray, left: int, top: int, region: dict) -> np.ndarray | None:
    """전체 프레임(BGRA)에서 소스 영역만 잘라낸다. 범위 밖이면 None."""
    x = int(region["x"]) - left
    y = int(region["y"]) - top
    w = int(region["w"])
    h = int(region["h"])
    fh, fw = frame.shape[:2]
    if x < 0 or y < 0 or x + w > fw or y + h > fh or w <= 0 or h <= 0:
        return None
    return frame[y : y + h, x : x + w]


def _to_qimage(bgra: np.ndarray) -> QImage:
    """BGRA 배열 → 불투명 QImage(RGB32). 데이터 소유 복사.

    mss 캡처는 알파가 0이라, 그대로 두면 레이어드(투명) 창 합성에서 창 전체가 투명으로
    간주돼 클릭이 통과(드래그 불가)한다. 알파를 255로 채워 불투명하게 만든다.
    """
    arr = np.array(bgra, copy=True)
    arr[:, :, 3] = 255
    h, w = arr.shape[:2]
    return QImage(arr.tobytes(), w, h, QImage.Format.Format_RGB32).copy()


class MirrorManager(QObject):
    changed = Signal()  # 미러 집합 변경 → 탭 목록 갱신
    overlay_moved = Signal()  # 드래그 이동 → 현재 상태 저장

    def __init__(
        self,
        fps: int = 15,
        grab=None,
        is_active=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._overlays: list[MirrorOverlay] = []
        self._grab = grab  # 테스트 주입: () -> (np.ndarray BGRA, left, top) | None
        # 게임 활성 여부(비활성/최소화면 캡처를 쉬고 오버레이를 숨긴다). 기본 항상 활성.
        self._is_active = is_active or (lambda: True)
        self._shown = True
        self._sct = None
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, 1000 // max(1, fps)))
        self._timer.timeout.connect(self._tick)

    # ---- 조회 ----
    def overlays(self) -> list[MirrorOverlay]:
        return list(self._overlays)

    def to_dicts(self) -> list[dict]:
        return [o.to_dict() for o in self._overlays]

    # ---- 추가/삭제 ----
    def add(self, region: dict) -> MirrorOverlay:
        overlay = MirrorOverlay(region)
        overlay.moved.connect(self.overlay_moved)
        overlay.set_locked(bool(region.get("locked", False)))
        overlay.show()
        self._overlays.append(overlay)
        self._sync_timer()
        self.changed.emit()
        return overlay

    def remove_indices(self, indices) -> None:
        for i in sorted(set(indices), reverse=True):
            if 0 <= i < len(self._overlays):
                self._overlays.pop(i).close()
        self._sync_timer()
        self.changed.emit()

    def clear(self) -> None:
        for o in self._overlays:
            o.close()
        self._overlays.clear()
        self._sync_timer()
        self.changed.emit()

    def load(self, items: list[dict]) -> None:
        """현재 미러를 주어진 목록으로 교체(프리셋 불러오기)."""
        self.clear()
        for it in items:
            self.add(it)

    # ---- 고정 ----
    def set_locked(self, indices, locked: bool) -> None:
        for i in indices:
            if 0 <= i < len(self._overlays):
                self._overlays[i].set_locked(locked)
        self.changed.emit()

    def set_locked_all(self, locked: bool) -> None:
        for o in self._overlays:
            o.set_locked(locked)
        self.changed.emit()

    # ---- 캡처 루프 ----
    def _sync_timer(self) -> None:
        if self._overlays and not self._timer.isActive():
            self._timer.start()
        elif not self._overlays and self._timer.isActive():
            self._timer.stop()

    def _tick(self) -> None:
        # 게임 비활성/최소화: 캡처를 쉬고(가장 큰 비용) 오버레이를 숨긴다.
        if not self._is_active():
            if self._shown:
                for o in self._overlays:
                    o.hide()
                self._shown = False
            return
        if not self._shown:
            for o in self._overlays:
                o.show()
            self._shown = True

        # 드래그 중엔 캡처(메인 스레드에서 전체 화면 grab)를 쉰다 → 그 시간을 드래그에
        # 양보해 창 이동이 부드럽다. 위치 잡는 중엔 내용 갱신이 필요 없다.
        if any(o.dragging for o in self._overlays):
            return

        got = self._grab_full()
        if got is None:
            return
        frame, left, top = got
        for o in self._overlays:
            sub = crop_region(frame, left, top, o.source)
            if sub is not None:
                o.set_frame(_to_qimage(np.ascontiguousarray(sub)))

    def _grab_full(self):
        if self._grab is not None:
            return self._grab()
        try:
            if self._sct is None:
                import mss

                self._sct = mss.mss()
            mon = self._sct.monitors[0]  # 전체(가상) 데스크톱
            shot = self._sct.grab(mon)
            frame = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
                shot.height, shot.width, 4
            )
            return frame, mon["left"], mon["top"]
        except Exception:  # noqa: BLE001 — 캡처 불가(헤드리스 등) → 갱신 생략
            return None

    def shutdown(self) -> None:
        self._timer.stop()
        for o in self._overlays:
            o.close()
        self._overlays.clear()
