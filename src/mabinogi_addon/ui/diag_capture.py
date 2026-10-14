"""진단용 캡처 (문제 신고 보조).

저장된 추적 영역(버프/디버프/투아림)을 '지금' 그대로 캡처해 PNG로 저장한다.
해상도·게임 UI 배율이 다른 사용자의 시간/% 판독 오류를 재현·확정하려면, 앱이 실제로
어떤 픽셀을 읽는지 봐야 한다. mss로 물리픽셀을 잡아(DPI 변환 포함) 저장만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from numbers import Integral
from pathlib import Path
from uuid import uuid4

import numpy as np

from .. import config, image_io, paths
from .dpi import to_physical


def validate_region(region: object) -> dict:
    if not isinstance(region, dict):
        raise ValueError("영역은 x, y, w, h가 있는 객체여야 합니다")
    for key in ("x", "y", "w", "h"):
        if key not in region or isinstance(region[key], bool) or not isinstance(region[key], Integral):
            raise ValueError(f"{key}: 정수 좌표가 필요합니다")
    if region["w"] < 1 or region["h"] < 1:
        raise ValueError("영역의 너비와 높이는 1 이상이어야 합니다")
    if region["w"] * region["h"] > 32_000_000:
        raise ValueError("영역이 너무 큽니다 (최대 3200만 픽셀)")
    return {key: int(region[key]) for key in ("x", "y", "w", "h")}


@dataclass
class RegionResult:
    name: str
    status: str
    error: str = ""
    filename: str | None = None
    physical: tuple[int, int, int, int] | None = None


@dataclass
class DiagnosticResult:
    directory: Path | None = None
    regions: list[RegionResult] = field(default_factory=list)
    error: str = ""

    @property
    def saved(self) -> list[str]:
        return [r.filename for r in self.regions if r.filename is not None]

    def message(self) -> str:
        labels = {"buffTracker": "버프", "debuffTracker": "디버프", "tuarim": "투아림"}
        states = {"unconfigured": "영역 미지정", "invalid_region": "영역 오류",
                  "capture_failed": "캡처 실패", "save_failed": "PNG 저장 실패"}
        lines = [f"{len(self.saved)}개 저장했습니다."] if self.saved else ["저장된 PNG가 없습니다."]
        if self.error:
            lines.append(f"저장 폴더 오류: {self.error}")
        for r in self.regions:
            detail = r.filename if r.status == "saved" else states.get(r.status, r.status)
            lines.append(f"{labels.get(r.name, r.name)}: {detail}" + (f" ({r.error})" if r.error else ""))
        if self.saved:
            lines.append(f"\n폴더: {self.directory}")
        return "\n".join(lines)


def diagnostic_regions() -> list[RegionResult]:
    """Qt 좌표 변환은 GUI 스레드에서, 캡처와 디스크 쓰기는 워커에서 실행한다."""
    results = []
    for name in ("buffTracker", "debuffTracker", "tuarim"):
        try:
            region = config.load_tuarim().get("box") if name == "tuarim" else config.load_capture_region(name)
            if region is None:
                results.append(RegionResult(name, "unconfigured"))
                continue
            physical = to_physical(validate_region(region))
            validate_region(dict(zip(("x", "y", "w", "h"), physical)))
            results.append(RegionResult(name, "ready", physical=physical))
        except Exception as exc:
            results.append(RegionResult(name, "invalid_region", str(exc)))
    return results


def _grab_physical(region: dict) -> np.ndarray | None:
    return _grab_pixels(to_physical(validate_region(region)))


def _grab_pixels(physical: tuple[int, int, int, int]) -> np.ndarray | None:
    px, py, pw, ph = physical
    import mss

    with mss.mss() as sct:
        shot = sct.grab({"left": px, "top": py, "width": pw, "height": ph})
    return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
        shot.height, shot.width, 4
    )[:, :, :3]


def save_diagnostic(regions: list[RegionResult] | None = None) -> DiagnosticResult:
    result = DiagnosticResult(regions=diagnostic_regions() if regions is None else regions)
    try:
        result.directory = paths.user_data_dir() / "debug"
        result.directory.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        for r in result.regions:
            if r.status == "ready":
                r.status, r.error = "save_failed", result.error
        return result
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:8]
    for r in result.regions:
        if r.status != "ready":
            continue
        try:
            frame = _grab_pixels(r.physical)
            if frame is None:
                raise RuntimeError("캡처 백엔드가 이미지를 반환하지 않았습니다")
        except Exception as exc:
            r.status, r.error = "capture_failed", f"{type(exc).__name__}: {exc}"
            continue
        fname = f"{r.name}_{ts}.png"
        try:
            if not image_io.imwrite(result.directory / fname, frame):
                raise OSError("PNG 인코딩 또는 파일 쓰기에 실패했습니다")
            r.status, r.filename = "saved", fname
        except Exception as exc:
            r.status, r.error = "save_failed", f"{type(exc).__name__}: {exc}"
    return result
