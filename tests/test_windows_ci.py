import json
from pathlib import Path
import runpy
from subprocess import CompletedProcess

import pytest

from scripts import windows_ci as ci

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


@pytest.mark.parametrize("path", ["src/mabinogi_addon/ui/main_window.py", "src/mabinogi_addon/ui/notifier.py",
                                 "packaging/build_windows.py", "uv.lock", "pyproject.toml",
                                 ".github/workflows/release.yml", "test_support/boundaries.py",
                                 "scripts/windows_ci.py", "tests/test_tracker_layout.py",
                                 "scripts/qa_tracker_horizontal_extent.py", "pytest.ini"])
def test_risky_changes_require_exe(path):
    assert ci.needs_build([path])


def test_build_advice_is_conservative_but_does_not_schedule_workflows():
    assert ci.needs_build(["tests/test_setup.py"])
    assert not ci.needs_build(["docs/windows-validation.md"])
    assert ci.changed_paths("0" * 40, SHA) is None


def report(**steps):
    return {"headSha": SHA, "conclusion": "success",
            "jobs": [{"steps": [{"name": name, "conclusion": status} for name, status in steps.items()]}]}


def test_only_exact_sha_and_actual_required_steps_are_accepted():
    valid = report(**{"Isolated regression": "success", "Native Windows integration": "success",
                      "Verify exe build": "success"})
    assert ci.verify_report(valid, SHA, True) == 0
    with pytest.raises(RuntimeError, match="SHA"):
        ci.verify_report(valid, "b" * 40)
    valid["jobs"][0]["steps"][1]["conclusion"] = "skipped"
    with pytest.raises(RuntimeError, match="did not pass"):
        ci.verify_report(valid, SHA)
    valid["conclusion"] = "failure"
    assert ci.verify_report(valid, SHA) == 1
    valid["conclusion"] = "cancelled"
    assert ci.verify_report(valid, SHA) == 1


def test_old_success_run_never_matches_new_push():
    assert ci.find_run([{"headSha": "b" * 40, "databaseId": 999, "conclusion": "success"}], SHA) is None
    assert ci.find_run([{"headSha": SHA, "databaseId": 1}, {"headSha": SHA, "databaseId": 2}], SHA)["databaseId"] == 2


def test_wait_reads_details_and_reports_api_failure(monkeypatch):
    run = {"headSha": SHA, "databaseId": 12, "status": "completed", "conclusion": "success", "url": "test"}
    valid = report(**{"Isolated regression": "success", "Native Windows integration": "success"})
    replies = iter([CompletedProcess([], 0, json.dumps([run]), ""), CompletedProcess([], 0, json.dumps(valid), "")])
    monkeypatch.setattr(ci.subprocess, "run", lambda *a, **k: next(replies))
    assert ci.wait(SHA, "owner/repo", timeout=1) == 0
    monkeypatch.setattr(ci.subprocess, "run", lambda *a, **k: CompletedProcess([], 1, "", "Forbidden"))
    with pytest.raises(RuntimeError, match="Forbidden"):
        ci.wait(SHA, "owner/repo", timeout=1)


def test_optional_upload_failure_is_visible_and_separate(tmp_path, monkeypatch, capsys):
    dest = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(dest))
    ci.summary("success", "success", "success", "failure")
    assert "Optional artifact upload" in dest.read_text(encoding="utf-8")
    assert "::warning::" in capsys.readouterr().out


