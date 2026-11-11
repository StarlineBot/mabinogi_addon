"""설정 동기화(서버) — 계정 관리 명세 3.3. 로그인한 사용자만, 작업 스레드에서.

코드 → 런타임 동작:
- 올릴 묶음 = `config.export_bundle`과 같은 ZIP(설정 + 직접 집은 아이콘)에서 **PC마다 다른 값**을 뺀 것 + `sync.json`(해상도·PC 이름).
- 바뀌었는지는 '뺀 뒤 내용'의 해시로 본다 → 동기화 기록·자동 찾기 지난 자리처럼 빼는 값만 바뀐 저장은 올리지 않는다.
- 받을 때: 이 PC의 빼는 값은 그대로 두고, **해상도가 다르면 위치 값(오버레이·읽기 영역·창 위치·직접 지정 고정)도 이 PC 것 유지**,
  그 뒤 `config.import_bundle`(가져오기와 같은 검사 — 비밀값·장치 값 유지, 아이콘 경로 확인)로 적용한다.
- 동기화 기록: config `settingsSync {enabled, rev, hash, at, device}` — 마지막으로 서버와 맞춘 rev와 그때 내용 해시.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

from . import config, paths

MAX_BYTES = 2 * 1024 * 1024  # 서버 상한(명세 3.3 제안)
SYNC_KEY = "settingsSync"
META_NAME = "sync.json"
# 빼는 값(명세 3.3): 비밀·장치 값(_SECRET_KEYS·_MACHINE_KEYS — export가 이미 뺌) + 아래
EXCLUDE_TOP = ("installId", "discordUser", "discordAccount", SYNC_KEY)
EXCLUDE_NESTED = {"general": ("gameExe", "lastSeenVersion", "firstUse", "firstUseGuideShown", "tourShown"),
                  "autofindV2": ("last",)}
# 해상도가 다르면 이 PC 것을 유지하는 값 — 좌표 dict({x, y}·{x, y, w, h}) 전부 + 직접 지정 고정 목록(영역과 한 묶음)
POSITION_LISTS = {"autofindV2": ("fixed",)}


# ---- 내용 다루기(순수) ----------------------------------------------------------------------------
def strip_for_sync(doc: dict) -> dict:
    """올릴 설정에서 PC마다 다른 값을 뺀다."""
    out = {k: copy.deepcopy(v) for k, v in doc.items() if k not in EXCLUDE_TOP}
    for section, keys in EXCLUDE_NESTED.items():
        sec = out.get(section)
        if isinstance(sec, dict):
            out[section] = {k: v for k, v in sec.items() if k not in keys}
    return out


def _is_geometry(value) -> bool:
    return (isinstance(value, dict) and {"x", "y"} <= value.keys() and set(value) <= {"x", "y", "w", "h"}
            and all(isinstance(value[k], (int, float)) and not isinstance(value[k], bool) for k in value))


def _has_geometry(value) -> bool:
    if _is_geometry(value):
        return True
    if isinstance(value, dict):
        return any(_has_geometry(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_geometry(v) for v in value)
    return False


_MISSING = object()


def _keep_local_positions(incoming, local):
    """incoming 안의 좌표 값을 local 것으로(없으면 뺀다). 좌표가 섞인 목록은 길이가 다르면 local 목록 통째로."""
    if _is_geometry(incoming):
        return copy.deepcopy(local) if _is_geometry(local) else _MISSING
    if isinstance(incoming, dict):
        out = {}
        for key, value in incoming.items():
            got = _keep_local_positions(value, local.get(key, _MISSING) if isinstance(local, dict) else _MISSING)
            if got is not _MISSING:
                out[key] = got
        if isinstance(local, dict):  # 이 PC에만 있는 좌표(예: 이 PC에서만 옮긴 오버레이)도 유지
            for key, value in local.items():
                if key not in out and _is_geometry(value):
                    out[key] = copy.deepcopy(value)
        return out
    if isinstance(incoming, list) and _has_geometry(incoming):
        if isinstance(local, list) and len(local) == len(incoming):
            kept = [_keep_local_positions(a, b) for a, b in zip(incoming, local)]
            return [v for v in kept if v is not _MISSING]
        return copy.deepcopy(local) if isinstance(local, list) else _MISSING
    return copy.deepcopy(incoming)


def merge_incoming(incoming: dict, local: dict, *, same_resolution: bool) -> dict:
    """받은 설정 + 이 PC의 빼는 값(+해상도가 다르면 위치 값) → 적용할 설정."""
    merged = strip_for_sync(incoming)
    if not same_resolution:
        merged = _keep_local_positions(merged, local)
        if merged is _MISSING:
            merged = {}
        for section, keys in POSITION_LISTS.items():
            for key in keys:
                sec_local = local.get(section) if isinstance(local.get(section), dict) else {}
                sec = merged.setdefault(section, {}) if isinstance(merged.get(section, {}), dict) else None
                if sec is None:
                    continue
                if key in sec_local:
                    sec[key] = copy.deepcopy(sec_local[key])
                else:
                    sec.pop(key, None)
    for key in EXCLUDE_TOP:
        if key in local:
            merged[key] = copy.deepcopy(local[key])
    for section, keys in EXCLUDE_NESTED.items():
        sec_local = local.get(section)
        if not isinstance(sec_local, dict):
            continue
        sec = merged.get(section)
        sec = dict(sec) if isinstance(sec, dict) else {}
        for key in keys:
            if key in sec_local:
                sec[key] = copy.deepcopy(sec_local[key])
        merged[section] = sec
    return merged


def content_hash(doc: dict, assets: list[tuple[str, int]]) -> str:
    """빼는 값을 뺀 설정 + 아이콘 파일(이름·크기)로 만든 지문 — 바뀌었는지 판단."""
    h = hashlib.sha256(json.dumps(strip_for_sync(doc), ensure_ascii=False, sort_keys=True).encode("utf-8"))
    for name, size in sorted(assets):
        h.update(f"\n{name}:{size}".encode("utf-8"))
    return h.hexdigest()


# ---- 동기화 기록 ----------------------------------------------------------------------------------
def record(raw: dict) -> dict:
    sec = raw.get(SYNC_KEY)
    return dict(sec) if isinstance(sec, dict) else {}


def enabled(raw: dict) -> bool:
    """로그인하면 기본 켬(명세 3.3)."""
    return record(raw).get("enabled", True) is not False


def save_record(path: Path = None, **values) -> None:
    path = config.LOCAL_CONFIG_PATH if path is None else path
    raw = config._read_local_config(path)
    sec = record(raw)
    sec.update(values)
    raw[SYNC_KEY] = sec
    config._write_local_config(raw, path)


# ---- 묶음 만들기·적용(작업 스레드) -------------------------------------------------------------------
def _assets(user_dir: Path) -> list[tuple[str, int]]:
    out = []
    for path in config._iter_user_files(user_dir, ""):
        out.append((path.relative_to(user_dir).as_posix(), path.stat().st_size))
    return out


def local_state(path: Path = None, user_dir: Path = None) -> tuple[dict, str]:
    """(설정 원본, 지금 내용 지문)."""
    path = config.LOCAL_CONFIG_PATH if path is None else path
    user_dir = paths.user_data_dir() if user_dir is None else Path(user_dir)
    raw = config._read_local_config(path)
    return raw, content_hash(raw, _assets(user_dir))


def build_blob(path: Path = None, user_dir: Path = None, *, resolution: str, device: str, app_version: str = "") -> tuple[bytes, str]:
    """올릴 ZIP(빼는 값 없음 + sync.json)과 내용 지문. 2MB를 넘으면 ValueError."""
    path = config.LOCAL_CONFIG_PATH if path is None else path
    user_dir = paths.user_data_dir() if user_dir is None else Path(user_dir)
    raw, digest = local_state(path, user_dir)
    blob = config.export_bundle_bytes(path, user_dir, transform=strip_for_sync,
                                      extra={META_NAME: json.dumps({"resolution": resolution, "device": device,
                                                                    "app": app_version, "created": time.time()},
                                                                   ensure_ascii=False)})
    if len(blob) > MAX_BYTES:
        raise ValueError(f"설정 묶음이 {MAX_BYTES // (1024 * 1024)}MB를 넘어요(아이콘이 너무 많음).")
    return blob, digest


def read_meta(blob: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return json.loads(z.read(META_NAME).decode("utf-8")) if META_NAME in z.namelist() else {}
    except Exception:  # noqa: BLE001
        return {}


def apply_blob(blob: bytes, path: Path = None, user_dir: Path = None, *, resolution: str) -> bool:
    """받은 묶음을 이 PC에 적용 → 해상도가 같아 위치까지 적용했으면 True.
    이 PC의 빼는 값은 유지, 해상도가 다르면 위치 값도 유지, 적용은 import_bundle(가져오기와 같은 검사)."""
    import tempfile
    path = config.LOCAL_CONFIG_PATH if path is None else path
    user_dir = paths.user_data_dir() if user_dir is None else Path(user_dir)
    if len(blob) > MAX_BYTES or not zipfile.is_zipfile(io.BytesIO(blob)):
        raise ValueError("서버 설정 묶음 형식이 올바르지 않아요.")
    meta = read_meta(blob)
    same = bool(meta.get("resolution")) and meta.get("resolution") == resolution
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = z.namelist()
        if config._BUNDLE_CONFIG_NAME not in names:
            raise ValueError("서버 설정 묶음에 설정이 없어요.")
        incoming = json.loads(z.read(config._BUNDLE_CONFIG_NAME).decode("utf-8"))
        if not isinstance(incoming, dict):
            raise ValueError("서버 설정 형식이 올바르지 않아요.")
        local = config._read_local_config(path)
        merged = merge_incoming(incoming, local, same_resolution=same)
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "sync.zip"
            with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as out:
                out.writestr(config._BUNDLE_CONFIG_NAME, json.dumps(merged, ensure_ascii=False))
                for name in names:
                    if name.startswith(config._BUNDLE_USERDATA_PREFIX) and not name.endswith("/"):
                        out.writestr(name, z.read(name))
            config.import_bundle(staged, path, user_dir)
    # import_bundle은 최상위 키 단위로 합친다 — 받은 설정에 없는 최상위 키도 지우지 않는다(이 PC 값 유지)
    return same


def device_name() -> str:
    import platform
    return platform.node() or "PC"
