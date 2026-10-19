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
                      "Verify exe build": "success", "Seal verified candidate": "success",
                      "Store verified candidate": "success"})
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


def test_storage_failure_is_visible_separate_and_blocks_deployment(tmp_path, monkeypatch, capsys):
    dest = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(dest))
    ci.summary("success", "success", "success", "failure")
    assert "Verified candidate storage" in dest.read_text(encoding="utf-8")
    assert "deployment is blocked" in capsys.readouterr().out


def workflow(name):
    import yaml
    return yaml.load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_validation_is_manual_full_gate_with_mandatory_bounded_storage():
    main = workflow("windows.yml")
    assert set(main["on"]) == {"workflow_dispatch"}
    assert main["on"]["workflow_dispatch"]["inputs"]["version"]["required"] == "true"
    assert main["permissions"]["contents"] == "read"
    job = main["jobs"]["validate"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    steps = job["steps"]
    names = [step.get("name") for step in steps]
    required = ("Isolated regression", "Native Windows integration", "Verify exe build",
                "Seal verified candidate", "Store verified candidate")
    assert [names.index(name) for name in required] == sorted(names.index(name) for name in required)
    for name in required:
        step = next(s for s in steps if s.get("name") == name)
        assert "if" not in step and "continue-on-error" not in step
    unit = next(s for s in steps if s.get("id") == "unit")
    native = next(s for s in steps if s.get("id") == "native")
    assert "not windows_integration" in unit["run"] and "-m windows_integration" in native["run"]
    assert "-vv" in unit["run"] and "-vv" in native["run"]
    assert "--regression-group" not in unit["run"] + native["run"]
    assert unit["env"]["QT_QPA_PLATFORM"] == "offscreen"
    assert native["env"]["QT_QPA_PLATFORM"] == "windows"
    build = next(s for s in steps if s.get("id") == "build")
    assert "packaging/build_windows.py" in build["run"] and "APP_VERSION" in build["run"]
    upload = next(s for s in steps if s.get("id") == "upload")
    assert upload["with"]["retention-days"] == "1"
    assert "github.run_id" in upload["with"]["name"] and "github.run_attempt" in upload["with"]["name"]
    assert names.index("Enforce candidate retention") < names.index("Store verified candidate")
    clean = next(s for s in steps if s.get("name") == "Verify clean checkout after tests")
    assert "git diff --quiet HEAD" in clean["run"] and "throw" in clean["run"]
    assert "git ls-files --others" in clean["run"]
    assert "if" not in clean and "continue-on-error" not in clean
    assert names.index("Native Windows integration") < names.index(clean["name"]) < names.index("Inject bundled secrets")
    text = json.dumps(main)
    assert "release_delivery" not in text and "RELEASES_TOKEN" not in text
    command = runpy.run_path(str(ROOT / "packaging/build_windows.py"))["build_command"]()
    assert "--uac-admin" in command and "--collect-all" in command
    assert "dxcam" in command and "comtypes" in command


def test_publication_is_manual_download_and_promotion_without_rebuild_or_retest():
    release = workflow("release.yml")
    assert set(release["on"]) == {"workflow_dispatch"}
    inputs = release["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"run_id", "attempt", "source_sha", "version"}
    assert all(value["required"] == "true" for value in inputs.values())
    job = release["jobs"]["promote"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert "windows" not in job["runs-on"]
    assert release["concurrency"] == workflow("windows.yml")["concurrency"]
    steps = job["steps"]
    download = next(s for s in steps if s.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"]["run-id"] == "${{ inputs.run_id }}"
    assert download["with"]["name"] == "${{ steps.gate.outputs.artifact_name }}"
    publish = next(s for s in steps if s.get("name") == "Publish exact verified files")
    assert steps.index(next(s for s in steps if s.get("id") == "gate")) < steps.index(download) < steps.index(publish)
    assert steps.index(next(s for s in steps if s.get("name") == "Verify candidate bytes and lifetime")) < steps.index(publish)
    assert all("continue-on-error" not in s for s in steps)
    text = json.dumps(release)
    assert "pytest" not in text and "build_windows.py" not in text and "pyinstaller" not in text.lower()
    assert "scripts.release_delivery" in publish["run"]
