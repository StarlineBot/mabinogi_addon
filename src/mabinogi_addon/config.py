"""설정·비밀 로더.

- 넥슨 API 키: `.env`(개발) 또는 `config.local.json`(배포판 설정 입력)에서 읽는다.
  둘 다 git에 커밋되지 않는다.
- 파티 키워드·제외 목록: `config.local.json`에 저장(없으면 기본값).
"""

from __future__ import annotations

import json
import os
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


def _read_local_config() -> dict:
    if not LOCAL_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _write_local_config(data: dict) -> None:
    LOCAL_CONFIG_PATH.write_text(
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
