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

from . import paths

# src/mabinogi_addon/config.py → 프로젝트 루트
PROJECT_ROOT = paths.project_root()
ENV_PATH = PROJECT_ROOT / ".env"
# 설정 파일: 개발=repo 루트(기존 유지), exe=사용자 데이터 폴더(paths.config_path).
LOCAL_CONFIG_PATH = paths.config_path()

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
    # 본 파일이 깨졌으면(.bak) 백업으로 복구 시도 → 전원차단 등으로 손상돼도 설정 보존.
    for p in (path, path.with_name(path.name + ".bak")):
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.strip():
            continue  # 빈 파일(쓰다 중단) → 다음 후보로
        try:
            return json.loads(text)
        except ValueError:
            continue
    return {}


def _write_local_config(data: dict, path: Path = LOCAL_CONFIG_PATH) -> None:
    """원자적 저장: 임시 파일에 쓰고 flush+fsync 후 os.replace로 교체한다. 쓰는
    도중 전원이 끊겨도 본 파일은 '이전 정상본' 아니면 '새 완본'이라 절대 깨지지
    않는다(빈 파일로 초기화되던 문제 방지). 교체 직전 직전본을 .bak로 보존한다."""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        try:
            os.replace(path, path.with_name(path.name + ".bak"))  # 직전본 백업
        except OSError:  # 백업 실패해도 본 저장은 진행
            pass
    os.replace(tmp, path)  # 원자적 교체


# 내보내기에서 제외할 비밀값(공유·이동 시 유출 방지). 가져올 때도 덮어쓰지 않음.
_SECRET_KEYS = ("nexonApiKey", "inquiryWebhookUrl")


def config_json_for_export(path: Path = LOCAL_CONFIG_PATH) -> str:
    """내보낼 설정 JSON 문자열(비밀값 제외). 파일 저장·디스코드 전송 공용."""
    data = {k: v for k, v in _read_local_config(path).items() if k not in _SECRET_KEYS}
    return json.dumps(data, ensure_ascii=False, indent=2)


def _merge_config_text(text: str, path: Path) -> None:
    """설정 JSON 문자열을 병합(비밀값은 기존 유지). 형식 오류면 ValueError."""
    incoming = json.loads(text)
    if not isinstance(incoming, dict):
        raise ValueError("설정 파일 형식이 올바르지 않습니다")  # noqa: TRY004
    data = _read_local_config(path)
    for key, value in incoming.items():
        if key not in _SECRET_KEYS:
            data[key] = value
    _write_local_config(data, path)


def import_config(src: Path, path: Path = LOCAL_CONFIG_PATH) -> None:
    """단일 JSON 파일에서 설정을 가져와 병합(레거시). 비밀값은 기존 것 유지."""
    _merge_config_text(Path(src).read_text(encoding="utf-8"), path)


# ---- 전체 백업(zip): 설정 + 사용자 자산(커스텀 버프·디버프 아이콘 등) ----
# 설정 JSON만으론 부족하다. 버프 목록·순서·고정은 '아이콘 파일'(카탈로그)이 있어야
# 복원되는데, 그 파일들은 사용자 데이터 폴더에 있고 config.local.json엔 없다.
# 그래서 다른 PC(특히 exe)로 옮길 땐 설정 + 자산 파일을 zip 하나로 묶는다.
_BUNDLE_CONFIG_NAME = "config.json"
_BUNDLE_USERDATA_PREFIX = "userdata/"


