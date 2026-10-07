"""자산·사용자 데이터 경로 해석 (개발/배포 공용).

- 번들(읽기전용) 자산: `resource_dir()` — 개발 땐 패키지의 assets/, exe(frozen)면
  PyInstaller 임시 추출 폴더(_MEIPASS)/assets.
- 사용자 데이터(쓰기 가능): `user_data_dir()` — 개발 땐 repo의 devdata/(내 머신끼리
  git로 동기화), exe면 %LOCALAPPDATA%\\StarlineMabinogiAddon(업데이트해도 유지).
- 설정 파일: `config_path()` — 개발 땐 기존처럼 repo 루트(비밀 유지), exe면 사용자
  데이터 폴더.

카탈로그는 '번들 기본 + 사용자 커스텀'을 합쳐서 읽고, 사용자가 추가한 아이콘·설정은
항상 사용자 데이터 폴더에 쓴다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent  # src/mabinogi_addon
_PROJECT_ROOT = _PKG.parents[1]  # repo 루트(개발)
_APP_DIRNAME = "StarlineMabinogiAddon"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return _PROJECT_ROOT


def resource_dir() -> Path:
    """번들(읽기전용) 자산 루트(assets/)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", _PKG))
        return base / "assets"
    return _PKG / "assets"


def user_data_dir() -> Path:
    """사용자 쓰기 가능 데이터 루트(커스텀 아이콘·설정)."""
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        d = Path(base) / _APP_DIRNAME
    else:
        d = _PROJECT_ROOT / "devdata"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    """설정 파일 경로. 개발은 repo 루트(기존 유지), exe는 사용자 데이터 폴더."""
    if is_frozen():
        return user_data_dir() / "config.local.json"
    return _PROJECT_ROOT / "config.local.json"
