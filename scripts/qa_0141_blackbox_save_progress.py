"""0.14.1 블랙박스 저장 진행 표시 재현: 실제 ffmpeg로 저장(encode→validate)하며 progress_snapshot을 읽는다.

실행: uv run python -m scripts.qa_0141_blackbox_save_progress
- 정상 저장: -progress 파일로 인코딩 퍼센트가 올라가고, 끝나면 progress가 None이어야 한다.
- 저장 취소·인코딩 실패: validate까지 가지 않으면 progress가 남는지 본다. 남으면 다음 저장이 시작되기 전까지
  탭이 '저장 중 · 경과 …'로 보이고, 컨트롤러 _save_started도 남아 다음 저장 완료의 '걸림' 시간이 부풀 수 있다.
남으면 REPRODUCED(Potential, 표시 문제), 종료 코드 1.
"""
import io
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from mabinogi_addon.blackbox_codec import CodecSettings, FFmpegEncoder  # noqa: E402
from mabinogi_addon.blackbox_export import ByteSink  # noqa: E402

W, H, FPS = 640, 360, 60


def settings():
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    return CodecSettings(Path(ffmpeg), Path(ffprobe), 'libx264', 2_000_000, FPS, 120, 50_000)


def segment(codec, folder, index, frames):
    path = folder / f'{index}.mp4'
    rng = [bytes([(index * 37 + n * 5) % 256]) * (W * H * 4) for n in range(frames)]
    with path.open('wb') as out:
        codec.encode_frames(rng, W, H, ByteSink(out, 1 << 30))
    return path


def plan(paths, frames):
    dur = frames * 1_000_000 // FPS
    slices = [SimpleNamespace(segment=SimpleNamespace(source=p, format_key='h264'), offset_us=0, duration_us=dur)
              for p in paths]
    return SimpleNamespace(slices=slices, duration_us=dur * len(paths))


def save(codec, p, out, cancel=None):
    seen = []
    done = threading.Event()

    def watch():
        while not done.is_set():
            seen.append(codec.progress_snapshot())
            time.sleep(0.05)
    t = threading.Thread(target=watch)
    t.start()
    error = None
    try:
        with out.open('wb') as stream:
            codec.encode(p, ByteSink(stream, 1 << 31, cancel))
        codec.validate(out, p)
    except Exception as exc:  # noqa: BLE001
        error = exc
    done.set()
    t.join()
    return seen, error


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        codec = FFmpegEncoder(settings(), lambda key: key)
        frames = 60
        paths = [segment(codec, folder, i, frames) for i in range(20)]  # 20초 분량
        p = plan(paths, frames)

        seen, error = save(codec, p, folder / 'ok.mp4')
        fractions = [s[3] for s in seen if s and s[0] == 'encode' and s[3] is not None]
        stages = sorted({s[0] for s in seen if s})
        print(f'[정상 저장] 오류: {error or "없음"} · 단계 {stages} · 퍼센트 표본 {len(fractions)}개 '
              f'(최대 {max(fractions, default=0):.0%}) · 끝난 뒤 progress={codec.progress}')
        normal_ok = error is None and fractions and codec.progress is None

        from threading import Event
        cancel = Event()
        threading.Timer(0.3, cancel.set).start()
        _, error = save(codec, p, folder / 'cancel.mp4', cancel)
        left_cancel = codec.progress
        print(f'[저장 취소] 오류: {type(error).__name__ if error else "없음"} · 끝난 뒤 progress='
              f'{None if left_cancel is None else left_cancel["stage"]}'
              + (f' · 2초 뒤 snapshot={codec.progress_snapshot()[2]:.1f}초 경과' if left_cancel else ''))
        if left_cancel:
            time.sleep(2)
            print(f'  2초 뒤 snapshot: {codec.progress_snapshot()}')
        codec.progress = None

        broken = plan([folder / 'missing.mp4'], frames)
        _, error = save(codec, broken, folder / 'fail.mp4')
        left_fail = codec.progress
        print(f'[인코딩 실패] 오류: {type(error).__name__ if error else "없음"} · 끝난 뒤 progress='
              f'{None if left_fail is None else left_fail["stage"]}')

        print('정상 저장 진행 표시:', '정상' if normal_ok else '실패')
        stale = left_cancel is not None or left_fail is not None
        print('REPRODUCED: 취소·실패한 저장의 진행 상태가 남음(다음 저장 전까지 "저장 중" 표시·다음 완료 "걸림" 시간 부풀 수 있음)'
              if stale else '취소·실패 뒤 진행 상태: 정리됨')
        sys.exit(1 if stale or not normal_ok else 0)
