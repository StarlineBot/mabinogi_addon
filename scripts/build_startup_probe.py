"""Manual, standalone onefile proof; does not build/publish the app or use secrets."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def build_and_run(output, files=80000):
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        payload = temp / "payload"
        payload.mkdir()
        # Lots of files exercise an actual long extraction, without pausing app startup.
        for index in range(files):
            (payload / f"{index:05d}.bin").write_bytes(bytes(512))
        spec = temp / "startup-probe.spec"
        spec.write_text(
            f"""import sys
sys.path.insert(0, {str(ROOT)!r})
sys.path.insert(0, {str(ROOT / "src")!r})
from scripts.startup_splash import splash_type
from mabinogi_addon.startup_content import MESSAGES
ProbeSplash = splash_type(Splash, messages=MESSAGES, probe=True)
a = Analysis([{str(ROOT / "scripts/startup_probe_entry.py")!r}], datas=[({str(payload)!r}, 'payload')], hiddenimports=['pyi_splash'])
p = PYZ(a.pure)
s = ProbeSplash({str(ROOT / "src/mabinogi_addon/assets/startup_background.png")!r}, binaries=a.binaries, datas=a.datas, minify_script=False, always_on_top=True)
e = EXE(p, a.scripts, s, s.binaries, a.binaries, a.datas, [], name='startup-probe', console=True)
""",
            encoding="utf-8",
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(temp / "dist"),
                "--workpath",
                str(temp / "build"),
                str(spec),
            ],
            check=True,
            cwd=ROOT,
        )
        exe = (
            temp
            / "dist"
            / ("startup-probe.exe" if sys.platform == "win32" else "startup-probe")
        )
        report = output / "events.tsv"
        for stale in output.glob("events.tsv*"):
            stale.unlink()
        started = time.time()
        subprocess.run(
            [str(exe)],
            env={**os.environ, "MABINOGI_SPLASH_PROBE_REPORT": str(report)},
            check=True,
            timeout=90,
        )
        events = []
        for row in report.read_text(encoding="utf-8").splitlines():
            stamp, stage, window, geometry, text = row.split("\t", 4)
            events.append(
                dict(
                    stamp=int(stamp),
                    stage=stage,
                    window=window,
                    geometry=geometry,
                    text=text,
                )
            )
        entry = json.loads(
            Path(str(report) + ".entry.json").read_text(encoding="utf-8")
        )["entered"]
        before = [
            e
            for e in events
            if e["stage"] == "unpack" and e["text"] and e["stamp"] <= entry
        ]
        if not before:
            raise AssertionError("no visible typing observed before Python entry")
        pre = [e for e in events if e["stage"] == "unpack" and e["stamp"] <= entry]
        if not any(
            not e["text"] and any(later["text"] for later in pre[index + 1 :])
            for index, e in enumerate(pre)
            if index > 0
        ):
            raise AssertionError(
                "no complete dialogue/hold/replacement during real extraction; increase --files"
            )
        if (
            len({e["window"] for e in events}) != 1
            or len({e["geometry"] for e in events}) != 1
        ):
            raise AssertionError("loading window identity or geometry changed")
        statuses = [e["text"] for e in events if e["stage"] == "checkpoint"]
        if statuses != ["업데이트 확인 중", "새 버전 v0.8.0 받는 중 37%"]:
            raise AssertionError("important statuses were missing or overwritten")
        scale = int(re.match(r"(\d+)x", events[-1]["geometry"])[1]) / 440
        bounds = (
            Path(str(report) + ".bounds.tsv").read_text(encoding="utf-8").splitlines()
        )
        if not bounds:
            raise AssertionError("complete dialogue bounds were not measured")
        for row in bounds:
            message, *box = row.split("\t")
            left, top, right, bottom = map(int, box)
            if not (
                left >= 24 * scale - 1
                and top >= 198 * scale - 1
                and right <= 416 * scale + 1
                and bottom <= 232 * scale + 1
            ):
                raise AssertionError("dialogue exceeds its fixed slot: " + message)
        result = dict(
            platform=sys.platform,
            source_sha=os.environ.get("GITHUB_SHA", "local-working-tree"),
            payload_files=files,
            pyinstaller=__import__("PyInstaller").__version__,
            duration=time.time() - started,
            pre_python_frames=len(before),
            unique_windows=1,
            pre_python_replacement=True,
            measured_dialogues=len(bounds),
            geometry=events[-1]["geometry"],
            events=len(events),
        )
        (output / "result.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("startup-probe-results"))
    parser.add_argument("--files", type=int, default=80000)
    args = parser.parse_args()
    build_and_run(args.output.resolve(), args.files)
