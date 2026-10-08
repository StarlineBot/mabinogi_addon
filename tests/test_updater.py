"""자동 업데이트 버전 비교 로직 회귀 테스트 (맥/리눅스에서도 실행 가능).

네트워크·파일 교체(apply_update)는 OS/환경 의존이라 여기선 순수 로직만 본다.
"""

from __future__ import annotations

from mabinogi_addon.system import updater


def test_is_newer_basic() -> None:
    assert updater.is_newer("0.2.0", "0.1.7")
    assert updater.is_newer("1.0.0", "0.9.9")
    assert updater.is_newer("0.1.8", "0.1.7")


def test_is_not_newer_when_same_or_older() -> None:
    assert not updater.is_newer("0.1.7", "0.1.7")
    assert not updater.is_newer("0.1.6", "0.1.7")
    assert not updater.is_newer("0.0.9", "0.1.0")


def test_version_prefix_and_extra_parts_ignored() -> None:
    # "v" 접두사나 네 번째 숫자가 섞여도 앞 3자리로 비교.
    assert updater.is_newer("v0.2.0", "0.1.0")
    assert not updater.is_newer("0.1.0.5", "0.1.0")


def test_can_update_false_in_dev() -> None:
    # 개발(uv) 실행은 frozen도 아니고 버전이 0.0.0 → 업데이트 시도 안 함.
    assert updater.can_update() is False
