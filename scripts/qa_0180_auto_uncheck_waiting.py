"""0.18.0 자동 적용 QA 재현: 게임 없는 대기 중 '자동 적용' 체크를 끄면(engine.auto=False) 그 뒤 켠 게임에 여전히 적용되는지.
실행: uv run python -m scripts.qa_0180_auto_uncheck_waiting  (적용됨 True면 재현)
"""
import sys, tempfile, time
from pathlib import Path
sys.path[:0]=['/home/user/mabinogi_addon/src','/home/user/mabinogi_addon/tests']
from test_optimization_auto import GameBackend, AUTO, key
from test_optimization import TARGET, _wait
from mabinogi_addon.optimization.engine import Engine
from mabinogi_addon.optimization.session import Recovery
from mabinogi_addon.system.process_priority import HIGH
b=GameBackend(); b.current[0]=None
r=Recovery(Path(tempfile.mkdtemp())/'j.json', b, lambda: True)
e=Engine(b,r,lambda: True); e.start(AUTO); time.sleep(1.5)
e.auto=False   # 사용자가 게임 없는 대기 중 '자동 적용' 체크를 끔(_auto_changed)
time.sleep(1.0); b.current[0]=TARGET   # 그 뒤 게임 실행
applied=_wait(lambda: b.values[key(TARGET)]==HIGH, 4)
print('체크를 끈 뒤 켠 게임에 우선순위 적용됨:', applied, '· 세션 진행 중:', e.busy)
e.stop(); e.thread.join(5)
