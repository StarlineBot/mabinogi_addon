"""단일 인스턴스 가드: 두 번째 인스턴스는 '이미 실행 중'으로 판정된다."""

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication

from mabinogi_addon.system.single_instance import SingleInstance


def _app():
    return QCoreApplication.instance() or QCoreApplication([])


def test_second_instance_detected():
    _app()
    key = "test_" + uuid.uuid4().hex
    first = SingleInstance(key)
    assert first.already_running is False  # 첫 인스턴스
    second = SingleInstance(key)
    assert second.already_running is True  # 두 번째 → 이미 실행 중
    # first 를 끝까지 살려 둬야 세그먼트가 유지된다(참조 유지).
    assert first._shm is not None


def test_distinct_keys_do_not_collide():
    _app()
    a = SingleInstance("test_" + uuid.uuid4().hex)
    b = SingleInstance("test_" + uuid.uuid4().hex)
    assert a.already_running is False
    assert b.already_running is False
