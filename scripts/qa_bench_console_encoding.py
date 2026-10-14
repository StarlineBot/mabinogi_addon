"""Reproduce CI-WIN-04 using the existing benchmark tests, without editing them."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CASES = (
    "tests/test_debuff_bench.py::test_detection_false_positive_benchmark",
    "tests/test_debuff_bench.py::test_boss_recognition_recall",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoding", choices=("cp1252", "utf-8"), default="cp1252")
    parser.add_argument("--junitxml", type=Path)
    args = parser.parse_args()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = args.encoding + ":strict"
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + previous if previous else "")
    command = [sys.executable, "-m", "pytest", "-q", "-rs", *CASES]
    if args.junitxml:
        command.append("--junitxml=" + str(args.junitxml.resolve()))
    print("Benchmark console encoding: " + args.encoding, flush=True)
    try:
        return subprocess.run(command, cwd=ROOT, env=env, timeout=120).returncode
    except subprocess.TimeoutExpired:
        print("Benchmark reproduction exceeded 120 seconds.", file=sys.stderr)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
