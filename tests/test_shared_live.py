"""공유 라이브 카메라의 GPU/출력 폴백·검증 (dxcam 없이 가짜 모듈로)."""

import sys

import pytest

from mabinogi_addon.capture import shared_live


class _FakeCam:
    def __init__(self, behavior: str) -> None:
        # behavior: "ok"(프레임 반환) / "dead"(항상 None) / "raise"(grab에서 예외)
        self.behavior = behavior
        self.released = False

    def grab(self):
        if self.behavior == "ok":
            return object()
        if self.behavior == "raise":
            raise RuntimeError("DuplicateOutput 실패")
        return None

    def release(self):
        self.released = True


class _FakeDxcam:
    """table: {(device_idx, output_idx): behavior}. 없으면 create가 None."""

    def __init__(self, table: dict) -> None:
        self.table = table
        self.created: list[tuple] = []
        self.cams: dict[tuple, _FakeCam] = {}

    def create(self, device_idx=None, output_idx=None, output_color="RGB"):
        key = (device_idx, output_idx)
        self.created.append(key)
        behavior = self.table.get(key)
        if behavior is None:
            return None
        cam = _FakeCam(behavior)
        self.cams[key] = cam
        return cam

    def output_info(self):
        return "Device[0] Output[0]: Res:(1920,1080)"


@pytest.fixture(autouse=True)
def _fast_probe(monkeypatch):
    # 죽은 카메라 검증 대기시간을 없애 테스트를 빠르게.
    monkeypatch.setattr(shared_live, "_PROBE_TRIES", 2)
    monkeypatch.setattr(shared_live, "_PROBE_GAP", 0.0)


def _install(monkeypatch, table) -> _FakeDxcam:
    fake = _FakeDxcam(table)
    monkeypatch.setitem(sys.modules, "dxcam", fake)
    return fake


def test_picks_default_when_it_works(monkeypatch):
    fake = _install(monkeypatch, {(None, None): "ok"})
    cam = shared_live._create_working_camera()
    assert cam is not None and cam.behavior == "ok"
    assert fake.created == [(None, None)]  # 기본이 되면 폴백 안 함


def test_falls_back_to_working_gpu_output(monkeypatch):
    """하이브리드 GPU: 기본·(0,0)은 캡처 안 되고 (0,1)이 되면 그걸 고른다."""
    fake = _install(
        monkeypatch,
        {(None, None): "dead", (0, 0): "dead", (0, 1): "ok"},
    )
    cam = shared_live._create_working_camera()
    assert cam is not None and cam.behavior == "ok"
    # 기본 → (0,0) → (0,1) 순으로 시도
    assert fake.created[:3] == [(None, None), (0, 0), (0, 1)]
    # 캡처 안 되던 카메라는 해제됨
    assert fake.cams[(None, None)].released and fake.cams[(0, 0)].released


def test_dead_camera_that_raises_is_skipped(monkeypatch):
    fake = _install(monkeypatch, {(None, None): "raise", (0, 0): "ok"})
    cam = shared_live._create_working_camera()
    assert cam is not None and cam.behavior == "ok"
    assert fake.cams[(None, None)].released


def test_returns_none_when_nothing_works(monkeypatch):
    fake = _install(monkeypatch, {(None, None): "dead"})  # 나머지 조합은 None
    cam = shared_live._create_working_camera()
    assert cam is None
    # 기본 + device/output 조합 전부 시도했음
    assert (None, None) in fake.created and (1, 3) in fake.created


def test_shared_camera_raises_when_unavailable(monkeypatch):
    _install(monkeypatch, {})  # 어떤 조합도 안 됨
    with pytest.raises(RuntimeError):
        shared_live._SharedLiveCamera()