def _iter_user_files(user_dir: Path, config_name: str):
    """사용자 데이터 폴더의 모든 파일(비밀 담긴 config.local.json은 제외)."""
    if not user_dir.exists():
        return
    for p in sorted(user_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.parent == user_dir and p.name == config_name:
            continue  # 비밀값 유출 방지(별도 sanitized config.json으로만 포함)
        yield p


def export_bundle_bytes(
    path: Path = LOCAL_CONFIG_PATH, user_dir: Path | None = None
) -> bytes:
    """설정 + 사용자 자산을 zip 바이트로. 파일 저장·디스코드 DM 공용."""
    import io
    import zipfile

    if user_dir is None:
        user_dir = paths.user_data_dir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(_BUNDLE_CONFIG_NAME, config_json_for_export(path))
        for f in _iter_user_files(user_dir, path.name):
            rel = f.relative_to(user_dir).as_posix()
            z.write(f, _BUNDLE_USERDATA_PREFIX + rel)
    return buf.getvalue()


def export_bundle(
    dest: Path, path: Path = LOCAL_CONFIG_PATH, user_dir: Path | None = None
) -> None:
    """현재 설정 + 사용자 자산을 zip 파일로 저장(비밀값 제외)."""
    Path(dest).write_bytes(export_bundle_bytes(path, user_dir))


def _safe_extract_path(base: Path, rel: str) -> Path | None:
    """zip 멤버 경로를 base 안으로만 풀도록 검증(zip slip 방지). 벗어나면 None."""
    base = base.resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def import_bundle(
    src: Path, path: Path = LOCAL_CONFIG_PATH, user_dir: Path | None = None
) -> None:
    """백업을 가져온다. zip(설정+자산) 또는 단일 JSON(레거시) 모두 수용."""
    import zipfile

    src = Path(src)
    if not zipfile.is_zipfile(src):
        import_config(src, path)  # 레거시 단일 JSON
        return
    if user_dir is None:
        user_dir = paths.user_data_dir()
    with zipfile.ZipFile(src) as z:
        config_text: str | None = None
        for name in z.namelist():
            if name.endswith("/"):
                continue
            if name == _BUNDLE_CONFIG_NAME:
                config_text = z.read(name).decode("utf-8")
            elif name.startswith(_BUNDLE_USERDATA_PREFIX):
                rel = name[len(_BUNDLE_USERDATA_PREFIX):]
                dest = _safe_extract_path(user_dir, rel)
                if dest is None:
                    continue  # 경로 탈출 시도 멤버는 건너뛴다
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(name))
        if config_text is None:
            raise ValueError("백업 파일에 설정(config.json)이 없습니다")
        _merge_config_text(config_text, path)


def reset_config(path: Path = LOCAL_CONFIG_PATH) -> None:
    """모든 사용자 설정을 지운다(비밀값은 유지해 API 키·웹훅은 보존)."""
    data = _read_local_config(path)
    kept = {k: v for k, v in data.items() if k in _SECRET_KEYS}
    _write_local_config(kept, path)


def _bundled(name: str) -> str | None:
    """빌드 시 번들된 비밀값(개발 땐 빈 값). 없으면 None."""
    try:
        from . import _bundled as b

        v = getattr(b, name, "")
        return v.strip() if isinstance(v, str) and v.strip() else None
    except Exception:  # noqa: BLE001 — 번들 모듈 없음/깨짐 → 폴백 없음
        return None


def get_nexon_api_key() -> str | None:
    """키 탐색 순서: `.env`/환경변수 → `config.local.json` → 번들(배포 exe)."""
    _load_env()
    key = os.environ.get("NEXON_API_KEY")
    if key and key.strip():
        return key.strip()
    key = _read_local_config().get("nexonApiKey")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return _bundled("NEXON_API_KEY")


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
    if isinstance(url, str) and url.strip():
        return url.strip()
    return _bundled("INQUIRY_WEBHOOK_URL")


def get_config_webhook_url() -> str | None:
    """설정 백업(디스코드 DM 릴레이)용 웹훅 URL.

    탐색 순서: `.env`/환경변수(CONFIG_WEBHOOK_URL) → `config.local.json`의
    configWebhookUrl → 번들. 봇이 이 채널을 보고 첨부된 설정을 작성자에게 DM한다.
    """
    _load_env()
    url = os.environ.get("CONFIG_WEBHOOK_URL")
    if url and url.strip():
        return url.strip()
    url = _read_local_config().get("configWebhookUrl")
    if isinstance(url, str) and url.strip():
        return url.strip()
    return _bundled("CONFIG_WEBHOOK_URL")


def load_discord_user(path: Path = LOCAL_CONFIG_PATH) -> dict | None:
    """로그인한 Discord 사용자 {id, name} 또는 None(비로그인)."""
    u = _read_local_config(path).get("discordUser")
    return u if isinstance(u, dict) and u.get("id") else None


