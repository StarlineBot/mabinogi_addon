"""미러 오버레이 관리 (커스텀 오버레이 / 기획서 3.6).

공유 캡처: 매 틱 전체 화면을 1회만 grab하고, 각 미러 오버레이가 자기 소스 영역만
crop해서 받는다(미러 개수와 무관하게 캡처 비용 일정). fps 캡으로 갱신 비용 상한.

캡처는 mss(크로스플랫폼). 실패(헤드리스 등) 시 조용히 건너뛴다. grab 함수는 테스트에서
주입 가능.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from .mirror_overlay import MirrorOverlay

_log = logging.getLogger("mabinogi_addon.mirror")


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
        source_hwnd=None,
        force_capture: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._overlays: list[MirrorOverlay] = []
        self._grab = grab  # 테스트 주입: () -> (np.ndarray BGRA, left, top) | None
        # 호환 캡처 모드: True면 DWM 썸네일을 아예 안 쓰고 항상 캡처(dxcam/mss)로 그린다.
        # 게임이 '전체창 모드'라 DWM 미러가 검정/멈춤일 때 사용자가 켠다.
        self._force_capture = bool(force_capture)
        # 게임 활성 여부(비활성/최소화면 캡처를 쉬고 오버레이를 숨긴다). 기본 항상 활성.
        self._is_active = is_active or (lambda: True)
        # DWM 썸네일 미러 소스(게임 창 HWND) 공급자. Windows + 공급자 있으면 DWM 모드:
        # 컴포지터가 복사를 맡아 CPU ~0%, mss 전체화면 캡처를 안 한다.
        self._source_hwnd = source_hwnd
        self._fps = max(1, fps)
        # DWM 썸네일을 쓸 수 있는 환경인지(Windows + 소스 공급자). 실제 '지금 쓸지'는
        # _desired_dwm()가 매번 판단한다 — 게임이 '테두리 없는 전체 창'이면 OS가
        # independent flip로 전환돼 DWM 썸네일이 검정으로 나오므로, 그땐 mss로 그린다.
        self._dwm_cap = source_hwnd is not None and self._dwm_available()
        # 현재 모드. 생성자에선 게임 창 탐지를 하지 않는다(소스 공급자가 아직 완전히
        # 초기화 전일 수 있음 + 게임이 아직 안 떴을 수 있음). DWM 가능이면 일단 DWM로
        # 시작하고, 첫 _tick의 _maybe_switch_mode가 실제 상태(전체창/못찾음)에 맞춰 전환.
        self._dwm = self._dwm_cap
        self._mode_pending = 0  # 모드 전환 히스테리시스(원하는 모드가 몇 틱 지속됐나)
        self._attached_hwnd = 0  # 현재 썸네일이 물린 게임 창(바뀌면 재연결)
        self._shown = True
        self._paused = False  # 사용자 일시정지 → 미러 숨김·캡처 쉼
        self._sct = None
        self._timer = QTimer(self)
        # DWM 모드는 비트맵 복사가 없어 자주 돌 필요가 없다(연결 확인·활성 토글용 250ms).
        # mss 모드만 fps 기반 주기.
        self._apply_interval()
        self._timer.timeout.connect(self._tick)

    @staticmethod
    def _dwm_available() -> bool:
        from ..system import dwm_thumbnail

        return dwm_thumbnail.available()

    def _apply_interval(self) -> None:
        self._timer.setInterval(250 if self._dwm else max(1, 1000 // self._fps))

    def _desired_dwm(self) -> bool:
        """지금 DWM 썸네일로 그릴지. 아니면 mss(전체 데스크톱 크롭)로 그린다.

        - DWM 환경이 아님(비Windows 등) 또는 호환 캡처 모드 ON → 캡처로.
        - 게임 창을 못 찾음 → 붙을 소스가 없음 → 캡처로.
        그 외(창 찾음)엔 DWM 썸네일(저부하)을 쓴다. '전체창 모드'인지로는 가르지 않는다 —
        전체창이어도 DWM이 멀쩡한 환경이 많고(GPU/드라이버의 MPO 동작 차이), 깨지는 쪽은
        크기로 구분되지 않으므로 그런 사용자는 '호환 캡처 모드'를 켠다.
        """
        if not self._dwm_cap or self._force_capture:
            return False
        hwnd = self._source_hwnd() if self._source_hwnd else 0
        return bool(hwnd)

    def set_force_capture(self, on: bool) -> None:
        """호환 캡처 모드 토글. 켜면 DWM을 끄고 캡처로, 끄면 자동 판정으로 되돌린다.
        모드가 바뀌면 오버레이를 새 모드로 즉시 재생성한다."""
        on = bool(on)
        if on == self._force_capture:
            return
        self._force_capture = on
        desired = self._desired_dwm()
        if desired != self._dwm:
            self._rebuild_overlays(desired)

    def _maybe_switch_mode(self) -> None:
        """게임 창 상태 변화(창↔전체창, 찾음↔못찾음)에 맞춰 DWM↔mss를 전환한다.
        잠깐의 상태 떨림으로 깜빡이지 않게 몇 틱 연속 유지될 때만 전환(히스테리시스)."""
        if not self._dwm_cap:
            return  # 애초에 mss 전용 환경 → 전환 없음
        desired = self._desired_dwm()
        if desired == self._dwm:
            self._mode_pending = 0
            return
        self._mode_pending += 1
        if self._mode_pending >= 3:
            self._mode_pending = 0
            self._rebuild_overlays(desired)

    def _rebuild_overlays(self, dwm: bool) -> None:
        """현재 미러들을 새 모드(DWM/mss)로 다시 만든다(위치·고정·배율 유지)."""
        dicts = self.to_dicts()
        for o in self._overlays:
            o.detach_thumbnail()
            o.close()
        self._overlays = []
        self._dwm = dwm
        self._apply_interval()
        for d in dicts:
            self._overlays.append(self._make_overlay(d))
        self._sync_timer()
        _log.info("미러 모드 전환: %s (미러 %d개)", "DWM 썸네일" if dwm else "mss 폴백", len(dicts))
        self.changed.emit()

    # ---- 조회 ----
    def overlays(self) -> list[MirrorOverlay]:
        return list(self._overlays)

    def to_dicts(self) -> list[dict]:
        return [o.to_dict() for o in self._overlays]

    # ---- 추가/삭제 ----
    def _make_overlay(self, region: dict) -> MirrorOverlay:
        overlay = MirrorOverlay(region, thumbnail_mode=self._dwm)
        overlay.moved.connect(self.overlay_moved)
        overlay.set_locked(bool(region.get("locked", False)))
        overlay.show()
        if self._dwm:
            self._attach(overlay)  # 창이 떠서 winId 유효 → 바로 썸네일 연결 시도
        return overlay

    def add(self, region: dict) -> MirrorOverlay:
        overlay = self._make_overlay(region)
        self._overlays.append(overlay)
        self._sync_timer()
        self.changed.emit()
        return overlay

    def _attach(self, overlay: MirrorOverlay) -> None:
        """DWM 모드: 게임 창을 찾아 썸네일 연결(이미 연결됐으면 생략)."""
        if overlay.thumbnail_active:
            return
        hwnd = self._source_hwnd() if self._source_hwnd else 0
        if hwnd:
            self._attached_hwnd = hwnd
            overlay.attach_thumbnail(hwnd)

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

    def set_paused(self, paused: bool) -> None:
        """사용자 일시정지: 미러 오버레이를 숨기고 캡처를 쉰다(다시 켜면 _tick이 복원)."""
        self._paused = paused
        if paused and self._shown:
            for o in self._overlays:
                o.hide()
            self._shown = False

    def _tick(self) -> None:
        # 일시정지 또는 게임 비활성/최소화: 캡처를 쉬고(가장 큰 비용) 오버레이를 숨긴다.
        if self._paused or not self._is_active():
            if self._shown:
                for o in self._overlays:
                    o.hide()
                self._shown = False
            return
        if not self._shown:
            for o in self._overlays:
                o.show()
            self._shown = True

        # 게임 창 상태(창↔전체창, 찾음↔못찾음)에 맞춰 DWM↔mss 전환(히스테리시스).
        self._maybe_switch_mode()

        # DWM 모드: 비트맵 복사 없음. 게임 창이 (처음/재실행으로) 생기면 연결하고,
        # 게임 창이 바뀌면(HWND 변경) 재연결만 한다. 이후는 컴포지터가 알아서 그린다.
        if self._dwm:
            hwnd = self._source_hwnd() if self._source_hwnd else 0
            if hwnd and hwnd != self._attached_hwnd:
                self._attached_hwnd = hwnd
                for o in self._overlays:
                    o.detach_thumbnail()
            for o in self._overlays:
                if hwnd and not o.thumbnail_active:
                    o.attach_thumbnail(hwnd)
            return

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
            return self._grab()  # 테스트 주입
        # 캡처 폴백은 mss 전체 '가상 데스크톱'을 잡는다 → 절대좌표 크롭이라 게임이
        # 2번 모니터에 있어도 정확히 그 영역을 집는다(dxcam 주모니터 전용과 달리).
        return self._grab_mss()

    def _grab_mss(self):
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
