#!/usr/bin/env python3
"""Every CI job must be bounded.

THE GAP
-------
`.github/workflows/ci.yml` had three jobs and no `timeout-minutes`, so all three
inherited GitHub's 360-minute default. Every other workflow in the repo already set
one (auto-sync 5, canary 2/5, chatgpt-patch 10, orch-agent 30) — ci.yml and
supabase-preview.yml were the exceptions.

Not theoretical: the runner test suite has been observed to HANG rather than fail —
three separate full local runs stalled instead of finishing. A hung CI job holds a
runner for six hours per push, and the release train waits behind it. A fuse is the
difference between a red build and a stuck fleet.

This test is the ratchet: a new workflow, or a new job in an existing one, fails here
until it is bounded.
"""
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS = os.path.join(REPO, ".github", "workflows")

yaml = pytest.importorskip("yaml", reason="pyyaml not installed")

# A job that legitimately runs long must be listed here deliberately rather than being
# silently unbounded. Empty on purpose: nothing currently qualifies.
LONG_RUNNING_ALLOWLIST = frozenset()

# Above this, a "timeout" stops being a fuse. GitHub's default is 360.
MAX_REASONABLE_MINUTES = 60


def workflow_files():
    if not os.path.isdir(WORKFLOWS):
        return []
    return sorted(f for f in os.listdir(WORKFLOWS)
                  if f.endswith((".yml", ".yaml")))


def jobs_in(filename):
    with open(os.path.join(WORKFLOWS, filename), encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return (data.get("jobs") or {}) if isinstance(data, dict) else {}


def all_jobs():
    for filename in workflow_files():
        for name, spec in jobs_in(filename).items():
            if isinstance(spec, dict):
                yield filename, name, spec


def test_there_are_workflows_to_check():
    """Guards against this whole file passing vacuously."""
    assert list(all_jobs()), "no workflow jobs found — the checks below prove nothing"


def test_every_job_declares_a_timeout():
    unbounded = [f"{f}:{name}" for f, name, spec in all_jobs()
                 if spec.get("timeout-minutes") is None
                 and f"{f}:{name}" not in LONG_RUNNING_ALLOWLIST]
    assert not unbounded, (
        "these CI jobs are unbounded and inherit GitHub's 360-minute default:\n  "
        + "\n  ".join(unbounded)
        + "\nAdd `timeout-minutes:` — a hung job holds a runner for six hours.")


def test_no_timeout_is_so_large_it_stops_being_a_fuse():
    excessive = [f"{f}:{name}={spec['timeout-minutes']}" for f, name, spec in all_jobs()
                 if isinstance(spec.get("timeout-minutes"), int)
                 and spec["timeout-minutes"] > MAX_REASONABLE_MINUTES]
    assert not excessive, excessive


def test_every_timeout_is_a_positive_integer():
    bad = [f"{f}:{name}={spec.get('timeout-minutes')!r}" for f, name, spec in all_jobs()
           if spec.get("timeout-minutes") is not None
           and not (isinstance(spec["timeout-minutes"], int)
                    and spec["timeout-minutes"] > 0)]
    assert not bad, bad


def test_the_main_ci_workflow_is_fully_bounded():
    """Named explicitly: ci.yml is the one that gates every push to master."""
    jobs = jobs_in("ci.yml")
    assert jobs, "ci.yml has no jobs"
    for name, spec in jobs.items():
        assert isinstance(spec.get("timeout-minutes"), int), f"ci.yml job {name}"


@pytest.mark.parametrize("filename", [f for f in (workflow_files() or ["ci.yml"])])
def test_each_workflow_file_parses(filename):
    """A workflow that does not parse does not run, and GitHub reports that quietly."""
    assert isinstance(jobs_in(filename), dict)
