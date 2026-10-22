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
    valid = report(**{"Release feature checks": "success", "Windows startup smoke": "success",
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
    valid = report(**{"Release feature checks": "success", "Windows startup smoke": "success"})
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


def test_linux_qt_runtime_is_installed_and_checked_before_regression():
    steps = workflow("windows.yml")["jobs"]["regression"]["steps"]
    install = next(s for s in steps if s.get("name") == "Install Qt runtime libraries")
    assert "libpulse0" in install["run"].split()
    check = next(s for s in steps if s.get("name") == "Check Qt runtime imports")
    unit = next(s for s in steps if s.get("id") == "unit")
    assert steps.index(install) < steps.index(check) < steps.index(unit)
    assert check["timeout-minutes"] == "1"
    assert check["run"].startswith("uv run --frozen python -c ")
    for module in ("QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtMultimedia"):
        assert module in check["run"]
    for step in (install, check):
        assert "if" not in step and "continue-on-error" not in step


def test_validation_is_manual_feature_gate_with_mandatory_bounded_storage():
    main = workflow("windows.yml")
    assert set(main["on"]) == {"workflow_dispatch"}
    assert main["on"]["workflow_dispatch"]["inputs"]["version"]["required"] == "true"
    assert main["permissions"]["contents"] == "read"
    job = main["jobs"]["validate"]
    assert job["needs"] == ["request", "regression"]
    regression = main["jobs"]["regression"]
    assert regression["needs"] == "request"
    assert regression["runs-on"] == "ubuntu-24.04"
    assert job["runs-on"] == "windows-2022"
    request = main["jobs"]["request"]
    freeze = next(s for s in request["steps"] if s.get("name") == "Freeze release request")
    assert freeze["id"] == "freeze"
    assert request["outputs"]["version"] == "${{ steps.freeze.outputs.version }}"
    assert job["env"]["APP_VERSION"] == "${{ needs.request.outputs.version }}"
    assert "inputs.mode != 'publish-existing'" in job["if"]
    steps = job["steps"]
    names = [step.get("name") for step in steps]
    required = ("Fetch regression report", "Windows startup smoke", "Verify exe build",
                "Seal verified candidate", "Store verified candidate")
    assert [names.index(name) for name in required] == sorted(names.index(name) for name in required)
    for name in required:
        step = next(s for s in steps if s.get("name") == name)
        assert "if" not in step and "continue-on-error" not in step
    unit = next(s for s in regression["steps"] if s.get("id") == "unit")
    smoke = next(s for s in steps if s.get("id") == "smoke")
    assert 'scripts.run_release_checks --version "$APP_VERSION"' in unit["run"]
    assert "tests/test_startup_smoke.py" in smoke["run"]
    assert "-vv" in smoke["run"]
    assert "--regression-group" not in unit["run"] + smoke["run"]
    assert "-n " not in smoke["run"]
    import tomllib
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(dep.startswith("pytest-xdist") for dep in project["dependency-groups"]["dev"])
    assert regression["env"]["QT_QPA_PLATFORM"] == "offscreen"
    assert smoke["env"]["QT_QPA_PLATFORM"] == "windows"
    assert "Native Windows integration" not in names
    report_upload = next(s for s in regression["steps"] if s.get("name") == "Store regression report")
    report_download = next(s for s in steps if s.get("name") == "Fetch regression report")
    assert report_upload["with"]["name"] == report_download["with"]["name"]
    assert "github.run_id" in report_download["with"]["name"]
    assert "github.run_attempt" in report_download["with"]["name"]
    assert "run-id" not in report_download["with"]  # only this run, never an older success
    assert "if" not in report_upload and "continue-on-error" not in report_upload
    assert report_upload["with"]["retention-days"] == "1"
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
    assert names.index("Windows startup smoke") < names.index(clean["name"]) < names.index("Inject bundled secrets")
    text = json.dumps(main)
    assert "release_delivery" not in text and "RELEASES_TOKEN" not in text
    command = runpy.run_path(str(ROOT / "packaging/build_windows.py"))["build_command"]()
    assert "--uac-admin" not in command and "--collect-all" in command
    assert "dxcam" in command and "comtypes" in command


def test_completion_publication_uses_trusted_main_without_rebuild_or_retest():
    release = workflow("release.yml")
    assert set(release["on"]) == {"workflow_run"}
    event = release["on"]["workflow_run"]
    assert event == {"workflows": ["Windows validation"], "types": ["completed"], "branches": ["main"]}
    job = release["jobs"]["promote"]
    assert "conclusion == 'success'" in job["if"]
    assert "event == 'workflow_dispatch'" in job["if"]
    assert "head_repository.full_name == github.repository" in job["if"]
    assert "windows" not in job["runs-on"]
    assert release["concurrency"] == workflow("windows.yml")["concurrency"]
    steps = job["steps"]
    checkout = steps[0]
    assert checkout["uses"] == "actions/checkout@v4"
    assert "ref" not in checkout["with"]  # default-branch snapshot, never triggering code
    approval = steps[1]
    assert approval["id"] == "approval"
    assert approval["run"] == "python -m scripts.release_automation authorize"
    assert "RELEASES_TOKEN" not in json.dumps(approval)
    public = steps[2]
    assert public["with"]["repository"] == "StarlineBot/mabinogi_addon-releases"
    assert public["if"] == "steps.approval.outputs.publish == 'true'"
    publish = steps[-1]
    assert publish["if"] == public["if"]
    assert all("continue-on-error" not in s for s in steps)
    text = json.dumps(release)
    assert "pytest" not in text and "build_windows.py" not in text and "pyinstaller" not in text.lower()
    assert publish["run"] == "python -m scripts.release_automation complete"


def test_dispatch_defaults_to_verification_and_freezes_request_before_heavy_job():
    main = workflow("windows.yml")
    inputs = main["on"]["workflow_dispatch"]["inputs"]
    assert inputs["mode"]["default"] == "verify-only"
    assert inputs["mode"]["options"] == ["verify-only", "validate-and-publish", "publish-existing"]
    assert inputs["candidate_run"]["required"] == "false"
    request = main["jobs"]["request"]
    assert request["runs-on"] == "ubuntu-latest"
    assert request["if"] == "github.ref == 'refs/heads/main'"
    assert request["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    assert main["jobs"]["validate"]["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    store = request["steps"][-1]
    assert store["with"]["retention-days"] == "1"
    assert "github.run_attempt" in store["with"]["name"]
    assert all("continue-on-error" not in s for s in request["steps"])
    assert "workflow run" not in json.dumps(main) + json.dumps(workflow("release.yml"))


@pytest.mark.parametrize("backend", ["offscreen", "offscreen:custom-options"])
@pytest.mark.parametrize("root_key", ["WINDIR", "SystemRoot"])
def test_windows_offscreen_uses_system_fonts_before_application(tmp_path, backend, root_key):
    from test_support.qt_runtime import configure_offscreen_fonts
    fonts = tmp_path / "Windows" / "Fonts"
    fonts.mkdir(parents=True)
    env = {"QT_QPA_PLATFORM": backend, root_key: str(fonts.parent)}
    configure_offscreen_fonts(platform="win32", environ=env)
    assert env["QT_QPA_FONTDIR"] == str(fonts)


@pytest.mark.parametrize("platform,backend", [
    ("win32", "windows"), ("win32", ""), ("linux", "offscreen"), ("darwin", "offscreen")
])
def test_native_and_other_platform_font_setup_is_preserved(platform, backend):
    from test_support.qt_runtime import configure_offscreen_fonts
    env = {"QT_QPA_PLATFORM": backend}
    configure_offscreen_fonts(platform=platform, environ=env)
    assert env == {"QT_QPA_PLATFORM": backend}


def test_explicit_offscreen_font_directory_is_preserved():
    from test_support.qt_runtime import configure_offscreen_fonts
    env = {"QT_QPA_PLATFORM": "offscreen", "QT_QPA_FONTDIR": "custom-fonts"}
    configure_offscreen_fonts(platform="win32", environ=env)
    assert env["QT_QPA_FONTDIR"] == "custom-fonts"


@pytest.mark.parametrize("root", [None, "missing-windows-directory"])
def test_missing_windows_fonts_fail_with_actionable_error(root):
    from test_support.qt_runtime import configure_offscreen_fonts
    env = {"QT_QPA_PLATFORM": "offscreen"}
    if root:
        env["WINDIR"] = root
    with pytest.raises(RuntimeError, match="QT_QPA_FONTDIR"):
        configure_offscreen_fonts(platform="win32", environ=env)
    assert "QT_QPA_FONTDIR" not in env


def test_watchdog_bounds_keep_feature_gate_and_publish_only_safe_diagnostics():
    jobs=workflow('windows.yml')['jobs']
    for job_name, step_id, case, session, limit, collect_name, store_name in [
        ('validate','smoke','60','90','3','Collect startup diagnostics','Store startup diagnostics'),
    ]:
        job=jobs[job_name]
        steps=job['steps']
        step=next(s for s in steps if s.get('id')==step_id)
        assert 'scripts.run_regressions' in step['run'] and '--case-timeout '+case in step['run']
        assert '--session-timeout '+session in step['run'] and step['timeout-minutes']==limit
        collect=next(s for s in steps if s.get('name')==collect_name)
        store=next(s for s in steps if s.get('name')==store_name)
        assert collect['if']=='always()' and store['if']=='always()'
        assert store['with']['path']=='test-diagnostics/**/public/*'
        assert store['with']['retention-days']=='1'
        assert '.raw' not in store['with']['path'] and 'continue-on-error' not in store
    assert all(jobs[name]['timeout-minutes']=='15' for name in ('request','regression','validate'))
    feature=next(s for s in jobs['regression']['steps'] if s.get('id')=='unit')
    assert feature['timeout-minutes']=='14'
    assert 'scripts.run_release_checks' in feature['run']
    for name in ('Collect regression diagnostics', 'Store regression diagnostics'):
        assert next(s for s in jobs['regression']['steps'] if s.get('name')==name)['if']=='always()'
    assert workflow('release.yml')['jobs']['promote']['timeout-minutes']=='15'
    build=next(s for s in jobs['validate']['steps'] if s.get('id')=='build')
    assert build['timeout-minutes']=='13'


def test_optional_native_workflow_preserves_all_cases_without_publishing():
    native=workflow('windows-native.yml')
    assert set(native['on'])=={'workflow_dispatch'}
    assert native['permissions']=={'contents':'read'}
    job=native['jobs']['native']
    assert job['runs-on']=='windows-2022' and job['timeout-minutes']=='15'
    assert job['env']['QT_QPA_PLATFORM']=='windows'
    step=next(s for s in job['steps'] if s.get('name')=='Native Windows integration')
    assert '-m windows_integration' in step['run'] and '--regression-group' not in step['run']
    assert '--session-timeout 600' in step['run'] and step['timeout-minutes']=='12'
    assert 'continue-on-error' not in step and 'if' not in step
    assert 'release_automation' not in json.dumps(native) and 'RELEASES_TOKEN' not in json.dumps(native)


def test_publication_contract_matches_each_workflow_job_and_cannot_skip_stages():
    from scripts.release_candidate import REQUIRED_JOBS
    main=workflow('windows.yml')
    for job_name, required in REQUIRED_JOBS.items():
        job=main['jobs'][job_name]
        assert "inputs.mode != 'publish-existing'" in job['if']
        assert job['steps'][0]['with']['ref']=='${{ github.sha }}'
        assert 'continue-on-error' not in job
        steps={s.get('name'):s for s in job['steps'] if s.get('name')}
        for name in required:
            assert name in steps
            assert 'if' not in steps[name] and 'continue-on-error' not in steps[name]
    assert main['jobs']['regression']['needs']=='request'
    assert main['jobs']['validate']['needs']==['request','regression']
    assert workflow('release.yml')['on']['workflow_run']['workflows']==['Windows validation']


def test_regression_reports_first_errors_and_owns_read_only_resource_sampler():
    job=workflow('windows.yml')['jobs']['regression']
    step=next(s for s in job['steps'] if s.get('id')=='unit')
    command=step['run']
    assert 'scripts.run_release_checks' in command
    assert 'setsid .venv/bin/python -u -m scripts.ci_resources &' in command
    assert 'trap cleanup EXIT' in command and 'kill -TERM -- "-$sampler"' in command
    assert 'wait "$sampler"' in command and 'exit "$result"' in command
    assert command.index('scripts.ci_resources') < command.index('scripts.run_release_checks')
    assert 'continue-on-error' not in step


def test_full_regression_is_optional_development_work_not_a_release_prerequisite():
    development=workflow('regression.yml')
    assert set(development['on'])=={'workflow_dispatch'}
    assert development['permissions']=={'contents':'read'}
    steps=development['jobs']['regression']['steps']
    full=next(s for s in steps if s.get('name')=='Full development regression')
    assert 'scripts.run_regressions' in full['run'] and '-n 2' in full['run']
    assert "not windows_integration" in full['run']
    assert '--regression-group' not in full['run'] and 'run_release_checks' not in full['run']
    assert 'libpulse0' in next(s for s in steps if s.get('name')=='Install Qt runtime libraries')['run']
    assert 'release_automation' not in json.dumps(development)
    assert 'Development regression' not in json.dumps(workflow('release.yml')['on'])


def test_release_linux_installs_synthetic_codec_dependency():
    from pathlib import Path
    import yaml
    workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / '.github/workflows/windows.yml').read_text())
    installs = [step.get('run', '') for step in workflow['jobs']['regression']['steps']]
    assert any('apt-get install' in command and 'ffmpeg' in command.split() for command in installs)
