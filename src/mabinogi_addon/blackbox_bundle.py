"""Frozen product profile resolution; no PATH lookup, download or device access."""
import hashlib
import json
from pathlib import Path
import sys
import os
import shutil
import uuid


def load_product_profile(*, bundle=None, data=None, videos=None):
    if bundle is None:
        if not getattr(sys, 'frozen', False):
            return None
        bundle = Path(sys._MEIPASS) / 'blackbox'
    bundle = Path(bundle)
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    required = ('product.json', 'mabinogi_blackbox.dll', 'blackbox_codec_host.exe',
                'ffmpeg.exe', 'ffprobe.exe', 'redistribution.json', 'THIRD-PARTY-NOTICES.txt',
                'corresponding-source.zip', 'FFmpeg-LICENSE.txt', 'avcodec-62.dll',
                'avformat-62.dll', 'avutil-60.dll', 'avfilter-11.dll',
                'swscale-9.dll', 'swresample-6.dll')
    if any(name not in manifest for name in required):
        raise ValueError('블랙박스 번들 구성 파일이 누락됐어요.')
    for name, expected in manifest.items():
        if Path(name).name != name or name in ('.', '..'):
            raise ValueError('invalid bundle filename')
        with (bundle / name).open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected:
            raise ValueError('블랙박스 번들 파일 확인 실패: ' + name)
    profile = json.loads((bundle / 'product.json').read_text(encoding='utf-8'))
    if any(key in profile for key in ('library', 'temp_parent', 'output_folder')):
        raise ValueError('product policy must not contain machine-specific paths')
    codec = profile.get('codec', {})
    if any(key in codec for key in ('ffmpeg', 'ffprobe', 'host')):
        raise ValueError('product codec paths must come from verified bundle')
    if codec.get('encoder') not in ('h264_mf',):
        raise ValueError('제품용 하드웨어 인코더 선택이 필요해요.')
    producer = profile.get('producer', {})
    if producer.get('max_width') != 1920 or producer.get('max_height') != 1080:
        raise ValueError('블랙박스 출력은 1920×1080 고정이어야 해요.')
    if producer.get('max_input_width') != 3840 or producer.get('max_input_height') != 2160:
        raise ValueError('블랙박스 입력 게임창 상한은 3840×2160이어야 해요(큰 창은 GPU에서 축소).')
    if codec.get('fps') != 60:
        raise ValueError('제품 녹화 FPS는 확정된 60이어야 해요.')
    if profile.get('audio') != 'process':
        raise ValueError('제품 설정에서 무음 검증 모드를 사용할 수 없어요.')
    if data is None:
        from .paths import user_data_dir
        data = user_data_dir()
    data = Path(data)
    if videos is None:
        from .system.known_folders import videos_folder
        videos = videos_folder()
    temp, output = data / 'blackbox-temporary', Path(videos) / 'StarlineMabinogiAddon'
    for folder in (temp, output):
        folder.mkdir(parents=True, exist_ok=True)
    profile.update(temp_parent=str(temp.absolute()), output_folder=str(output.absolute()),
                   library=str((bundle / 'mabinogi_blackbox.dll').absolute()))
    profile['codec'] = dict(codec, ffmpeg=str((bundle / 'ffmpeg.exe').absolute()),
                            ffprobe=str((bundle / 'ffprobe.exe').absolute()),
                            host=str((bundle / 'blackbox_codec_host.exe').absolute()))
    from .blackbox_service import ServiceSettings
    ServiceSettings.from_dict(profile)  # missing policy fields fail before native/device access
    publish_notices(bundle, data, manifest)
    return profile


def publish_notices(bundle, data, manifest):
    """Provide bundled source/notices as ordinary files; no user developer tools needed."""
    folder = Path(data) / 'third_party' / ('ffmpeg-' + manifest['corresponding-source.zip'][:16])
    folder.mkdir(parents=True, exist_ok=True)
    for name in ('corresponding-source.zip', 'THIRD-PARTY-NOTICES.txt', 'FFmpeg-LICENSE.txt', 'redistribution.json'):
        target = folder / name
        if target.exists():
            with target.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != manifest[name]:
                    raise ValueError('기존 라이선스 자료가 변경됐어요: ' + name)
            continue
        temporary = folder / (uuid.uuid4().hex + '.partial')
        try:
            with (Path(bundle) / name).open('rb') as source, temporary.open('xb') as output:
                shutil.copyfileobj(source, output)
                output.flush(); os.fsync(output.fileno())
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return folder
