"""설정·비밀 로더.

- 넥슨 API 키: `.env`(개발) 또는 `config.local.json`(배포판 설정 입력)에서 읽는다.
  둘 다 git에 커밋되지 않는다.
- 파티 키워드·제외 목록: `config.local.json`에 저장(없으면 기본값).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# src/mabinogi_addon/config.py → 프로젝트 루트
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
LOCAL_CONFIG_PATH = PROJECT_ROOT / "config.local.json"


def _load_env() -> None:
    """`.env`를 환경변수로 로드. python-dotenv 있으면 사용, 없으면 간단 파싱."""
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
    except ImportError:
        if ENV_PATH.exists():
            for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def _read_local_config(path: Path = LOCAL_CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _write_local_config(data: dict, path: Path = LOCAL_CONFIG_PATH) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_nexon_api_key() -> str | None:
    """키 탐색 순서: `.env`/환경변수 → `config.local.json`의 nexonApiKey."""
    _load_env()
    key = os.environ.get("NEXON_API_KEY")
    if key and key.strip():
        return key.strip()
    key = _read_local_config().get("nexonApiKey")
    return key.strip() if isinstance(key, str) and key.strip() else None


def load_party_lists() -> tuple[list[str], list[str]]:
    """(keywords, excludeLeaders)를 로컬 설정에서 읽는다."""
    data = _read_local_config()
    party = data.get("party", {}) if isinstance(data.get("party"), dict) else {}
    keywords = [str(x) for x in party.get("keywords", [])]
    excludes = [str(x) for x in party.get("excludeLeaders", [])]
    return keywords, excludes


def save_party_lists(keywords: list[str], excludes: list[str]) -> None:
    """키워드·제외 목록을 로컬 설정에 저장(다른 설정은 보존)."""
    data = _read_local_config()
    party = data.get("party", {})
    if not isinstance(party, dict):
        party = {}
    party["keywords"] = keywords
    party["excludeLeaders"] = excludes
    data["party"] = party
    _write_local_config(data)


# ---- 버프별 설정 (기획서 6 buffTracker.buffs) ----


@dataclass
class AlertConfig:
    enabled: bool = True
    before_sec: int = 30
    blink: bool = True
    sound: bool = True


@dataclass
class BuffSettings:
    """버프 하나의 사용자 설정. 카탈로그(아이콘·이미지)와 별개로 id로 연결된다."""

    id: str
    name: str = ""  # 표시 이름(비우면 id 사용)
    show_duration: bool = True
    hidden: bool = False  # 오버레이에서 숨김(목록엔 남김)
    alert: AlertConfig = field(default_factory=AlertConfig)


def _settings_from_dict(raw: dict) -> BuffSettings:
    alert = raw.get("alert") or {}
    return BuffSettings(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        show_duration=bool(raw.get("showDuration", True)),
        hidden=bool(raw.get("hidden", False)),
        alert=AlertConfig(
            enabled=bool(alert.get("enabled", True)),
            before_sec=int(alert.get("beforeSec", 30)),
            blink=bool(alert.get("blink", True)),
            sound=bool(alert.get("sound", True)),
        ),
    )


def _settings_to_dict(s: BuffSettings) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "showDuration": s.show_duration,
        "hidden": s.hidden,
        "alert": {
            "enabled": s.alert.enabled,
            "beforeSec": s.alert.before_sec,
            "blink": s.alert.blink,
            "sound": s.alert.sound,
        },
    }


def load_buff_settings(path: Path = LOCAL_CONFIG_PATH) -> list[BuffSettings]:
    """저장된 버프 설정을 순서대로 반환(목록 표시 순서 = 저장 순서)."""
    raw = (_read_local_config(path).get("buffTracker") or {}).get("buffs") or []
    return [_settings_from_dict(b) for b in raw if b.get("id")]


def save_buff_settings(
    items: list[BuffSettings], path: Path = LOCAL_CONFIG_PATH
) -> None:
    data = _read_local_config(path)
    bt = data.get("buffTracker")
    if not isinstance(bt, dict):
        bt = {}
    bt["buffs"] = [_settings_to_dict(s) for s in items]
    data["buffTracker"] = bt
    _write_local_config(data, path)
