"""Every `run:` block in a GitHub workflow must be valid shell.

A workflow's shell is never parsed until the job executes on a runner, so a syntax error
ships green and only surfaces as a red run minutes later — with a message
("syntax error: unexpected end of file") that points at a generated temp file rather than
at the YAML. That is exactly how a `run:` block lost its closing `fi` on 2026-08-19: the
YAML was valid, the job started, and the step died at line 8 of
`/home/runner/work/_temp/<uuid>.sh`.

`bash -n` parses without executing, so this costs milliseconds and catches the whole class.
"""
import os
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKFLOW_DIR = os.path.join(_REPO, ".github", "workflows")


def _workflows():
    if not os.path.isdir(_WORKFLOW_DIR):
        return []
    return sorted(f for f in os.listdir(_WORKFLOW_DIR)
                  if f.endswith((".yml", ".yaml")))


def _run_blocks(path):
    """[(job, step_label, script)] for every shell `run:` in the workflow."""
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    blocks = []
    for job_name, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        default_shell = ((job.get("defaults") or {}).get("run") or {}).get("shell", "bash")
        for index, step in enumerate(job.get("steps") or []):
            if not isinstance(step, dict) or "run" not in step:
                continue
            shell = step.get("shell", default_shell)
            if shell not in ("bash", "sh", None):
                continue          # pwsh/python/etc. are out of scope for bash -n
            label = step.get("name") or step.get("id") or f"step[{index}]"
            blocks.append((job_name, label, step["run"]))
    return blocks


@pytest.mark.skipif(not shutil.which("bash"), reason="bash not available")
@pytest.mark.parametrize("workflow", _workflows())
def test_every_run_block_parses_as_shell(workflow):
    path = os.path.join(_WORKFLOW_DIR, workflow)
    blocks = _run_blocks(path)
    failures = []
    for job, label, script in blocks:
        # GitHub expands ${{ ... }} before the shell ever sees it; substitute a literal so
        # an expression in a string cannot be mistaken for a shell syntax error.
        probe = script.replace("${{", "${__GHA__").replace("}}", "}")
        result = subprocess.run(["bash", "-n"], input=probe, text=True,
                                capture_output=True, timeout=30)
        if result.returncode != 0:
            failures.append(f"{workflow} :: {job} :: {label}\n{result.stderr.strip()}")
    assert not failures, "invalid shell in workflow run blocks:\n\n" + "\n\n".join(failures)


def test_the_checker_actually_catches_a_missing_fi(tmp_path):
    """Guards the guard: a workflow with an unterminated if must fail this test."""
    broken = tmp_path / "workflows"
    broken.mkdir()
    (broken / "broken.yml").write_text(
        'jobs:\n'
        '  j:\n'
        '    steps:\n'
        '      - name: no fi\n'
        '        run: |\n'
        '          if [ -n "$X" ]; then\n'
        '            echo yes\n'
        '          else\n'
        '            echo no\n'
    )

    blocks = _run_blocks(str(broken / "broken.yml"))
    assert len(blocks) == 1
    result = subprocess.run(["bash", "-n"], input=blocks[0][2], text=True,
                            capture_output=True, timeout=30)
    assert result.returncode != 0
    assert "unexpected end of file" in result.stderr


def test_at_least_one_workflow_was_checked():
    """A silent zero-workflow scan would make this suite permanently, uselessly green."""
    assert _workflows(), f"no workflows found under {_WORKFLOW_DIR}"
