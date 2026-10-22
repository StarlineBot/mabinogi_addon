from pathlib import Path
from threading import Event
from types import SimpleNamespace
import shutil
import pytest

from test_support.blackbox_codec import codec_host
from scripts.probe_blackbox_window import collect_frames, save_frames, run, FRAME_COUNT
from mabinogi_addon.blackbox_codec import CodecSettings
from mabinogi_addon.blackbox_native import NativeTransition


class Native:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.closed = False
    def open(self, target):
        self.target = target
    def read(self):
        value = next(self.frames)
        if isinstance(value, Exception):
            raise value
        return value
    def close(self):
        self.closed = True


def frames():
    return [(bytes([0, 0, 255, 255] if n % 2 else [255, 0, 0, 255]) * 16,
             4, 4, 1_000_000 + n * 100_000) for n in range(FRAME_COUNT)]


def test_windows_host_is_explicit_and_missing_is_failure(tmp_path):
    with pytest.raises(ValueError, match='BLACKBOX_CODEC_HOST'):
        codec_host(platform='win32', environ={})
    with pytest.raises(ValueError):
        codec_host(platform='win32', environ={'BLACKBOX_CODEC_HOST': 'relative.exe'})
    host = tmp_path / 'host.exe'; host.write_bytes(b'fixture only')
    assert codec_host(platform='win32', environ={'BLACKBOX_CODEC_HOST': str(host)}) == host
    assert codec_host(platform='linux', environ={}) is None


def test_owned_pattern_mock_and_real_encode(tmp_path):
    native = Native(frames())
    data, size, stamps = collect_frames(native, object(), Event())
    assert native.closed and len(data) == FRAME_COUNT and stamps == [f[3] for f in frames()]
    settings = CodecSettings(Path(shutil.which('ffmpeg')), Path(shutil.which('ffprobe')),
        'libx264', 100000, 10, 10, 50000, host=codec_host())
    result = save_frames(data, size, tmp_path / 'synthetic.mp4', settings)
    assert result.completed and result.validated and result.output.is_file()
    with pytest.raises(RuntimeError):
        save_frames(data, size, result.output, settings)


@pytest.mark.parametrize('value', [NativeTransition('foreground lost'), (bytes(64), 4, 4, 1000000)])
def test_foreground_loss_or_nonpattern_never_falls_back(value):
    native = Native([value])
    with pytest.raises((NativeTransition, ValueError)):
        collect_frames(native, object(), Event())
    assert native.closed


def test_probe_requires_explicit_capture_flag_before_any_platform_access():
    with pytest.raises(ValueError, match='explicit'):
        run(SimpleNamespace(run_owned_window_capture=False))


@pytest.mark.parametrize('failure', ['identity', 'thread_start'])
def test_setup_failure_closes_owned_window_and_records_error(tmp_path, monkeypatch, failure):
    import json
    from PySide6.QtWidgets import QApplication
    from scripts import probe_blackbox_window as probe
    app = QApplication.instance() or QApplication([])
    binary = tmp_path / 'fixture.exe'; binary.write_bytes(b'not executed')
    args = SimpleNamespace(run_owned_window_capture=True, library=binary, host=binary,
                           ffmpeg=binary, ffprobe=binary, output=tmp_path / 'output')
    monkeypatch.setattr(probe, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.delenv('QT_QPA_PLATFORM', raising=False)
    def fail(*args):
        raise OSError('setup fixture failed')
    monkeypatch.setattr(probe, 'NativeCapture', lambda *a, **k: pytest.fail('native device opened'))
    monkeypatch.setattr(probe, 'target_identity', fail if failure == 'identity' else lambda *a: object())
    if failure == 'thread_start':
        monkeypatch.setattr(probe.threading.Thread, 'start', fail)
    with pytest.raises(RuntimeError, match='setup fixture failed'):
        probe.run(args)
    assert json.loads((args.output / 'result.json').read_text())['error'] == 'setup fixture failed'
    assert not [w for w in app.topLevelWidgets() if w.isVisible() and w.windowTitle().startswith('Blackbox synthetic')]
