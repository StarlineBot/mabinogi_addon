"""0.17.1 FPS 표시 부하 재현: PresentMon 한 줄(게임 프레임 1개)마다 앱이 하는 일을 실제 코드로 분당 2만 줄 돌려 CPU 시간을 잰다.

실행: uv run python -m scripts.qa_0171_fps_line_cost
실사용 로그(2026-10-25): 'FPS 이벤트 도착 지연' 200FPS+ 분당 약 22,000개 → 초당 약 370줄이 UI 스레드로 들어온다.
줄마다 하는 일(optimization_controller._line): 제작자 확인(is_creator → config.json 읽기·JSON 해석), 시계 조회, FrameStream.feed
(csv 해석·dict), 수집기 _read의 줄 자르기(buffer.split 반복). Windows 호출(QPC)은 대신 time.perf_counter로 둔다.
- 각 단계 비용을 따로 재고, 분당 2만 줄 기준 CPU 점유율(코어 1개 기준)로 환산한다.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from mabinogi_addon import config  # noqa: E402
from mabinogi_addon.optimization.frame_summary import FrameSummary  # noqa: E402
from mabinogi_addon.optimization.frames import FrameStream  # noqa: E402

N = 22000
FREQ = 10_000_000
HEADER = ('Application,ProcessID,SwapChainAddress,Runtime,SyncInterval,PresentFlags,AllowsTearing,PresentMode,'
          'QPCTime,msInPresentAPI,msBetweenPresents')


def lines(start_qpc):
    out, qpc = [], start_qpc
    for _ in range(N):
        qpc += 45_000  # 4.5ms ≈ 222FPS
        out.append(f'Client.exe,1664,0x000000000ED0C3F8,DXGI,0,0,1,Hardware: Independent Flip,{qpc},0.051,4.500')
    return out


def timed(label, fn):
    t = time.process_time()
    fn()
    used = time.process_time() - t
    print(f'{label:<46} {used * 1000:7.0f}ms / 2만 줄 → 코어 1개 기준 {used / 60 * 100:5.2f}%')
    return used


if __name__ == '__main__':
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / 'config.json'
    # 실사용 설정과 비슷한 크기(탭별 설정·영역·알림 등). 실제 사용자 파일 크기는 다를 수 있다.
    data = {'discordUser': {'id': '280290004926857216', 'name': 'x'}}
    data.update({f'section{i}': {f'key{j}': [j, j * 2, 'value' * 3] for j in range(40)} for i in range(12)})
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'설정 파일 크기 {cfg.stat().st_size / 1024:.1f}KB · 2만 줄(≈1분, 222FPS) 기준')
    base = time.perf_counter()
    rows = lines(int(base * FREQ))
    total = 0.0
    total += timed('① 제작자 확인(config.json 읽기·해석) ×2만', lambda: [config.load_discord_user(cfg) for _ in range(N)])
    total += timed('② 시계 조회(perf_counter 대용) ×2만', lambda: [time.perf_counter() for _ in range(N)])

    def feed():
        stream = FrameStream(1664, FREQ, FrameSummary())
        now = base + 120
        stream.feed(HEADER, now)
        for r in rows:
            stream.feed(r, now)
    total += timed('③ FrameStream.feed(csv·검사·요약) ×2만', feed)

    blob = ('\n'.join(rows) + '\n').encode()
    chunk = len(blob) // 75  # 약 0.8초마다 묶여 도착(로그 도착 지연 ~800ms) → 1분에 약 75덩어리

    def split():
        buf = b''
        for i in range(0, len(blob), chunk):
            buf += blob[i:i + chunk]
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                line.decode('utf-8-sig').strip()
    total += timed(f'④ 수집기 줄 자르기(덩어리 {chunk // 1024}KB씩) ×2만', split)
    print(f'합계 {total * 1000:.0f}ms/분 → 코어 1개 기준 {total / 60 * 100:.2f}% (전체 코어 기준은 코어 수로 나눔)')
