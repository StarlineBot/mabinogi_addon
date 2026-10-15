"""자동 찾기용 화면 1회 캡처 헬퍼 (mss).

자동 찾기는 '영역이 아직 없을 때' 화면을 한 번 떠서 검출기에 넘긴다. **등록된 게임 창이
있으면 그 창 사각형만** 캡처하고(다중 모니터에서도 게임 화면을 정확히 집음), 없으면
**가상 데스크톱 전체(monitors[0])**로 폴백한다. 검출 좌표를 전역(절대) 좌표로 바꿀
오프셋(left, top)을 함께 돌려준다 — 트래커가 쓰는 좌표계와 같다.

과거엔 `monitors[1]`(mss가 나열한 '첫 모니터')만 떴는데, 그게 주/게임 모니터라는 보장이
없어 다중 모니터에서 엉뚱한 화면을 찍어 자동 찾기가 전부 실패했다. 그래서 게임 창 기준으로
바꾸고 monitors[1] 가정을 제거했다.
"""

from __future__ import annotations

import logging

import numpy as np

from ..autofind_diagnostics import capture_info

_log = logging.getLogger("mabinogi_addon.capture")
_sct = None


def _mss():
    """mss 인스턴스(재사용)."""
    global _sct
    if _sct is None:
        import mss

        _sct = mss.mss()
    return _sct


def _grab_mon(mon: dict) -> np.ndarray | None:
    """mss 모니터/영역 dict({left,top,width,height})를 BGR(연속 배열)로 캡처. 실패 시 None."""
    try:
        shot = _mss().grab(mon)
        img = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)
        return np.ascontiguousarray(img[:, :, :3])
    except Exception as exc:  # noqa: BLE001 — 캡처 실패 시 호출 측이 안내
        info = capture_info.get()
        if info is not None:
            info.setdefault("errors", []).append(f"mss.grab: {type(exc).__name__}: {exc}")
        return None


def grab_primary() -> tuple[np.ndarray | None, int, int]:
    """가상 데스크톱 전체(monitors[0])를 BGR로 캡처하고 (이미지, left, top)을 반환.

    monitors[0]은 모든 모니터를 합친 가상 데스크톱이라 모니터 구성·순서와 무관하다(Windows
    주 모니터는 항상 (0,0)). 오프셋으로 데스크톱 원점(left/top; 왼쪽에 모니터가 있으면 음수)을
    돌려줘, 검출 좌표 + 오프셋 = 트래커가 쓰는 절대 좌표가 된다. 실패 시 (None, 0, 0)."""
    try:
        mon = _mss().monitors[0]  # 0 = 전체(가상) 데스크톱
    except Exception as exc:  # noqa: BLE001
        info = capture_info.get()
        if info is not None:
            info.setdefault("errors", []).append(f"mss.monitors: {type(exc).__name__}: {exc}")
        return None, 0, 0
    img = _grab_mon(mon)
    if img is None:
        return None, 0, 0
    return img, int(mon["left"]), int(mon["top"])


def _grab_game_window() -> tuple[np.ndarray | None, int, int]:
    """등록된 게임 창 사각형만 캡처하고 (이미지, left, top). 창을 못 찾으면 (None, 0, 0).

    다중 모니터에서 '주 모니터'가 아니라 '게임이 떠 있는 곳'을 정확히 집기 위해, 포그라운드
    감지·미러와 같은 창 탐색(find_game_window)을 재사용한다. 좌표는 전역(절대) 물리픽셀."""
    try:
        from .. import config
        from ..system import dwm_thumbnail
        from ..system.window_watcher import DEFAULT_GAME_TITLES

        game_exe = config.load_game_exe()
        hwnd = dwm_thumbnail.find_game_window(game_exe, DEFAULT_GAME_TITLES)
        rect = dwm_thumbnail.window_rect(hwnd) if hwnd else None
        info = capture_info.get()
        if info is not None:
            info.update(game_exe=game_exe, game_hwnd=int(hwnd or 0), game_window_rect=rect)
    except Exception as exc:  # noqa: BLE001 — Windows 전용/pywin32 없음 등
        info = capture_info.get()
        if info is not None:
            info.setdefault("errors", []).append(f"game_window: {type(exc).__name__}: {exc}")
        hwnd, rect = 0, None
    if not rect:
        _log.info("자동 찾기 캡처: 게임 창 미발견(hwnd=%s) → 데스크톱 전체로 폴백", hwnd)
        return None, 0, 0
    left, top, right, bottom = rect
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        _log.info("자동 찾기 캡처: 게임 창 크기 이상 %s → 데스크톱 전체로 폴백", rect)
        return None, 0, 0
    img = _grab_mon({"left": left, "top": top, "width": w, "height": h})
    if img is None:
        return None, 0, 0
    _log.info("자동 찾기 캡처: 게임 창 hwnd=%s rect=%s", hwnd, rect)
    return img, int(left), int(top)


