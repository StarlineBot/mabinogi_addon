"""Windows 검증 계획, 단계별 결과 요약, 정확한 푸시 SHA의 Actions 결과 확인."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time


WORKFLOW = "windows.yml"
BUILD_PATHS = ("src/", "packaging/", ".github/workflows/", "test_support/", "tests/", "scripts/")


def needs_build(paths):
    # 수동 사전 검증의 보수적인 빌드 권고다. 푸시 자동 실행 조건은 아니다.
    return any(path.startswith(BUILD_PATHS) or path in ("pyproject.toml", "uv.lock", "pytest.ini")
               for path in paths)


def changed_paths(base, head):
    if not base or set(base) == {"0"}:
        return None
    raw = subprocess.run(["git", "diff", "--name-only", "-z", base, head],
                         capture_output=True, check=True).stdout
    return [os.fsdecode(path) for path in raw.split(b"\0") if path]


def append(path, text):
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(text + "\n")


def plan(base, head):
    paths = changed_paths(base, head)
    build = paths is None or needs_build(paths)
    append(os.environ.get("GITHUB_OUTPUT"), f"build_required={str(build).lower()}")
    append(os.environ.get("GITHUB_STEP_SUMMARY"),
           f"## Windows Verification\nSource: `{head}`\n\nExe build required: **{build}**")
    return build


def summary(unit, smoke, build, upload):
    rows = {"Linux isolated regression": unit, "Windows startup smoke": smoke,
            "Exe build": build, "Verified candidate storage (deployment gate)": upload}
    output = "\n| Stage | Result |\n| --- | --- |\n"
    output += "\n".join(f"| {name} | {state} |" for name, state in rows.items())
    append(os.environ.get("GITHUB_STEP_SUMMARY"), output)
    print(output)
    if upload == "failure":
        print("::warning::Candidate storage failed; deployment is blocked. See upload logs for quota/transport errors. "
              "Test and exe build results are listed separately.")


def find_run(runs, sha):
    matches = [run for run in runs if run.get("headSha") == sha]
    return max(matches, key=lambda run: run["databaseId"]) if matches else None


def verify_report(report, sha, require_build=False):
    if report.get("headSha") != sha:
        raise RuntimeError("Run SHA does not match the pushed source")
    if report.get("conclusion") != "success":
        return 1
    steps = {step["name"]: step.get("conclusion")
             for job in report.get("jobs", []) for step in job.get("steps", [])}
    required = ["Isolated regression", "Windows startup smoke"]
    if require_build:
        required.extend(("Verify exe build", "Seal verified candidate", "Store verified candidate"))
    if any(steps.get(name) != "success" for name in required):
        raise RuntimeError("Required Windows verification step did not pass: " + json.dumps(steps))
    return 0


def wait(sha, repo, timeout=1800, interval=15, require_build=False):
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise ValueError("Use the complete pushed commit SHA")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = subprocess.run(["gh", "run", "list", "--repo", repo, "--workflow", WORKFLOW,
                               "--commit", sha, "--limit", "50", "--json",
                               "databaseId,headSha,status,conclusion,url"], capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError("Cannot read GitHub Actions: " + proc.stderr.strip())
        run = find_run(json.loads(proc.stdout), sha)
        if run:
            print(json.dumps(run, ensure_ascii=False), flush=True)
            if run["status"] == "completed":
                details = subprocess.run(["gh", "run", "view", str(run["databaseId"]), "--repo", repo,
                                          "--json", "headSha,status,conclusion,jobs,url"],
                                         capture_output=True, text=True, check=True)
                report = json.loads(details.stdout)
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return verify_report(report, sha, require_build)
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    raise TimeoutError(f"Windows verification did not finish for {sha}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    planning = sub.add_parser("plan")
    planning.add_argument("--base", default="")
    planning.add_argument("--head", required=True)
    reporting = sub.add_parser("summary")
    for name in ("unit", "smoke", "build", "upload"):
        reporting.add_argument("--" + name, required=True)
    waiting = sub.add_parser("wait")
    waiting.add_argument("--sha", required=True)
    waiting.add_argument("--repo", default="StarlineBot/mabinogi_addon")
    waiting.add_argument("--timeout", type=int, default=1800)
    waiting.add_argument("--require-build", action="store_true")
    args = parser.parse_args()
    if args.command == "plan":
        plan(args.base, args.head)
    elif args.command == "summary":
        summary(args.unit, args.smoke, args.build, args.upload)
    else:
        return wait(args.sha, args.repo, args.timeout, require_build=args.require_build)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
