"""명시적으로 실행한 자기 합성창만 WGC로 캡처하는 Windows 기술 검사.

게임/사용자 창 식별자를 받지 않는다. 오디오 API를 열지 않는다.
검사 수치는 작은 고정 fixture이며 제품 기본값이 아니다.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

from mabinogi_addon.blackbox import SavePlan, Segment, Slice
from mabinogi_addon.blackbox_codec import CodecSettings, FFmpegEncoder
from mabinogi_addon.blackbox_export import ExportJob
from mabinogi_addon.system.blackbox_capture import NativeCapture, target_identity


FRAME_LIMIT = 4 * 1024 * 1024
FRAME_COUNT = 12
FPS = 10


def collect_frames(native, target, stop, *, timeout=10):
    """닫힘/포커스 상실은 실패. 다른 대상으로 다시 연결하지 않는다."""
    frames, stamps, colours = [], [], set()
    dimensions = None
    deadline, next_frame = time.monotonic() + timeout, 0
    try:
        native.open(target)
        while len(frames) < FRAME_COUNT:
            if stop.is_set():
                raise RuntimeError('synthetic window closed before capture completed')
            if time.monotonic() >= deadline:
                raise TimeoutError('synthetic capture deadline exceeded')
            item = native.read()
            if item is None:
                stop.wait(.002)
                continue
            data, width, height, stamp = item
            if (width < 2 or height < 2 or len(data) != width * height * 4
                    or len(data) > FRAME_LIMIT):
                raise ValueError('synthetic frame bounds invalid')
            if dimensions is not None and dimensions != (width, height):
                raise ValueError('synthetic window resized')
            dimensions = width, height
            if stamps and stamp <= stamps[-1]:
                raise ValueError('capture timestamp did not advance')
            if stamp < next_frame:
                continue
            offset = ((height // 2) * width + width // 2) * 4
            b, g, r = data[offset:offset + 3]
            if g > 25 or not ((r > 220 and b < 25) or (b > 220 and r < 25)):
                raise ValueError('unexpected pixels in owned synthetic window')
            colours.add('red' if r > b else 'blue')
            frames.append(data); stamps.append(stamp)
            next_frame = stamp + 1_000_000 // FPS
        if colours != {'red', 'blue'}:
            raise ValueError('synthetic pattern did not change')
        return frames, dimensions, stamps
    finally:
        native.close()


def save_frames(frames, dimensions, output, settings):
    duration = round(len(frames) * 1_000_000 / FPS)
    width, height = dimensions
    segment = Segment('owned-synthetic-window', 'memory', 0, duration,
                      sum(map(len, frames)), f'{width}x{height}:{FPS}:video')
    plan = SavePlan(duration, (Slice(segment, 0, duration),))
    codec = FFmpegEncoder(settings, lambda source: None)
    result = ExportJob(plan, output, max_output_bytes=8 * 1024 * 1024).run(
        lambda plan, sink: codec.encode_frames(frames, width, height, sink), codec.validate)
    if not result.completed:
        raise RuntimeError(f'{result.error}; preserved partial={result.partial}')
    return result


def run(args):
    if not args.run_owned_window_capture:
        raise ValueError('explicit --run-owned-window-capture required')
    if sys.platform != 'win32' or os.environ.get('QT_QPA_PLATFORM', '').lower() in ('offscreen', 'minimal'):
        raise OSError('interactive Windows desktop required; no alternate capture path')
    if not args.library.is_file() or not args.host.is_file():
        raise ValueError('built native DLL and codec host required')
    settings = CodecSettings(args.ffmpeg, args.ffprobe, getattr(args, 'encoder', 'h264_mf'), 500000, FPS, 15, 50000, host=args.host)
    args.output.mkdir(parents=True, exist_ok=False)
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    stop, done = threading.Event(), threading.Event()
    result = {}

    class Pattern(QWidget):
        red = True
        def paintEvent(self, event):
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor('red' if self.red else 'blue'))
            painter.end()
        def advance(self):
            self.red = not self.red
            self.update()
        def closeEvent(self, event):
            stop.set()
            event.accept()

    def work():
        try:
            native = NativeCapture(args.library, max_frame_bytes=FRAME_LIMIT, cursor=False)
            frames, dimensions, stamps = collect_frames(native, target, stop)
            exported = save_frames(frames, dimensions, args.output / 'synthetic.mp4', settings)
            result.update(scope='owned synthetic window only; no audio; not game/performance validation',
                          frames=len(frames), dimensions=dimensions, timestamps_us=stamps,
                          output=str(exported.output), cadence='10fps sampled test output; not source timing certification')
        except Exception as exc:
            result['error'] = str(exc)
        finally:
            done.set()

    window = timer = worker = None
    try:
        window = Pattern()
        window.setWindowTitle('Blackbox synthetic capture — this window only, no audio')
        window.setFixedSize(320, 240)
        window.show(); window.raise_(); window.activateWindow()
        app.processEvents()
        # 호출자가 전달한 HWND/PID는 없다. 이 코드가 만든 창/현재 프로세스만 사용.
        target = target_identity(int(window.winId()), os.getpid())
        timer = QTimer(window)
        timer.setInterval(150); timer.timeout.connect(window.advance); timer.start()
        worker = threading.Thread(target=work, name='blackbox-owned-window-probe')
        worker.start()
        while not done.wait(.005):
            app.processEvents()
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        stop.set()
        if worker is not None and worker.ident is not None:
            worker.join()
        if timer is not None:
            timer.stop()
        if window is not None:
            window.close(); window.deleteLater()
        app.processEvents()
    (args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if 'error' in result:
        raise RuntimeError(result['error'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-owned-window-capture', action='store_true')
    parser.add_argument('--encoder', default='h264_mf', choices=('h264_mf', 'libx264'),
                        help='Product hardware MF, or explicitly chosen external synthetic test codec')
    for key in ('library', 'host', 'ffmpeg', 'ffprobe', 'output'):
        parser.add_argument('--' + key, required=True, type=lambda value: Path(value).absolute())
    print(json.dumps(run(parser.parse_args()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
