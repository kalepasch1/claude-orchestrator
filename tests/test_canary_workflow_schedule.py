#!/usr/bin/env python3
"""The Gemini canary's SCHEDULE, pinned as a contract.

`.github/workflows/canary.yml` is the only thing that actually runs the canary on a
timer, and every property that makes it useful is a decision recorded in a YAML comment
rather than in a check:

  * it must run often enough to be a liveness signal, and rarely enough not to be the
    largest line item on the Actions bill (the file records the move from */5 — 288
    runs/day — to */30);
  * a MISSING SECRET must SKIP, not fail. The comment is emphatic about why: when the
    absent key failed the run, 100 of the last 100 runs were red for a reason that never
    changed, and "a genuine Gemini outage would have been indistinguishable from the
    missing secret, which is exactly the failure this canary exists to catch";
  * probe failure and marker failure must stay distinguishable — credential/transport
    versus the model returning something unexpected;
  * every job must be time-boxed, or a hung probe burns the runner's maximum.

A comment cannot fail. These tests can, so the next edit to the cadence or the gating has
to be deliberate. Everything here is offline — the workflow file is parsed, never run.
"""
from __future__ import annotations

import os
import re
import unittest

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "canary.yml")

#: Model ids the v1beta generateContent endpoint actually serves. A family name such as
#: `gemini-2.5` carries no variant suffix and 404s, which in the canary log is
#: indistinguishable from an outage — the one thing this workflow must never produce.
MODEL_ID_RE = re.compile(r"^gemini-\d+(?:\.\d+)?-(?:flash|pro)(?:-[a-z0-9.-]+)?$", re.I)

#: Floor on the cadence. Below this the canary costs more than the signal is worth; the
#: file's own history is the argument.
MIN_INTERVAL_MINUTES = 15


def load():
    with open(WORKFLOW, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


class WorkflowExistsTest(unittest.TestCase):
    def test_the_workflow_file_is_present_and_parses(self):
        self.assertTrue(os.path.isfile(WORKFLOW))
        self.assertIsInstance(load(), dict)

    def test_it_is_named(self):
        self.assertTrue(str(load().get("name") or "").strip())


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.workflow = load()
        # PyYAML parses a bare `on:` key as the boolean True — YAML 1.1's "on" literal.
        # A test that looked up the string key would silently find nothing and assert
        # nothing, which is how a workflow test comes to pass while checking no triggers.
        self.triggers = self.workflow.get("on", self.workflow.get(True))

    def test_the_canary_is_actually_scheduled(self):
        self.assertIsNotNone(self.triggers, "no trigger block — nothing runs this")
        self.assertIn("schedule", self.triggers,
                      "a canary with no schedule is not a canary")

    def test_it_can_also_be_run_by_hand(self):
        """Needed to confirm a fix without waiting for the next tick."""
        self.assertIn("workflow_dispatch", self.triggers)

    def test_the_cron_expression_is_well_formed(self):
        for entry in self.triggers["schedule"]:
            fields = entry["cron"].split()
            self.assertEqual(len(fields), 5, entry["cron"])

    def test_the_cadence_is_not_more_frequent_than_the_cost_floor(self):
        for entry in self.triggers["schedule"]:
            minute_field = entry["cron"].split()[0]
            match = re.fullmatch(r"\*/(\d+)", minute_field)
            if not match:
                continue
            interval = int(match.group(1))
            self.assertGreaterEqual(
                interval, MIN_INTERVAL_MINUTES,
                f"*/{interval} is {24 * 60 // interval} runs/day; the file records "
                f"moving off */5 for exactly this reason")

    def test_runs_do_not_stack_on_a_backed_up_schedule(self):
        concurrency = load().get("concurrency")
        self.assertIsInstance(concurrency, dict)
        self.assertTrue(concurrency.get("group"))
        self.assertIs(concurrency.get("cancel-in-progress"), False,
                      "cancelling the in-flight run would discard the signal being taken")


class NotConfiguredIsNotBrokenTest(unittest.TestCase):
    """The decision the file argues for at greatest length."""

    def setUp(self):
        self.jobs = load()["jobs"]

    def test_a_preflight_job_decides_whether_the_lane_is_configured(self):
        self.assertIn("preflight", self.jobs)
        self.assertIn("configured", self.jobs["preflight"].get("outputs", {}))

    def test_the_canary_job_is_gated_on_that_output(self):
        gate = str(self.jobs["gemini-canary"].get("if") or "")
        self.assertIn("preflight.outputs.configured", gate)
        self.assertIn("true", gate)

    def test_the_gate_runs_before_anything_is_provisioned(self):
        """The point of the separate job: no checkout, no pip install, on a skip."""
        preflight_steps = self.jobs["preflight"]["steps"]
        self.assertTrue(all("uses" not in step for step in preflight_steps),
                        "the preflight job must not check out or set up anything")

    def test_a_missing_secret_warns_rather_than_failing(self):
        body = " ".join(str(step.get("run") or "") for step in self.jobs["preflight"]["steps"])
        self.assertIn("::warning", body)
        self.assertNotIn("exit 1", body,
                         "a configuration gap must skip the canary, not redden it forever")


class FailureModesStaySeparableTest(unittest.TestCase):
    def setUp(self):
        self.steps = load()["jobs"]["gemini-canary"]["steps"]
        self.named = {str(s.get("name") or ""): s for s in self.steps}

    def test_the_probe_and_the_validation_are_separate_steps(self):
        """One step doing both makes 'key died' and 'model drifted' the same red X."""
        self.assertTrue(any("Probe" in name for name in self.named))
        self.assertTrue(any("Validate" in name for name in self.named))

    def test_the_probe_runs_the_probe_module(self):
        probe = next(s for name, s in self.named.items() if "Probe" in name)
        self.assertIn("gemini_canary_probe.py", probe["run"])

    def test_the_validation_runs_the_verdict_module_on_the_probe_output(self):
        validate = next(s for name, s in self.named.items() if "Validate" in name)
        self.assertIn("canary.py", validate["run"])
        self.assertIn("steps.probe.outputs.response", validate["run"],
                      "validating anything other than what the probe returned is theatre")

    def test_the_probe_step_fails_loudly(self):
        probe = next(s for name, s in self.named.items() if "Probe" in name)
        self.assertIn("set -euo pipefail", probe["run"],
                      "without pipefail a failed probe inside $(...) is swallowed")


class ConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.workflow = load()

    def test_the_model_is_a_served_id_not_a_family_name(self):
        model = self.workflow["jobs"]["gemini-canary"]["env"]["GEMINI_MODEL"]
        self.assertRegex(model, MODEL_ID_RE,
                         f"{model!r} has no variant suffix; the endpoint 404s on family "
                         f"names and a 404 reads like an outage in the canary log")

    def test_the_key_comes_from_secrets_and_is_never_inline(self):
        raw = open(WORKFLOW, encoding="utf-8").read()
        self.assertIn("secrets.GEMINI_API_KEY", raw)
        self.assertNotRegex(raw, r"GEMINI_API_KEY:\s*['\"]?AIza",
                            "a literal key in a workflow file is a leaked credential")

    def test_every_job_is_time_boxed(self):
        for name, job in self.workflow["jobs"].items():
            with self.subTest(job=name):
                self.assertIn("timeout-minutes", job,
                              "an untimed job burns the runner maximum when the probe hangs")
                self.assertLessEqual(job["timeout-minutes"], 15)

    def test_the_workflow_asks_for_no_more_permission_than_it_needs(self):
        self.assertEqual(self.workflow.get("permissions"), {"contents": "read"})


if __name__ == "__main__":
    unittest.main()
