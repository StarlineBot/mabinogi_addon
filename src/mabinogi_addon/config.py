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

# 앱 식별 정보(창 제목·트레이·제작자 표기)
APP_NAME = "섯다라인 마비노기 애드온"
CREATOR_NAME = "HP Starline"


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


def get_inquiry_webhook_url() -> str | None:
    """문의 전송용 Discord 웹훅 URL.

    탐색 순서: `.env`/환경변수(INQUIRY_WEBHOOK_URL) → `config.local.json`의
    inquiryWebhookUrl. 넥슨 API 키와 같은 '앱이 보관하는 비밀' — git에 커밋하지 않고
    배포 때 번들한다.
    """
    _load_env()
    url = os.environ.get("INQUIRY_WEBHOOK_URL")
    if url and url.strip():
        return url.strip()
    url = _read_local_config().get("inquiryWebhookUrl")
    return url.strip() if isinstance(url, str) and url.strip() else None


def load_party_lists() -> tuple[list[str], list[str]]:
    """(keywords, excludeLeaders)를 로컬 설정에서 읽는다."""
    data = _read_local_config()
    party = data.get("party", {}) if isinstance(data.get("party"), dict) else {}
    keywords = [str(x) for x in party.get("keywords", [])]
    excludes = [str(x) for x in party.get("excludeLeaders", [])]
    return keywords, excludes


def load_party_alert_sound(path: Path = LOCAL_CONFIG_PATH) -> bool:
    """키워드 알림 효과음 사용 여부(기본 켜짐)."""
    data = _read_local_config(path)
    party = data.get("party", {}) if isinstance(data.get("party"), dict) else {}
    v = party.get("alertSound")
    return bool(v) if isinstance(v, bool) else True


def save_party_alert_sound(on: bool, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    party = data.get("party")
    if not isinstance(party, dict):
        party = {}
    party["alertSound"] = bool(on)
    data["party"] = party
    _write_local_config(data, path)


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
    enabled2: bool = False  # 2차 알림(놓침·오독 대비 재알림) 사용 여부
    before_sec2: int = 5  # 2차 알림 기준(만료 N초 전)


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
            enabled2=bool(alert.get("enabled2", False)),
            before_sec2=int(alert.get("beforeSec2", 5)),
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
            "enabled2": s.alert.enabled2,
            "beforeSec2": s.alert.before_sec2,
        },
    }


def _load_settings(section: str, key: str, path: Path) -> list[BuffSettings]:
    raw = (_read_local_config(path).get(section) or {}).get(key) or []
    return [_settings_from_dict(b) for b in raw if b.get("id")]


def _save_settings(
    items: list[BuffSettings], section: str, key: str, path: Path
) -> None:
    data = _read_local_config(path)
    sec = data.get(section)
    if not isinstance(sec, dict):
        sec = {}
    sec[key] = [_settings_to_dict(s) for s in items]
    data[section] = sec
    _write_local_config(data, path)


def load_buff_settings(path: Path = LOCAL_CONFIG_PATH) -> list[BuffSettings]:
    """저장된 버프 설정을 순서대로 반환(목록 표시 순서 = 저장 순서)."""
    return _load_settings("buffTracker", "buffs", path)


def save_buff_settings(items: list[BuffSettings], path: Path = LOCAL_CONFIG_PATH) -> None:
    _save_settings(items, "buffTracker", "buffs", path)


def load_capture_region(
    section: str = "buffTracker", path: Path = LOCAL_CONFIG_PATH
) -> dict | None:
    """저장된 캡처 영역 {x,y,w,h} 또는 None."""
    sec = _read_local_config(path).get(section) or {}
    region = sec.get("captureRegion")
    return region if isinstance(region, dict) else None


def save_capture_region(
    x: int, y: int, w: int, h: int,
    section: str = "buffTracker",
    path: Path = LOCAL_CONFIG_PATH,
) -> None:
    data = _read_local_config(path)
    sec = data.get(section)
    if not isinstance(sec, dict):
        sec = {}
    sec["captureRegion"] = {"x": x, "y": y, "w": w, "h": h}
    data[section] = sec
    _write_local_config(data, path)


