"""합성 코덱 검사의 명시적 Windows host 경로. 자동 다운로드/skip 없음."""
import os
from pathlib import Path
import sys
import shutil


def codec_host(*, platform=None, environ=None):
    if (sys.platform if platform is None else platform) != 'win32':
        return None
    value = (os.environ if environ is None else environ).get('BLACKBOX_CODEC_HOST')
    if not value or not Path(value).is_absolute() or not Path(value).is_file():
        raise ValueError('BLACKBOX_CODEC_HOST must name the absolute built blackbox_codec_host.exe')
    return Path(value)


def codec_tools():
    """Require the synthetic-test executables; never skip or download silently."""
    names = ('ffmpeg', 'ffprobe')
    resolved = [shutil.which(name) for name in names]
    missing = [name for name, path in zip(names, resolved) if not path]
    if missing:
        raise RuntimeError(
            'Blackbox synthetic tests require ' + ', '.join(missing) +
            ' on PATH. On Ubuntu install the ffmpeg package; '
            'the test FFmpeg must include libx264 and AAC. This is not the product bundle.'
        )
    return tuple(Path(path) for path in resolved)
