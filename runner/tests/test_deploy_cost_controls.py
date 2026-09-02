import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cowork_assemble


ROOT = Path(__file__).resolve().parents[2]


def test_web_only_auto_deploys_production_branch():
    """Only master builds. Branch deploys stay off; that is the cost control here.

    This test also used to require an `ignoreCommand` that skipped the build when
    web/ was untouched:

        "bash -c 'git diff --quiet ${VERCEL_GIT_PREVIOUS_SHA:-HEAD^} HEAD -- . ../packages/darwin-kernel'"

    That exact string was never in web/vercel.json. What was there was the naive
    form, `git diff --quiet HEAD^ HEAD -- .`, and a human removed it on
    2026-07-22 in 68746f3b, "remove ignoreCommand that canceled all master prod
    builds" — because on a squash or merge commit HEAD^..HEAD frequently touches
    nothing under web/, so the check cancelled the production build for changes
    that genuinely needed one. (96767f3f had restored it once before that; the
    removal is the later and deliberate act.)

    So the assertion is inverted rather than deleted: the key must stay ABSENT,
    and a future reintroduction has to be a deliberate change to this test with
    the VERCEL_GIT_PREVIOUS_SHA form that survives a squash — not a quiet
    re-add of the form that took production builds down.
    """
    config = json.loads((ROOT / "web" / "vercel.json").read_text())
    assert config["git"]["deploymentEnabled"] == {"*": False, "master": True}
    assert "ignoreCommand" not in config, (
        "ignoreCommand was removed in 68746f3b because HEAD^..HEAD cancelled "
        "master production builds on squash/merge commits. Reintroducing it "
        "needs the ${VERCEL_GIT_PREVIOUS_SHA:-HEAD^} form and an update here."
    )


def test_release_defaults_batch_builds():
    config = json.loads((ROOT / "scripts" / "fleet_config_baseline.json").read_text())
    assert config["ORCH_PUSH_ON_MERGE"] == "false"
    assert int(config["RELEASE_MIN_BATCH"]) >= 10
    assert float(config["RELEASE_INTERVAL_HOURS"]) >= 6


def test_release_code_enforces_cost_control_floors():
    """The floors that are actually in force, rather than the ones from 2026-07.

    This asserted `MIN_BATCH = max(10,` in both files. Neither is true any more,
    and both changes were deliberate:

      * 04b55df6 (2026-08-02) lowered release_train's hard floor to
        `max(1, ...)` to "allow MIN_BATCH floor of 1 for recovery flushes (env
        RELEASE_MIN_BATCH)". The DEFAULT is still 10 — the floor only binds when
        an operator sets the variable — so the cost control is the default plus
        the need for an explicit opt-in, not the floor.
      * autopilot does not pin 10 either. It temporarily sets 1/0 behind
        AUTOPILOT_RELEASE_BLOCKER_FLUSH and restores both the environment and
        the module globals in a `finally`.

    So what is worth pinning is the restore. An override that escaped its
    `finally` would leave the fleet at batch=1 and interval=0 permanently — a
    Vercel production build per merge — and nothing else in the system would
    notice. That, and the fact that lowering the batch takes a named env var.
    """
    release = (ROOT / "runner" / "release_train.py").read_text()
    autopilot = (ROOT / "runner" / "autopilot.py").read_text()

    # Defaults, and the interval floor which was never relaxed.
    assert 'os.environ.get("ORCH_RELEASE_BATCH_MIN", "10")' in release
    assert "RELEASE_INTERVAL_HOURS = max(6.0," in release
    assert 'os.environ.get("ORCH_RELEASE_INTERVAL_HOURS", "6")' in release

    # The batch floor can only be lowered by naming it.
    assert 'os.environ.get("RELEASE_MIN_BATCH"' in release

    # autopilot's flush is opt-in and is restored.
    assert 'os.environ.get(\n            "AUTOPILOT_RELEASE_BLOCKER_FLUSH", "false"' in autopilot
    assert "release_train.MIN_BATCH = max(1, int(os.environ.get(" in autopilot
    assert "release_train.RELEASE_INTERVAL_HOURS = max(6.0, float(os.environ.get(" in autopilot

    flush_block = autopilot.split('old_min_batch = os.environ.get("RELEASE_MIN_BATCH")', 1)[1]
    flush_block = flush_block.split("def ", 1)[0]
    assert "finally:" in flush_block, (
        "the release-flush override must be restored in a finally — an escaped "
        "override leaves the fleet at batch=1 permanently"
    )
    assert flush_block.index("finally:") < flush_block.index(
        "release_train.MIN_BATCH = max(1, int(os.environ.get("), (
        "the recomputation of MIN_BATCH must live inside the finally block"
    )


def test_cowork_executor_cannot_launch_vercel_builds():
    skill = (ROOT / "runner" / "cowork_executor" / "SKILL.md").read_text()
    forbidden = "npx " + "vercel@latest deploy"
    assert forbidden not in skill
    assert "RELEASE QUEUE ONLY" in skill


def test_cloud_runner_cannot_push_every_merge_to_production():
    service = (ROOT / "deploy" / "runner.service").read_text()
    assert "Environment=ORCH_PUSH_ON_MERGE=false" in service
    assert "Environment=RELEASE_MIN_BATCH=10" in service
    assert "Environment=RELEASE_INTERVAL_HOURS=6" in service


def test_cowork_agents_never_receive_vercel_token():
    with patch.dict(os.environ, {"VERCEL_TOKEN": "account-secret"}), \
            patch.object(cowork_assemble, "_safe_import", return_value=None):
        config = cowork_assemble.get_vercel_config()
    assert config["token"] == ""