def save_discord_user(user_id: str, name: str, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    data["discordUser"] = {"id": str(user_id), "name": str(name)}
    _write_local_config(data, path)


def clear_discord_user(path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    data.pop("discordUser", None)
    _write_local_config(data, path)


def load_party_lists() -> tuple[list[str], list[str]]:
    """(keywords, excludeLeaders)를 로컬 설정에서 읽는다."""
    data = _read_local_config()
    party = data.get("party", {}) if isinstance(data.get("party"), dict) else {}
    keywords = [str(x) for x in party.get("keywords", [])]
    excludes = [str(x) for x in party.get("excludeLeaders", [])]
    return keywords, excludes


def load_party_server(path: Path = LOCAL_CONFIG_PATH) -> str:
    """파티모집 현황을 조회할 서버(기본 하프). 알 수 없는 값이면 하프로."""
    from .party.client import DEFAULT_SERVER, SERVERS

    data = _read_local_config(path)
    party = data.get("party", {}) if isinstance(data.get("party"), dict) else {}
    v = party.get("server")
    return v if v in SERVERS else DEFAULT_SERVER


def save_party_server(server: str, path: Path = LOCAL_CONFIG_PATH) -> None:
    from .party.client import DEFAULT_SERVER, SERVERS

    data = _read_local_config(path)
    party = data.get("party")
    if not isinstance(party, dict):
        party = {}
    party["server"] = server if server in SERVERS else DEFAULT_SERVER
    data["party"] = party
    _write_local_config(data, path)


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


def load_voice_pack(path: Path = LOCAL_CONFIG_PATH) -> str:
    """알림 목소리 팩 폴더 이름. 빈 문자열이면 기본(녹음본)."""
    v = _read_local_config(path).get("voice")
    pack = v.get("pack") if isinstance(v, dict) else None
    return pack if isinstance(pack, str) else ""


def save_voice_pack(pack: str, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    data["voice"] = {"pack": pack or ""}
    _write_local_config(data, path)


# 앱 테마: system(시스템 따름) / light / dark. 기본값은 다크(앱 디자인 기준 톤).
def load_theme(path: Path = LOCAL_CONFIG_PATH) -> str:
    v = _read_local_config(path).get("theme")
    return v if v in ("system", "light", "dark") else "dark"


def save_theme(name: str, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    data["theme"] = name if name in ("system", "light", "dark") else "dark"
    _write_local_config(data, path)


# 토스트 표시 모서리: br=우하단(기본) tr=우상단 bl=좌하단 tl=좌상단
TOAST_CORNERS = ("br", "tr", "bl", "tl")


def load_toast_corner(path: Path = LOCAL_CONFIG_PATH) -> str:
    """토스트 알림이 뜰 화면 모서리(기본 우하단)."""
    sec = _read_local_config(path).get("toast")
    corner = sec.get("corner") if isinstance(sec, dict) else None
    return corner if corner in TOAST_CORNERS else "br"


def save_toast_corner(corner: str, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    data["toast"] = {"corner": corner if corner in TOAST_CORNERS else "br"}
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
    enabled: bool = False  # 기본: 종료 알림 꺼짐(사용자가 필요한 버프만 켬)
    before_sec: int = 30
    sound: bool = True
    enabled2: bool = False  # 2차 알림(놓침·오독 대비 재알림) 사용 여부
    before_sec2: int = 5  # 2차 알림 기준(만료 N초 전)
    # 사라짐 경고: 추적 중이던 버프가 사라지면 오버레이에 그 자리를 잠깐(3초) 빨간
    # 테두리+X로 표시. 종료 알림(enabled)과 독립 — 소리 없이 시각으로만 알린다.
    warn_gone: bool = False


@dataclass
class BuffSettings:
    """버프 하나의 사용자 설정. 카탈로그(아이콘·이미지)와 별개로 id로 연결된다."""

    id: str
    name: str = ""  # 표시 이름(비우면 id 사용)
    show_duration: bool = False  # 기본: 지속시간 표시 꺼짐(오버레이 표시만 기본 ON)
    hidden: bool = False  # 오버레이에서 숨김(목록엔 남김)
    alert: AlertConfig = field(default_factory=AlertConfig)


def _settings_from_dict(raw: dict) -> BuffSettings:
    alert = raw.get("alert") or {}
    return BuffSettings(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        show_duration=bool(raw.get("showDuration", False)),
        hidden=bool(raw.get("hidden", False)),
        alert=AlertConfig(
            enabled=bool(alert.get("enabled", False)),
            before_sec=int(alert.get("beforeSec", 30)),
            sound=bool(alert.get("sound", True)),
            enabled2=bool(alert.get("enabled2", False)),
            before_sec2=int(alert.get("beforeSec2", 5)),
            warn_gone=bool(alert.get("warnGone", False)),
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
            "sound": s.alert.sound,
            "enabled2": s.alert.enabled2,
            "beforeSec2": s.alert.before_sec2,
            "warnGone": s.alert.warn_gone,
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


def seed_warn_gone_defaults(
    sound_ids: set[str], path: Path = LOCAL_CONFIG_PATH
) -> None:
    """최초 1회: '기본 음성알림 있는 버프'에 사라짐 경고를 켜 둔다(기존 사용자 이관).

    사라짐 경고는 새 기능이라 기존 설정엔 전부 꺼짐(기본값)으로 로드된다. 사용자가
    원하는 기본값('소리 있는 버프만 켜짐')을 한 번만 적용하고, 이후엔 사용자가 켜고
    끈 값을 존중한다(warnGoneSeeded 플래그로 재적용 방지).
    """
    data = _read_local_config(path)
    if data.get("warnGoneSeeded"):
        return
    items = load_buff_settings(path)
    for s in items:
        if s.id in sound_ids:
            s.alert.warn_gone = True
    save_buff_settings(items, path)
    data = _read_local_config(path)  # 위 저장 이후 파일 상태로 다시 읽어 플래그만 추가
    data["warnGoneSeeded"] = True
    _write_local_config(data, path)


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


def load_window_pos(path: Path = LOCAL_CONFIG_PATH) -> dict | None:
    """메인 창 위치 {x,y}. 없으면 None(→ 중앙 배치)."""
    g = _read_local_config(path).get("general") or {}
    p = g.get("windowPos")
    if isinstance(p, dict) and "x" in p and "y" in p:
        return {"x": int(p["x"]), "y": int(p["y"])}
    return None


def save_window_pos(x: int, y: int, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    g = data.get("general")
    if not isinstance(g, dict):
        g = {}
    g["windowPos"] = {"x": int(x), "y": int(y)}
    data["general"] = g
    _write_local_config(data, path)


_AUTOSTART_KEY = "autostart"  # general 섹션: Windows 시작 시 자동 실행 '의도'


def load_autostart_intent(path: Path = LOCAL_CONFIG_PATH) -> bool | None:
    """자동 실행 의도. 한 번도 설정 안 했으면 None(기존 작업 상태를 이어받도록)."""
    g = _read_local_config(path).get("general") or {}
    v = g.get(_AUTOSTART_KEY)
    return v if isinstance(v, bool) else None


def save_autostart_intent(on: bool, path: Path = LOCAL_CONFIG_PATH) -> None:
    save_general_flag(_AUTOSTART_KEY, on, path)


_LAST_SEEN_VERSION_KEY = "lastSeenVersion"  # general: 마지막으로 업데이트 노트를 본 버전


def load_last_seen_version(path: Path = LOCAL_CONFIG_PATH) -> str | None:
    """마지막으로 업데이트 노트를 띄운 앱 버전. 한 번도 없으면 None."""
    g = _read_local_config(path).get("general") or {}
    v = g.get(_LAST_SEEN_VERSION_KEY)
    return v if isinstance(v, str) and v else None


def save_last_seen_version(version: str, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    g = data.get("general")
    if not isinstance(g, dict):
        g = {}
    g[_LAST_SEEN_VERSION_KEY] = str(version)
    data["general"] = g
    _write_local_config(data, path)


def load_grid_size(path: Path = LOCAL_CONFIG_PATH) -> int:
    """오버레이 격자 칸 크기(px). 기본 32. 작을수록 미세, 클수록 큼직한 이동."""
    g = _read_local_config(path).get("general") or {}
    v = g.get("gridSize")
    return int(v) if isinstance(v, (int, float)) and int(v) > 0 else 32


def save_grid_size(px: int, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    g = data.get("general")
    if not isinstance(g, dict):
        g = {}
    g["gridSize"] = int(px)
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
    text: str,
    locked: bool,
    font_size: int,
    enabled: bool = True,
    path: Path = LOCAL_CONFIG_PATH,
) -> None:
    data = _read_local_config(path)
    data["memo"] = {
        "text": text,
        "locked": locked,
        "fontSize": font_size,
        "enabled": enabled,
    }
    _write_local_config(data, path)


def load_removed_defaults(
    section: str = "buffTracker", path: Path = LOCAL_CONFIG_PATH
) -> set[str]:
    """사용자가 '지운' 기본(번들) id 집합. 목록에서 걸러내는 데 쓴다."""
    sec = _read_local_config(path).get(section) or {}
    r = sec.get("removedDefaults")
    return {str(x) for x in r} if isinstance(r, list) else set()


def add_removed_default(
    item_id: str, section: str = "buffTracker", path: Path = LOCAL_CONFIG_PATH
) -> None:
    """기본 id를 '지움' 목록에 추가(배포돼도 계속 숨김 유지)."""
    removed = load_removed_defaults(section, path)
    removed.add(item_id)
    data = _read_local_config(path)
    sec = data.get(section)
    if not isinstance(sec, dict):
        sec = {}
    sec["removedDefaults"] = sorted(removed)
    data[section] = sec
    _write_local_config(data, path)


def load_tuarim(path: Path = LOCAL_CONFIG_PATH) -> dict:
    """투아림 설정. {enabled, box:{x,y,w,h,locked}, thresholds:[int], sounds:[bool,bool]}."""
    sec = _read_local_config(path).get("tuarim")
    sec = sec if isinstance(sec, dict) else {}
    box = sec.get("box") if isinstance(sec.get("box"), dict) else None
    thresholds = sec.get("thresholds")
    # % 판독이 90% 이상에서만 신뢰 가능(밝은 배경 저대비)하고, 투아림 알림의 목적도
    # 100% 직전 경고이므로 임계는 90~99로 제한한다(옛 설정값은 90으로 끌어올림).
    thresholds = (
        [min(99, max(90, int(x))) for x in thresholds]
        if isinstance(thresholds, list)
        else [90, 95]
    )
    sounds = sec.get("sounds")
    sounds = [bool(x) for x in sounds] if isinstance(sounds, list) else [True, True]
    return {
        "enabled": bool(sec.get("enabled", False)),
        "box": box,
        "thresholds": thresholds,
        "sounds": sounds,
    }


def save_tuarim(data: dict, path: Path = LOCAL_CONFIG_PATH) -> None:
    cfg = _read_local_config(path)
    sec = cfg.get("tuarim")
    if not isinstance(sec, dict):
        sec = {}
    sec.update(data)
    cfg["tuarim"] = sec
    _write_local_config(cfg, path)


# 보스 HP바 영역 — 디버프 트래커와 보스 패턴 알림이 '공유'한다. 둘 중 어디서 지정하든
# 같은 값을 쓰므로, 한쪽만 세팅해도 다른 쪽이 함께 세팅된 상태가 된다. 저장 위치는
# 공용 키 'bossBar' 하나(중앙 설정 UI 없이 값만 공유). 과거 보스 패턴 box에서 이관한다.
def load_bar_region(path: Path = LOCAL_CONFIG_PATH) -> dict | None:
    """공유 보스 HP바 영역 {x,y,w,h} 또는 None. (디버프·보스패턴 공용)"""
    data = _read_local_config(path)
    r = data.get("bossBar")
    if isinstance(r, dict) and all(k in r for k in ("x", "y", "w", "h")):
        return {k: int(r[k]) for k in ("x", "y", "w", "h")}
    # 이관: 예전 보스 패턴 영역(box)이 있으면 그걸 공유 영역으로. (디버프의 옛 strip
    # 영역은 바보다 커서 HP 판독을 깨뜨리므로 이관하지 않는다 — 재지정 안내.)
    sec = data.get("bossPattern")
    box = sec.get("box") if isinstance(sec, dict) else None
    if isinstance(box, dict) and all(k in box for k in ("x", "y", "w", "h")):
        return {k: int(box[k]) for k in ("x", "y", "w", "h")}
    return None


def save_bar_region(
    x: int, y: int, w: int, h: int, path: Path = LOCAL_CONFIG_PATH
) -> None:
    data = _read_local_config(path)
    data["bossBar"] = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
    _write_local_config(data, path)


def load_boss_pattern(path: Path = LOCAL_CONFIG_PATH) -> dict:
    """보스 패턴 경고 설정. (베타 — 디스코드 로그인 게이팅)

    {enabled, box:{x,y,w,h}, showUpcoming, upcomingLocked, upcomingPos:{x,y},
     warnLocked, warnPos:{x,y}}
    - showUpcoming: 왼쪽 '다음 패턴 목록' 오버레이 사용
    - upcomingLocked/upcomingPos: 그 목록의 고정 여부·위치
    - warnLocked/warnPos: 중앙 경고의 고정 여부·위치(없으면 기본 위치)
    """
    sec = _read_local_config(path).get("bossPattern")
    sec = sec if isinstance(sec, dict) else {}
    box = sec.get("box") if isinstance(sec.get("box"), dict) else None
    pos = sec.get("upcomingPos") if isinstance(sec.get("upcomingPos"), dict) else None
    warn_pos = sec.get("warnPos") if isinstance(sec.get("warnPos"), dict) else None
    return {
        "enabled": bool(sec.get("enabled", False)),
        "box": box,
        "showUpcoming": bool(sec.get("showUpcoming", False)),
        "upcomingLocked": bool(sec.get("upcomingLocked", False)),
        "upcomingPos": pos,
        "warnLocked": bool(sec.get("warnLocked", True)),
        "warnPos": warn_pos,
    }


def save_boss_pattern(data: dict, path: Path = LOCAL_CONFIG_PATH) -> None:
    cfg = _read_local_config(path)
    sec = cfg.get("bossPattern")
    if not isinstance(sec, dict):
        sec = {}
    sec.update(data)
    cfg["bossPattern"] = sec
    _write_local_config(cfg, path)


def _custom_section(path: Path) -> dict:
    sec = _read_local_config(path).get("customOverlay")
    return sec if isinstance(sec, dict) else {}


def load_custom_overlays(path: Path = LOCAL_CONFIG_PATH) -> list[dict]:
    """현재 커스텀 오버레이(미러) 목록."""
    items = _custom_section(path).get("overlays")
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


def save_custom_overlays(items: list[dict], path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    sec = data.get("customOverlay")
    if not isinstance(sec, dict):
        sec = {}
    sec["overlays"] = items
    data["customOverlay"] = sec
    _write_local_config(data, path)


def load_custom_presets(path: Path = LOCAL_CONFIG_PATH) -> dict[str, list[dict]]:
    """저장된 프리셋 {이름: [오버레이...]}."""
    presets = _custom_section(path).get("presets")
    if not isinstance(presets, dict):
        return {}
    return {
        str(k): [x for x in v if isinstance(x, dict)]
        for k, v in presets.items()
        if isinstance(v, list)
    }


def save_custom_preset(
    name: str, items: list[dict], path: Path = LOCAL_CONFIG_PATH
) -> None:
    data = _read_local_config(path)
    sec = data.get("customOverlay")
    if not isinstance(sec, dict):
        sec = {}
    presets = sec.get("presets")
    if not isinstance(presets, dict):
        presets = {}
    presets[name] = items
    sec["presets"] = presets
    data["customOverlay"] = sec
    _write_local_config(data, path)


def delete_custom_preset(name: str, path: Path = LOCAL_CONFIG_PATH) -> None:
    data = _read_local_config(path)
    sec = data.get("customOverlay")
    if not isinstance(sec, dict):
        return
    presets = sec.get("presets")
    if isinstance(presets, dict) and name in presets:
        del presets[name]
        sec["presets"] = presets
        data["customOverlay"] = sec
        _write_local_config(data, path)
    # 자동 불러오기로 지정된 프리셋이 삭제되면 지정도 해제한다.
    if sec.get("autoPreset") == name:
        sec.pop("autoPreset", None)
        data["customOverlay"] = sec
        _write_local_config(data, path)


def load_auto_preset(path: Path = LOCAL_CONFIG_PATH) -> str | None:
    """시작 시 자동 불러올 프리셋 이름(없으면 None)."""
    name = _custom_section(path).get("autoPreset")
    return name if isinstance(name, str) and name else None


def save_auto_preset(name: str | None, path: Path = LOCAL_CONFIG_PATH) -> None:
    """시작 시 자동 불러올 프리셋 지정(None이면 해제)."""
    data = _read_local_config(path)
    sec = data.get("customOverlay")
    if not isinstance(sec, dict):
        sec = {}
    if name:
        sec["autoPreset"] = name
    else:
        sec.pop("autoPreset", None)
    data["customOverlay"] = sec
    _write_local_config(data, path)


def load_debuff_settings(path: Path = LOCAL_CONFIG_PATH) -> list[BuffSettings]:
    """디버프 설정(이름·노출 여부·순서). 지속시간·알림은 쓰지 않는다."""
    return _load_settings("debuffTracker", "debuffs", path)


def save_debuff_settings(
    items: list[BuffSettings], path: Path = LOCAL_CONFIG_PATH
) -> None:
    _save_settings(items, "debuffTracker", "debuffs", path)
