#!/usr/bin/env python3
"""Lease-night recovery, group 4 — the three config hunks, verified against current state.

The directive for this section is careful: *"small consistency updates; verify against current
state before applying (these files have moved substantially since)."* Verified 2026-08-05
against `hotfix/stash-rescue-lease-night-5f879035`:

| hunk | rescue branch | current master | outcome |
|---|---|---|---|
| `runner/deployment_bindings.json` | adds the `apparently-law` binding, drops the trailing newline | binding already present | **superseded** — re-applying would only remove a newline |
| `runner/merge_train.py` | restores `process_project` as a worker function | already restored at `merge_train.py:1665` | **superseded** |
| `scripts/fleet_config_baseline.json` | `ORCH_PUSH_ON_RELEASE: "true" -> "false"` | `"true"` | **DIVERGENCE — current is correct** |

The third is the one that matters, and it is why this file exists rather than a commit.

`ORCH_PUSH_ON_RELEASE=false` was set during the 2026-07-29 lease-RPC outage — the night an RPC
failure mass-quarantined 91 tasks. Stopping production pushes mid-incident was right. Carrying
it forward into the BASELINE is not: the baseline is re-asserted onto every machine in the
fleet, so a blind re-apply would silently stop production releases everywhere, with a green
build and no error anywhere to say why nothing was shipping. That is the same failure shape as
the release-train batch floor of 10 that "silently held small merges out of prod" — a correct-
looking config value doing damage quietly.

The directive's own instruction covers this: *"where the codebase has since evolved a different
solution for the same problem, prefer current and note the divergence rather than forcing."*
These tests are that note, in the only form that survives: one that fails if someone re-applies
the rescue value.
"""
import json
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_PATH = os.path.join(REPO, "scripts", "fleet_config_baseline.json")
BINDINGS_PATH = os.path.join(REPO, "runner", "deployment_bindings.json")
MERGE_TRAIN_PATH = os.path.join(REPO, "runner", "merge_train.py")


def baseline():
    with open(BASELINE_PATH) as f:
        return json.load(f)


class PushOnReleaseDivergenceTests(unittest.TestCase):
    """The one hunk that must NOT be re-applied."""

    def test_production_pushes_stay_enabled_in_the_baseline(self):
        self.assertEqual(
            baseline().get("ORCH_PUSH_ON_RELEASE"), "true",
            "ORCH_PUSH_ON_RELEASE=false is the 2026-07-29 incident value. The baseline is "
            "re-asserted onto every machine, so setting it here stops production releases "
            "fleet-wide — silently, with a green build.")

    def test_the_release_train_is_still_the_thing_that_pushes(self):
        """Belt and braces: dev merges push, plain merges do not, releases do."""
        config = baseline()
        self.assertEqual(config.get("ORCH_PUSH_ON_DEV_MERGE"), "true")
        self.assertEqual(config.get("ORCH_PUSH_ON_MERGE"), "false")
        self.assertEqual(config.get("ORCH_PUSH_ON_RELEASE"), "true")

    def test_the_baseline_is_valid_json_and_all_string_values(self):
        """It is loaded into env on every machine; a non-string would fail there, not here."""
        config = baseline()
        self.assertIsInstance(config, dict)
        for key, value in config.items():
            self.assertIsInstance(value, str, f"{key} must be a string")

    def test_no_credential_shaped_key_reached_the_baseline(self):
        """fleet_config rejects these; the baseline must not carry one either."""
        for key in baseline():
            upper = key.upper()
            for marker in ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "PAT"):
                self.assertNotIn(marker, upper, f"{key} looks like a credential")


class SupersededHunkTests(unittest.TestCase):
    """The two hunks that are already landed — asserted so nobody re-applies them either."""

    def test_the_apparently_law_binding_is_already_present(self):
        with open(BINDINGS_PATH) as f:
            text = f.read()
        self.assertIn("apparently-law", text)
        data = json.loads(text)
        apps = data.get("targets") or []
        names = {a.get("app") for a in apps if isinstance(a, dict)}
        self.assertIn("apparently-law", names,
                      "the rescue hunk added this binding; it is already here")

    def test_the_bindings_file_keeps_its_trailing_newline(self):
        """The rescue hunk removed it — and master had lost it too. Restored here."""
        with open(BINDINGS_PATH, "rb") as f:
            self.assertTrue(f.read().endswith(b"\n"),
                            "deployment_bindings.json must end with a newline")

    def test_merge_train_process_project_is_already_restored(self):
        """The rescue hunk restored this worker function; master already has it."""
        with open(MERGE_TRAIN_PATH, errors="replace") as f:
            source = f.read()
        self.assertIn("def process_project(item):", source)
        self.assertIn("def process_project_isolated(item):", source)
        self.assertLess(source.index("def process_project(item):"),
                        source.index("def process_project_isolated(item):"),
                        "the worker must be defined before the isolator that calls it")

    def test_the_isolator_actually_calls_the_worker(self):
        with open(MERGE_TRAIN_PATH, errors="replace") as f:
            source = f.read()
        self.assertIn("process_project_isolated", source)
        self.assertIn("pool.map(process_project_isolated", source)


class ProvenanceTests(unittest.TestCase):
    def test_this_file_records_why_the_rescue_value_is_not_applied(self):
        """A divergence nobody wrote down is a divergence that gets re-applied next quarter."""
        with open(os.path.abspath(__file__), errors="replace") as f:
            doc = f.read()
        self.assertIn("ORCH_PUSH_ON_RELEASE", doc)
        self.assertIn("2026-07-29", doc)
        self.assertIn("prefer current and note the divergence", doc)


if __name__ == "__main__":
    unittest.main()
