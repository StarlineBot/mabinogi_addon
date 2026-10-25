"""CI 배포 검사 SIGSEGV(종료 코드 245, 실행 #127·#132) 원인 재현: faulthandler.dump_traceback_later(반복) + 스레드 생성·종료가 겹치면 파이썬이 SIGSEGV로 죽는다.

실행: .venv/bin/python scripts/qa_ci_faulthandler_segv.py 15   (종료 코드 139 = SIGSEGV면 재현)
test_support/progress.py는 pytest 주 프로세스(xdist controller)에도 30초 반복 덤프를 걸고 다시 걸지 않는다 → 시작 약 30초 뒤 첫 덤프.
두 실패 모두 "bringing up nodes" 뒤 약 30.5초에 주 프로세스가 죽었다(#127 21:49:56.3→21:50:26.8, #132 06:26:57.4→06:27:27.9).
"""
import faulthandler, threading, time, tempfile, sys
f=tempfile.TemporaryFile()
faulthandler.dump_traceback_later(0.001, repeat=True, file=f)
end=time.time()+float(sys.argv[1])
n=0
while time.time()<end:
    ts=[threading.Thread(target=lambda: sum(range(200))) for _ in range(20)]
    for t in ts: t.start()
    for t in ts: t.join()
    n+=20
print('ok threads', n)
