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


class _FakeShot:
    def __init__(self, w: int, h: int) -> None:
        self.width = w
        self.height = h
        self.bgra = bytes(w * h * 4)  # 전부 0(검정) — 모양만 맞으면 됨


class _FakeMSS:
    def __init__(self, grab_fail: bool = False) -> None:
        self.grab_fail = grab_fail
        self.closed = False
        self.monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080},  # [0] 가상 데스크톱
            {"left": 0, "top": 0, "width": 1920, "height": 1080},  # [1] 주 모니터
        ]

    def grab(self, mon):
        if self.grab_fail:
            raise RuntimeError("캡처 불가")
        return _FakeShot(mon["width"], mon["height"])

    def close(self):
        self.closed = True


class _FakeMSSModule:
    """sys.modules['mss'] 대체. make_fail=True면 mss() 자체가 실패(헤드리스 흉내)."""

    def __init__(self, make_fail: bool = False, grab_fail: bool = False) -> None:
        self._make_fail = make_fail
        self._grab_fail = grab_fail
        self.instances: list[_FakeMSS] = []

    def mss(self):
        if self._make_fail:
            raise RuntimeError("디스플레이 없음(헤드리스)")
        inst = _FakeMSS(self._grab_fail)
        self.instances.append(inst)
        return inst


def test_raises_when_dxcam_and_mss_both_fail(monkeypatch):
    _install(monkeypatch, {})  # dxcam 어떤 조합도 안 됨
    monkeypatch.setitem(sys.modules, "mss", _FakeMSSModule(make_fail=True))
    with pytest.raises(RuntimeError):
        shared_live._SharedLiveCamera()


def test_falls_back_to_mss_when_dxcam_unavailable(monkeypatch):
    """하이브리드 GPU 노트북: dxcam은 전부 실패해도 mss(GDI)로 캡처가 된다."""
    _install(monkeypatch, {})  # dxcam 전부 실패
    fake_mss = _FakeMSSModule()
    monkeypatch.setitem(sys.modules, "mss", fake_mss)

    cam = shared_live._SharedLiveCamera()
    assert cam._camera is None  # dxcam 없음
    assert cam._mss is not None  # mss 폴백 사용 중

    frame = cam.full_frame()
    assert frame is not None
    assert frame.shape == (1080, 1920, 3)  # BGRA→BGR, 주 모니터 크기
    assert frame.flags["C_CONTIGUOUS"]  # 탐지 코드가 바로 쓸 수 있게 연속

    inst = fake_mss.instances[0]
    cam.release()  # _refs 0 → -1 ≤ 0 → 해제
    assert inst.closed  # mss도 닫힘
