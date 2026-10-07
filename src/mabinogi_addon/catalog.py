"""버프 카탈로그 (기획서 3.1 / 6).

매칭용 아이콘 폴더(icon/)와 오버레이 표시용 이미지 폴더(image/)를 훑어
버프 목록(BuffDef)을 만든다. 파일명(확장자·_enable 접미사 제거)을 키로 짝짓는다.
- matchIcon: 상태창에서 탐지할 16px 아이콘 (필수)
- displayImage: 오버레이에 표시할 이미지 (없으면 matchIcon으로 대체)

지금은 개발 데이터가 tests/data에 있다. 배포 때는 패키지 자산으로 옮긴다.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import paths
from .image_io import imread

# 번들(기본) 자산 — 읽기전용, exe에 포함
DEFAULT_ICON_DIR = paths.resource_dir() / "buff" / "icon"
DEFAULT_IMAGE_DIR = paths.resource_dir() / "buff" / "image"
DEFAULT_DEBUFF_ICON_DIR = paths.resource_dir() / "debuff" / "icon"
# 사용자 커스텀 자산 — 쓰기 가능(사용자가 추가한 버프/디버프)
USER_ICON_DIR = paths.user_data_dir() / "buff" / "icon"
USER_IMAGE_DIR = paths.user_data_dir() / "buff" / "image"
USER_DEBUFF_ICON_DIR = paths.user_data_dir() / "debuff" / "icon"
# 새 버프/디버프 등록 시 쓰는 빈(none) placeholder
NONE_MATCH_ICON = paths.resource_dir() / "placeholder" / "none.png"
NONE_DISPLAY_IMAGE = paths.resource_dir() / "placeholder" / "none_enable.png"


def _stem(path: Path) -> str:
    """파일명에서 확장자와 _enable 접미사를 떼어낸 키."""
    return path.stem.removesuffix("_enable")


@dataclass(frozen=True)
class BuffDef:
    id: str
    name: str  # 표시 이름(기본=id). GUI에서 한글로 바꿀 수 있다.
    match_icon: Path  # 탐지용 아이콘 (필수)
    display_image: Path | None  # 오버레이 표시용 (없으면 matchIcon 사용)


def _collect(dirs, key_fn) -> dict[str, Path]:
    """여러 폴더의 png를 key→경로로 모은다. 뒤 폴더(사용자)가 앞(기본)을 덮어쓴다."""
    out: dict[str, Path] = {}
    for directory in dirs:
        for path in directory.glob("*.png"):
            out[key_fn(path)] = path
    return out


def load_catalog(
    icon_dirs: tuple[Path, ...] = (DEFAULT_ICON_DIR, USER_ICON_DIR),
    image_dirs: tuple[Path, ...] = (DEFAULT_IMAGE_DIR, USER_IMAGE_DIR),
) -> list[BuffDef]:
    """번들 기본 + 사용자 커스텀을 합쳐, matchIcon 있는 버프만 id 순으로 반환."""
    icons = _collect(icon_dirs, _stem)
    images = _collect(image_dirs, _stem)
    return [
        BuffDef(id=key, name=key, match_icon=icon_path, display_image=images.get(key))
        for key, icon_path in sorted(icons.items())
    ]


def load_debuff_catalog(
    icon_dirs: tuple[Path, ...] = (DEFAULT_DEBUFF_ICON_DIR, USER_DEBUFF_ICON_DIR),
) -> list[BuffDef]:
    """번들 기본 + 사용자 커스텀 디버프 목록. (표시이미지 없음 → 오버레이는 matchIcon)"""
    icons = _collect(icon_dirs, lambda p: p.stem)
    return [
        BuffDef(id=key, name=key, match_icon=path, display_image=None)
        for key, path in sorted(icons.items())
    ]


def register_buff(
    name: str,
    match_icon_src: Path,
    display_image_src: Path | None = None,
    *,
    icon_dir: Path = USER_ICON_DIR,
    image_dir: Path = USER_IMAGE_DIR,
) -> str:
    """새 버프 등록: 고른 파일을 사용자 폴더에 {name}.png로 복사. 반환=버프 id."""
    name = name.strip()
    if not name:
        raise ValueError("이름이 비어 있습니다")
    icon_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(match_icon_src, icon_dir / f"{name}.png")
    if display_image_src is not None:
        image_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(display_image_src, image_dir / f"{name}.png")
    return name


def _delete_matching(directories, buff_id: str, key_fn) -> None:
    """여러 폴더에서 id가 일치하는 png 삭제. 읽기전용(번들/exe)이면 조용히 건너뜀."""
    for directory in directories:
        for path in directory.glob("*.png"):
            if key_fn(path) == buff_id:
                try:
                    path.unlink()
                except OSError:
                    pass  # 번들(읽기전용) 기본 아이콘 — 삭제 불가


#: 삭제 시 지울 폴더(사용자 폴더만). 번들 기본은 절대 파일 삭제하지 않는다 —
#  기본을 '지움'은 config의 removedDefaults로 기록해 목록에서 걸러낸다(배포돼도 유지).
_BUFF_DELETE_DIRS = (USER_ICON_DIR, USER_IMAGE_DIR)
DEBUFF_DELETE_DIRS = (USER_DEBUFF_ICON_DIR,)


def delete_buff(buff_id: str, *, dirs: tuple[Path, ...] = _BUFF_DELETE_DIRS) -> None:
    """사용자가 추가/덮어쓴 파일만 지운다(번들 기본은 건드리지 않음)."""
    _delete_matching(dirs, buff_id, _stem)


def default_buff_ids() -> set[str]:
    """번들(기본) 버프 id 집합."""
    return {_stem(p) for p in DEFAULT_ICON_DIR.glob("*.png")}


def default_debuff_ids() -> set[str]:
    """번들(기본) 디버프 id 집합."""
    return {p.stem for p in DEFAULT_DEBUFF_ICON_DIR.glob("*.png")}


def available_catalog() -> list[BuffDef]:
    """앱에서 실제로 쓰는 버프 목록(기본+커스텀 − 사용자가 지운 기본)."""
    from . import config

    removed = config.load_removed_defaults("buffTracker")
    return [b for b in load_catalog() if b.id not in removed]


def available_debuff_catalog() -> list[BuffDef]:
    """앱에서 실제로 쓰는 디버프 목록(기본+커스텀 − 사용자가 지운 기본)."""
    from . import config

    removed = config.load_removed_defaults("debuffTracker")
    return [b for b in load_debuff_catalog() if b.id not in removed]


def set_match_icon(buff_id: str, src: Path, *, icon_dir: Path = USER_ICON_DIR) -> None:
    """버프의 매칭 아이콘을 사용자 폴더에 저장(기본 아이콘이면 덮어쓰기=override)."""
    icon_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, icon_dir / f"{buff_id}.png")


def set_display_image(
    buff_id: str, src: Path, *, image_dir: Path = USER_IMAGE_DIR
) -> None:
    """버프의 표시 이미지를 사용자 폴더에 저장/추가."""
    image_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, image_dir / f"{buff_id}.png")


def clear_display_image(buff_id: str, *, image_dir: Path = USER_IMAGE_DIR) -> None:
    """버프의 표시 이미지 삭제(사용자·기본 양쪽, 오버레이는 매칭 아이콘 사용)."""
    _delete_matching({image_dir, DEFAULT_IMAGE_DIR}, buff_id, _stem)


def load_template(path: Path) -> np.ndarray | None:
    """매칭용 BGR 템플릿 로드(알파는 무시 — 아이콘은 모두 불투명).

    한글 경로도 읽히도록 유니코드 안전 로더 사용(Windows cv2.imread 한계 회피).
    """
    return imread(path, cv2.IMREAD_COLOR)


def build_templates(catalog: list[BuffDef]) -> dict[str, np.ndarray]:
    """detect_buffs에 넘길 {buff_id: BGR 템플릿} 사전. 못 읽은 아이콘은 건너뛴다."""
    out: dict[str, np.ndarray] = {}
    for buff in catalog:
        template = load_template(buff.match_icon)
        if template is not None:
            out[buff.id] = template
    return out