def _save_debug_frame(frame: np.ndarray | None, offset: tuple[int, int]) -> None:
    """프레임 정보만 로그로 남긴다. PNG는 실행별 진단 워커가 저장한다."""
    try:
        try:
            mons = _mss().monitors
        except Exception:  # noqa: BLE001
            mons = "(unavailable)"
        _log.info(
            "자동 찾기 프레임 %s offset=%s monitors=%s",
            None if frame is None else f"{frame.shape[1]}x{frame.shape[0]}",
            offset,
            mons,
        )
    except Exception:  # noqa: BLE001 — 진단용이라 실패해도 무시
        pass


def capture_for_autofind(*, require_game=False, restore_allowed=None,
                         restore_widget_allowed=None) -> tuple[np.ndarray | None, int, int]:
    """자동 찾기용 캡처 — 우리 앱 창·오버레이를 잠깐 숨긴 뒤 게임만 찍는다.

    자동 찾기 버튼은 우리 창에 있어, 그냥 찍으면 앱 창/오버레이가 게임(보스바·상태목록창)을
    가리거나 오버레이가 함께 찍혀 오탐한다. 모든 최상위 위젯을 잠깐 숨기고 조금 기다렸다가
    캡처한 뒤 되돌린다(설정 시 1회성이라 짧은 깜빡임 허용).

    캡처 대상: 등록된 게임 창 사각형(우선) → 없으면 가상 데스크톱 전체. 반환 (이미지, left, top).
    종료 시 전체 복원 차단과 사용자가 숨긴 개별 창의 복원 차단은 각각 판단한다.
    """
    import time

    from PySide6.QtWidgets import QApplication

    tops = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
    img = None
    left = top = 0
    used_game = False
    try:
        for w in tops:
            w.hide()
        QApplication.processEvents()
        time.sleep(0.25)  # 컴포지터가 실제로 지우도록 잠깐 대기
        QApplication.processEvents()
        info = capture_info.get()
        if info is not None:
            from ..system.display_diagnostics import monitor_info
            info["backend"] = "mss"
            try:
                info.update(monitor_info())
            except Exception as exc:
                info["dpi_info_error"] = str(exc)
            try:
                info["mss_monitors"] = [dict(m) for m in _mss().monitors]
            except Exception as exc:
                info["monitor_error"] = str(exc)
        img, left, top = _grab_game_window()  # 게임 창 우선
        used_game = img is not None
        if img is None and not require_game:
            img, left, top = grab_primary()  # 폴백: 가상 데스크톱 전체
        if info is not None:
            info.update(target="game_window" if used_game else "game_window_unavailable" if require_game else "virtual_desktop",
                        offset_physical=[left, top],
                        frame_size=None if img is None else [img.shape[1], img.shape[0]])
        _save_debug_frame(img, (left, top))
    finally:
        for w in tops:
            if restore_allowed is not None and not restore_allowed():
                break
            if restore_widget_allowed is not None and not restore_widget_allowed(w):
                continue
            try:
                w.show()
                w.raise_()
            except RuntimeError:  # processEvents 중 이미 닫힌 Qt 객체
                continue
        QApplication.processEvents()
    # 위젯 복원 뒤에 안내한다(숨긴 상태에서 모달 띄우지 않게). 게임 창을 못 찾아 전체
    # 데스크톱으로 폴백했고 모니터가 여러 개면, 엉뚱한 화면을 찍었을 수 있어 등록을 권한다.
    if img is not None and not used_game and not require_game:
        _warn_no_game_window()
    return img, left, top


def _warn_no_game_window() -> None:
    """다중 모니터인데 게임 창을 못 찾아 전체 데스크톱을 캡처한 경우 등록을 안내한다.
    단일 모니터면 전체=그 화면이라 문제없어 생략."""
    try:
        mons = _mss().monitors
        if len(mons) - 1 < 2:  # [0]=가상 전체 제외 → 실제 모니터 수
            return
        from PySide6.QtWidgets import QApplication, QMessageBox

        QMessageBox.information(
            QApplication.activeWindow(),
            "자동 찾기 — 게임 창 안내",
            "게임 창을 인식하지 못해 전체 화면을 캡처했습니다.\n\n"
            "모니터가 여러 개면 엉뚱한 화면을 잡을 수 있습니다. "
            "설정 › '게임 창 인식'에서 게임 창을 등록하면, 자동 찾기가 "
            "게임 화면만 정확히 캡처합니다.",
        )
    except Exception:  # noqa: BLE001 — 안내 실패는 무시
        pass
