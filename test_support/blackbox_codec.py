"""합성 코덱 검사의 명시적 Windows host 경로. 자동 다운로드/skip 없음."""
import os
from pathlib import Path
import sys


def codec_host(*, platform=None, environ=None):
    if (sys.platform if platform is None else platform) != 'win32':
        return None
    value = (os.environ if environ is None else environ).get('BLACKBOX_CODEC_HOST')
    if not value or not Path(value).is_absolute() or not Path(value).is_file():
        raise ValueError('BLACKBOX_CODEC_HOST must name the absolute built blackbox_codec_host.exe')
    return Path(value)
