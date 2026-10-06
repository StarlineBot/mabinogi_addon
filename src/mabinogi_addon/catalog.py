"""버프 카탈로그 (기획서 3.1 / 6).

매칭용 아이콘 폴더(icon/)와 오버레이 표시용 이미지 폴더(image/)를 훑어
버프 목록(BuffDef)을 만든다. 파일명(확장자·_enable 접미사 제거)을 키로 짝짓는다.
- matchIcon: 상태창에서 탐지할 16px 아이콘 (필수)
- displayImage: 오버레이에 표시할 이미지 (없으면 matchIcon으로 대체)

지금은 개발 데이터가 tests/data에 있다. 배포 때는 패키지 자산으로 옮긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import PROJECT_ROOT

DEFAULT_ICON_DIR = PROJECT_ROOT / "tests" / "data" / "icon"
DEFAULT_IMAGE_DIR = PROJECT_ROOT / "tests" / "data" / "image"
DEFAULT_DEBUFF_ICON_DIR = PROJECT_ROOT / "tests" / "data" / "debuff_icon"


def _stem(path: Path) -> str:
    """파일명에서 확장자와 _enable 접미사를 떼어낸 키."""
    return path.stem.removesuffix("_enable")


@dataclass(frozen=True)
class BuffDef:
    id: str
    name: str  # 표시 이름(기본=id). GUI에서 한글로 바꿀 수 있다.
    match_icon: Path  # 탐지용 아이콘 (필수)
    display_image: Path | None  # 오버레이 표시용 (없으면 matchIcon 사용)


def load_catalog(
    icon_dir: Path = DEFAULT_ICON_DIR,
    image_dir: Path = DEFAULT_IMAGE_DIR,
) -> list[BuffDef]:
    """matchIcon이 있는 버프만 id 순으로 반환. displayImage는 있으면 짝지운다."""
    icons = {_stem(p): p for p in icon_dir.glob("*.png")}
    images = {_stem(p): p for p in image_dir.glob("*.png")}

    catalog = [
        BuffDef(
            id=key,
            name=key,
            match_icon=icon_path,
            display_image=images.get(key),
        )
        for key, icon_path in sorted(icons.items())
    ]
    return catalog


def load_debuff_catalog(icon_dir: Path = DEFAULT_DEBUFF_ICON_DIR) -> list[BuffDef]:
    """디버프 매칭 아이콘 폴더 → 디버프 목록. (표시이미지 없음 → 오버레이는 matchIcon)"""
    icons = {p.stem: p for p in icon_dir.glob("*.png")}
    return [
        BuffDef(id=key, name=key, match_icon=path, display_image=None)
        for key, path in sorted(icons.items())
    ]


def load_template(path: Path) -> np.ndarray:
    """매칭용 BGR 템플릿 로드(알파는 무시 — 아이콘은 모두 불투명)."""
    return cv2.imread(str(path), cv2.IMREAD_COLOR)


def build_templates(catalog: list[BuffDef]) -> dict[str, np.ndarray]:
    """detect_buffs에 넘길 {buff_id: BGR 템플릿} 사전."""
    return {buff.id: load_template(buff.match_icon) for buff in catalog}