def test_release_and_validation_use_same_build_command():
    import yaml

    def workflow(name):
        return yaml.load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    main = workflow("windows.yml")
    release = workflow("release.yml")
    assert set(main["on"]) == {"workflow_dispatch"}
    inputs = main["on"]["workflow_dispatch"]["inputs"]
    assert inputs["build_exe"]["type"] == "boolean"
    assert inputs["build_exe"]["default"] == "false"
    assert inputs["upload_exe"]["default"] == "false"
    assert release["on"]["push"] == {"tags": ["v*"]}
    main_steps = main["jobs"]["validate"]["steps"]
    release_steps = release["jobs"]["build-windows"]["steps"]
    assert "continue-on-error" not in release["jobs"]["build-windows"]
    for steps in (main_steps, release_steps):
        builds = [step for step in steps if step.get("id") == "build"]
        assert len(builds) == 1 and "packaging/build_windows.py" in builds[0]["run"]
        unit = next(step for step in steps if step.get("id") == "unit")
        native = next(step for step in steps if step.get("id") == "native")
        assert "not windows_integration" in unit["run"]
        assert "-m windows_integration" in native["run"]
        assert "-vv" in unit["run"] and "-vv" in native["run"]
        assert unit["env"]["QT_QPA_PLATFORM"] == "offscreen"
        assert native["env"]["QT_QPA_PLATFORM"] == "windows"
        assert "continue-on-error" not in unit and "continue-on-error" not in native
        assert "if" not in unit and "if" not in native
        assert "continue-on-error" not in builds[0]
        upload = next(step for step in steps if step.get("id") == "upload")
        assert upload["continue-on-error"] == "true"
        assert upload["with"]["retention-days"] == "1"
    manual_build = next(s for s in main_steps if s.get("id") == "build")
    assert manual_build["if"] == "inputs.build_exe || inputs.upload_exe"
    assert not any(s.get("id") == "plan" for s in main_steps)
    release_build = next(s for s in release_steps if s.get("id") == "build")
    assert "if" not in release_build
    stage_ids = [s.get("id") for s in release_steps]
    assert stage_ids.index("unit") < stage_ids.index("native") < stage_ids.index("build")
    command = runpy.run_path(str(ROOT / "packaging/build_windows.py"))["build_command"]()
    assert "--uac-admin" in command and "--collect-all" in command
    assert "dxcam" in command and "comtypes" in command


def test_every_release_publication_requires_all_three_successes():
    import yaml

    release = yaml.load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = release["jobs"]["build-windows"]["steps"]
    publications = {
        "Attach to Release",
        "Commit to public repo main (version.json + CHANGELOG + README)",
        "Publish exe + version.json to public repo (Release)",
        "Announce release to Discord forum (webhook)",
    }
    gate = ("success() && startsWith(github.ref, 'refs/tags/') && "
            "steps.unit.outcome == 'success' && steps.native.outcome == 'success' && steps.build.outcome == 'success'")
    found = set()
    build_index = next(i for i, step in enumerate(steps) if step.get("id") == "build")
    for index, step in enumerate(steps):
        if step.get("name") in publications:
            found.add(step["name"])
            assert index > build_index
            assert step["if"] in (gate, gate + " && env.RELEASE_WEBHOOK_URL != ''")
            assert "continue-on-error" not in step
    assert found == publications


@pytest.mark.parametrize("existing", [None, b"author custom data\n", b"malformed but preserve"])
def test_public_dialogue_seed_never_replaces_author_file(tmp_path, existing):
    import shutil
    import subprocess
    import sys
    import yaml

    release = yaml.load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    step = next(s for s in release["jobs"]["build-windows"]["steps"]
                if s.get("name") == "Commit to public repo main (version.json + CHANGELOG + README)")
    script = step["run"]
    seed = script[script.index("mkdir -p data"):script.index("git config user.name")]
    source = tmp_path / "src/mabinogi_addon/assets/dialogues.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"bundled initial data\n")
    public = tmp_path / "pub"
    (public / "data").mkdir(parents=True)
    target = public / "data/dialogues.json"
    if existing is not None:
        target.write_bytes(existing)
    bash = "bash"
    if sys.platform == "win32":
        bash = str(Path(shutil.which("git")).parents[1] / "bin/bash.exe")
    subprocess.run([bash, "-e", "-c", seed], cwd=public, check=True)
    assert target.read_bytes() == (existing if existing is not None else source.read_bytes())
    assert "git add version.json README.md CHANGELOG.md data/dialogues.json" in script
