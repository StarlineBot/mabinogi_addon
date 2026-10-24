"""FPS 명세 10.4 D안: 게임 CPU = 마비노기에서 가장 바쁜 스레드 사용률(코어 1개 = 100%). 버퍼 해석·계산은 OS 없이."""
import struct

from mabinogi_addon.system.process_threads import GameCpu, PROCESS_SIZE, THREAD_SIZE, busiest_percent, parse


def process_entry(pid, threads, base_priority=8, last=False):
    """SYSTEM_PROCESS_INFORMATION(x64) + 스레드 배열을 합성한다. threads: [(스레드 ID, 커널, 사용자)]."""
    size = PROCESS_SIZE + THREAD_SIZE * len(threads)
    data = bytearray(size)
    struct.pack_into('<II', data, 0, 0 if last else size, len(threads))
    struct.pack_into('<i', data, 72, base_priority)
    struct.pack_into('<Q', data, 80, pid)
    for index, (tid, kernel, user) in enumerate(threads):
        at = PROCESS_SIZE + index * THREAD_SIZE
        struct.pack_into('<qq', data, at, kernel, user)
        struct.pack_into('<Q', data, at + 48, tid)
    return bytes(data)


def buffer(game_threads, other_threads=((1, 0, 0),)):
    return process_entry(4, list(other_threads)) + process_entry(123, list(game_threads), base_priority=13, last=True)


def test_parse_finds_game_threads_and_base_priority_only_for_that_pid():
    times, base = parse(buffer([(10, 100, 50), (11, 5, 5)]), 123)
    assert times == {10: 150, 11: 10} and base == 13
    assert parse(buffer([(10, 0, 0)]), 999) == (None, None)


def test_busiest_thread_percent_uses_one_core_as_100_and_ignores_other_processes():
    # 1초 동안 메인 스레드 0.9초, 다른 스레드 0.2초 → 90%(코어 하나 기준). 다른 프로세스 부하는 섞이지 않는다.
    before = {10: 0, 11: 0}
    after = {10: 9_000_000, 11: 2_000_000, 12: 50_000_000}  # 12는 새 스레드(비교 제외)
    assert busiest_percent(before, after, 1.0) == 90.0
    assert busiest_percent(before, {10: 30_000_000}, 1.0) == 100.0  # 상한
    assert busiest_percent({}, after, 1.0) is None


def test_game_cpu_needs_two_samples_and_resets_on_new_pid():
    samples = iter([buffer([(10, 0, 0)]), buffer([(10, 4_000_000, 1_000_000)]), buffer([(10, 0, 0)])])
    clock = iter([0.0, 1.0, 2.0])
    reader = GameCpu(source=lambda: next(samples), clock=lambda: next(clock))
    assert reader.read(123) is None          # 첫 표본: —
    assert reader.read(123) == 50.0          # 0.5초/1초
    assert reader.read(None) is None         # 게임 없음: 초기화
