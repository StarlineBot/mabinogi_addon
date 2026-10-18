"""Evaluate the workflows' boolean gates without starting Actions or publishing."""

import itertools
import json
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[4]


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def evaluate(cases):
    # These expressions use the JS-compatible Boolean/string subset of Actions.
    program = """const fs = require('fs');
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
const compiled = new Map();
const result = cases.map(({expression, context}) => {
  if (!compiled.has(expression)) compiled.set(expression, new Function('ctx',
    'const {github, steps, env, inputs} = ctx; ' +
    'const success = () => ctx.ok; const startsWith = (a,b) => a.startsWith(b); ' +
    'return Boolean(' + expression + ');'));
  return compiled.get(expression)(context);
});
process.stdout.write(JSON.stringify(result));
"""
    result = subprocess.run(["node", "-e", program], input=json.dumps(cases), text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


def context(outcomes=("success",) * 3, ok=True, tag=True, webhook=True):
    return {"ok": ok, "github": {"ref": "refs/tags/v0.4.85" if tag else "refs/heads/main",
                               "event_name": "workflow_dispatch"},
            "steps": {key: {"outcome": value} for key, value in zip(("unit", "native", "build"), outcomes)},
            "env": {"RELEASE_WEBHOOK_URL": "test" if webhook else ""}, "inputs": {}}


def publications():
    steps = workflow("release.yml")["jobs"]["build-windows"]["steps"]
    names = {"Attach to Release", "Commit to public repo main (version.json + CHANGELOG + README)",
             "Publish exe + version.json to public repo (Release)",
             "Announce release to Discord forum (webhook)"}
    selected = [step for step in steps if step.get("name") in names]
    assert {step["name"] for step in selected} == names
    return selected


def test_only_explicit_manual_or_tag_events_schedule_windows():
    manual, release = workflow("windows.yml"), workflow("release.yml")
    assert set(manual["on"]) == {"workflow_dispatch"}
    assert set(release["on"]) == {"workflow_dispatch", "push"}
    assert release["on"]["push"] == {"tags": ["v*"]}
    assert {path.name for path in (ROOT / ".github/workflows").glob("*.yml")} == {"windows.yml", "release.yml"}
    for name in ("build_exe", "upload_exe"):
        setting = manual["on"]["workflow_dispatch"]["inputs"][name]
        assert setting["type"] == "boolean" and setting["default"] == "false"


def test_manual_build_and_upload_truth_table():
    steps = workflow("windows.yml")["jobs"]["validate"]["steps"]
    build = next(step for step in steps if step.get("id") == "build")
    upload = next(step for step in steps if step.get("id") == "upload")
    cases, expected = [], []
    for ok, build_flag, upload_flag in itertools.product((False, True), repeat=3):
        ctx = context(ok=ok, tag=False)
        ctx["inputs"] = {"build_exe": build_flag, "upload_exe": upload_flag}
        will_build = ok and (build_flag or upload_flag)
        ctx["steps"]["build"]["outcome"] = "success" if will_build else "skipped"
        # Actions adds success() to conditions without an explicit status function.
        cases.extend([{"expression": "success() && (" + build["if"] + ")", "context": ctx},
                      {"expression": "success() && (" + upload["if"] + ")", "context": ctx}])
        expected.extend([will_build, will_build and upload_flag])
    assert evaluate(cases) == expected


def test_release_publication_failure_skip_cancel_matrix():
    cases, expected = [], []
    statuses = ("success", "failure", "skipped", "cancelled", "")
    for step in publications():
        discord = step["name"].startswith("Announce")
        for outcomes in itertools.product(statuses, repeat=3):
            for ok, tag, hook in itertools.product((False, True), repeat=3):
                cases.append({"expression": step["if"], "context": context(outcomes, ok, tag, hook)})
                expected.append(ok and tag and all(s == "success" for s in outcomes)
                                and (hook if discord else True))
    assert len(cases) == 4000
    assert evaluate(cases) == expected


def test_gate_matrix_detects_removed_required_checks():
    cases = []
    for step in publications():
        expression = step["if"]
        for index, key in enumerate(("unit", "native", "build")):
            outcomes = ["success"] * 3
            outcomes[index] = "failure"
            mutated = expression.replace(f"steps.{key}.outcome == 'success'", "true")
            assert mutated != expression
            cases.append({"expression": mutated, "context": context(outcomes)})
        cases.append({"expression": expression.replace("success()", "true"), "context": context(ok=False)})
        cases.append({"expression": expression.replace("startsWith(github.ref, 'refs/tags/')", "true"),
                      "context": context(tag=False)})
    assert len(cases) == 20 and all(evaluate(cases))


def test_required_steps_cannot_be_conditionally_skipped_or_soft_failed():
    for name, job in (("windows.yml", "validate"), ("release.yml", "build-windows")):
        definition = workflow(name)["jobs"][job]
        assert definition.get("continue-on-error", "false") == "false"
        by_id = {step["id"]: step for step in definition["steps"] if "id" in step}
        for key in ("unit", "native", "build"):
            assert by_id[key].get("continue-on-error", "false") == "false"
            if key != "build" or name == "release.yml":
                assert "if" not in by_id[key]


def test_bash_steps_have_valid_shell_syntax_without_execution():
    count = 0
    for step in workflow("release.yml")["jobs"]["build-windows"]["steps"]:
        if step.get("shell") == "bash":
            result = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
            assert result.returncode == 0, (step["name"], result.stderr)
            count += 1
    assert count >= 5
