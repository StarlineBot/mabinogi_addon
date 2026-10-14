"""저장된 ZIP만을 입력 데이터로 사용하는 자동찾기 재실행.

동일 앱 버전에서: python -m mabinogi_addon.autofind_replay diagnostic.zip
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np

from . import version


def detector_assets(feature: str) -> dict[str, np.ndarray]:
    if feature == "buff":
        from .detect.status_panel import anchor_template
        template = anchor_template()
        return {} if template is None else {"anchor": template}
    if feature in ("boss", "debuff"):
        from .detect.boss_hp_reader import _DIGITS
        return {f"digit_{digit}_{i}": template for digit, samples in _DIGITS.items()
                for i, template in enumerate(samples)}
    return {}


def run_detector(feature: str, frame: np.ndarray, assets: dict, trace: dict):
    if feature == "buff":
        from .detect.status_panel import locate_status_region
        template = assets.get("anchor")
        if template is None:
            trace["rejection"] = "missing_anchor_template"
            return None
        return locate_status_region(frame, template, diagnostics=trace)
    if feature in ("boss", "debuff"):
        from .detect.boss_bar import locate_boss_bar, make_validator
        from .detect import boss_hp_reader
        digits = {}
        for name, image in sorted(assets.items()):
            if name.startswith("digit_"):
                digits.setdefault(name.split("_")[1], []).append(image)
        trace["percent_validation"] = {"transforms": ["height-scaled right-aligned glyph crop", "low-saturation mask", "low-HP bright-mask fallback"],
                                       "accept_score": boss_hp_reader._ACCEPT,
                                       "strong_digit_score": boss_hp_reader._STRONG,
                                       "saturation_max": boss_hp_reader._SAT_MAX,
                                       "reference_height": boss_hp_reader._REF_H,
                                       "y_band": boss_hp_reader._YBAND,
                                       "alignment_search": boss_hp_reader._SEARCH}
        return locate_boss_bar(frame, make_validator(templates=digits, diagnostics=trace), diagnostics=trace)
    if feature == "stat_bars":
        from .detect.stat_bars import locate_stat_bars
        return locate_stat_bars(frame, diagnostics=trace)
    raise ValueError(f"이 버전에 등록되지 않은 자동찾기 검출기: {feature}")


def replay(path: Path | str) -> dict:
    with ZipFile(path) as archive:
        info = archive.infolist()
        if len(info) > 500 or sum(i.file_size for i in info) > 256 * 1024 * 1024:
            raise ValueError("진단 ZIP 크기 상한 초과")
        if len({i.filename for i in info}) != len(info):
            raise ValueError("진단 ZIP에 중복 파일이 있습니다")
        metadata = json.loads(archive.read("metadata.json"))
        if metadata.get("schema") != 1:
            raise ValueError("지원하지 않는 진단 형식")
        images = {}
        for name, digest in metadata.get("files_sha256", {}).items():
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"PNG 무결성 검사 실패: {name}")
            image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
            if image is None:
                raise ValueError(f"PNG 읽기 실패: {name}")
            images[Path(name).stem] = image
        frame = images.pop("input", None)
        if frame is None:
            return {"run_id": metadata["run_id"], "replayed": False,
                    "failure_stage": metadata.get("failure_stage"),
                    "error": metadata.get("error") or metadata.get("input_error") or metadata.get("image_errors")}
        missing = [name for name in metadata.get("asset_names", []) if name not in images]
        if missing:
            return {"run_id": metadata["run_id"], "replayed": False,
                    "failure_stage": "diagnostic_assets", "error": f"검출 템플릿 PNG 누락: {missing}"}
        trace = {}
        result = run_detector(metadata["feature"], frame, images, trace)
        result = None if result is None else list(result)
        return {"run_id": metadata["run_id"], "replayed": True, "result": result,
                "matches_recorded": result == metadata["result"], "trace": trace,
                "same_app_version": metadata["app_version"] == version.__version__}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="자동찾기 진단 ZIP 재실행")
    parser.add_argument("zip", type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.zip), ensure_ascii=False, indent=2))