def load_overlay_state(
    section: str = "buffTracker", path: Path = LOCAL_CONFIG_PATH
) -> dict | None:
    """저장된 오버레이 상태 {x,y,locked} 또는 None."""
    sec = _read_local_config(path).get(section) or {}
    state = sec.get("overlay")
    return state if isinstance(state, dict) else None


def save_overlay_state(
    x: int,
    y: int,
    locked: bool,
    section: str = "buffTracker",
    path: Path = LOCAL_CONFIG_PATH,
) -> None:
    data = _read_local_config(path)
    sec = data.get(section)
    if not isinstance(sec, dict):
        sec = {}
    sec["overlay"] = {"x": x, "y": y, "locked": locked}
    data[section] = sec
    _write_local_config(data, path)


def load_overlay_scales(path: Path = LOCAL_CONFIG_PATH) -> tuple[int, int]:
    """(버프 배율%, 디버프 배율%). 기본 150 / 100."""
    s = _read_local_config(path).get("overlay") or {}
    return int(s.get("buffScale", 150)), int(s.get("debuffScale", 100))


def save_overlay_scales(
    buff_scale: int, debuff_scale: int, path: Path = LOCAL_CONFIG_PATH
) -> None:
    data = _read_local_config(path)
    s = data.get("overlay")
    if not isinstance(s, dict):
        s = {}
    s["buffScale"] = buff_scale
    s["debuffScale"] = debuff_scale
    data["overlay"] = s
    _write_local_config(data, path)


def load_general_flag(
    key: str, default: bool = False, path: Path = LOCAL_CONFIG_PATH
) -> bool:
    """general 섹션의 불리언 설정(없으면 default)."""
    g = _read_local_config(path).get("general") or {}
    v = g.get(key)
    return bool(v) if isinstance(v, bool) else default


def save_general_flag(key: str, value: bool, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    g = data.get("general")
    if not isinstance(g, dict):
        g = {}
    g[key] = bool(value)
    data["general"] = g
    _write_local_config(data, path)


def load_game_exe(path: Path = LOCAL_CONFIG_PATH) -> str | None:
    """포그라운드 판정에 쓸 게임 실행파일명(basename). 없으면 None(제목 폴백)."""
    g = _read_local_config(path).get("general") or {}
    exe = g.get("gameExe")
    return exe.strip().lower() if isinstance(exe, str) and exe.strip() else None


def save_game_exe(exe: str, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    g = data.get("general")
    if not isinstance(g, dict):
        g = {}
    g["gameExe"] = exe
    data["general"] = g
    _write_local_config(data, path)


def set_buff_scale(pct: int, path: Path = LOCAL_CONFIG_PATH) -> None:
    _, debuff = load_overlay_scales(path)
    save_overlay_scales(pct, debuff, path)


def set_debuff_scale(pct: int, path: Path = LOCAL_CONFIG_PATH) -> None:
    buff, _ = load_overlay_scales(path)
    save_overlay_scales(buff, pct, path)


def load_memo(path: Path = LOCAL_CONFIG_PATH) -> dict:
    """메모 상태 {text, locked, fontSize}. 없으면 빈 dict."""
    m = _read_local_config(path).get("memo")
    return m if isinstance(m, dict) else {}


def save_memo(
    text: str, locked: bool, font_size: int, path: Path = LOCAL_CONFIG_PATH
) -> None:
    data = _read_local_config(path)
    data["memo"] = {"text": text, "locked": locked, "fontSize": font_size}
    _write_local_config(data, path)


def load_debuff_settings(path: Path = LOCAL_CONFIG_PATH) -> list[BuffSettings]:
    """디버프 설정(이름·노출 여부·순서). 지속시간·알림은 쓰지 않는다."""
    return _load_settings("debuffTracker", "debuffs", path)


def save_debuff_settings(
    items: list[BuffSettings], path: Path = LOCAL_CONFIG_PATH
) -> None:
    _save_settings(items, "debuffTracker", "debuffs", path)
