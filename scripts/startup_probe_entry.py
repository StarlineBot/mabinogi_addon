"""Frozen proof entry: the bootloader window must survive Python/update states unchanged."""

import time

entered = time.time_ns() // 1_000_000

import json
import os
from pathlib import Path
import pyi_splash

print("splash-alive", pyi_splash.is_alive(), flush=True)
pyi_splash.update_text("@probe:app")
# Observation windows belong only to this proof executable, not application startup.
pyi_splash.update_text("@status:업데이트 확인 중")
time.sleep(0.4)
pyi_splash.update_text("@probe:check")
pyi_splash.update_text("@status:새 버전 v0.8.0 받는 중 37%")
time.sleep(0.4)
pyi_splash.update_text("@probe:check")
pyi_splash.update_text("@resume")
time.sleep(3.5)
pyi_splash.update_text("@probe:flush")
report = Path(os.environ["MABINOGI_SPLASH_PROBE_REPORT"])
deadline = time.monotonic() + 3
while not report.exists() and time.monotonic() < deadline:
    time.sleep(0.02)
pyi_splash.close()
Path(str(report) + ".entry.json").write_text(
    json.dumps(dict(entered=entered)), encoding="utf-8"
)
