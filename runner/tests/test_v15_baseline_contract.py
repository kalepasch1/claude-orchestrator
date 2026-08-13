"""Machine-checked V15 baseline contract (docs/v15-00-baseline-contract-audit-slice-1.md).

An audit written only as prose drifts silently. These tests pin the enumerated surface —
app ids, feature flags, public API, telemetry keys, and the two defects the audit records
— so that any change to the landed runtime either updates the contract or fails here.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TS = os.path.join(_REPO, "packages", "darwin-kernel", "src", "hivemindV15", "index.ts")
_PY = os.path.join(_REPO, "runner", "hivemind_v15.py")
_DOC = os.path.join(_REPO, "docs", "v15-00-baseline-contract-audit-slice-1.md")

AUDITED_APPS = (
    "galop", "tomorrow", "smarter", "pareto", "apparently",
    "orchestrator", "vigil", "hisanta", "predictions", "trojun",
)
AUDITED_FLAGS = {"ORCH_V15_MEMORY_CAPACITY", "ORCH_V15_SPIKE_THRESHOLD"}


class AppIdentityContractTest(unittest.TestCase):
    def test_python_fleet_apps_match_the_audit(self):
        self.assertEqual(tuple(hivemind_v15.FLEET_APPS), AUDITED_APPS)

    def test_typescript_app_list_is_in_lockstep_with_python(self):
        """The two lists are hand-synced literals; e2834ef5 had to edit both."""
        with open(_TS, encoding="utf-8") as fh:
            src = fh.read()
        block = re.search(r"HIVEMIND_APPS\s*=\s*\[(.*?)\]", src, re.S)
        self.assertIsNotNone(block, "HIVEMIND_APPS literal not found")
        ts_apps = tuple(re.findall(r"'([a-z]+)'", block.group(1)))
        self.assertEqual(ts_apps, tuple(hivemind_v15.FLEET_APPS))

    def test_unknown_app_falls_back_to_orchestrator_rather_than_raising(self):
        self.assertEqual(hivemind_v15.canonical_app("not-a-real-app"), "orchestrator")
        for app in AUDITED_APPS:
            self.assertEqual(hivemind_v15.canonical_app(app), app)


class FeatureFlagContractTest(unittest.TestCase):
    def test_exactly_the_audited_flags_are_read(self):
        with open(_PY, encoding="utf-8") as fh:
            src = fh.read()
        found = set(re.findall(r"os\.getenv\(\s*[\"']([A-Z0-9_]+)[\"']", src))
        self.assertEqual(found, AUDITED_FLAGS)


class PublicApiContractTest(unittest.TestCase):
    EXPECTED = (
        "FractalEncoder", "MemoryHit", "HolographicMemory", "ZeroCopyFederation",
        "MetabolicState", "SpikeBudget", "AdaptiveErrorCorrection", "FractalCausalGraph",
        "AdversarialAnomalyCurriculum", "DistilledNode", "QueryCluster", "QueryTopology",
        "SpeculativeChains", "FleetAdapter", "HivemindV15",
    )

    def test_every_audited_class_is_still_exported(self):
        for name in self.EXPECTED:
            self.assertTrue(hasattr(hivemind_v15, name), f"missing class {name}")

    def test_module_level_entry_points_are_still_exported(self):
        for name in ("canonical_app", "pattern_key", "value_key", "runtime", "observe_task"):
            self.assertTrue(callable(getattr(hivemind_v15, name, None)), f"missing {name}")

    def test_facade_exposes_the_documented_subsystems(self):
        rt = hivemind_v15.HivemindV15()
        for attr in ("memory", "federation", "budget", "ecc", "causal",
                     "curriculum", "topology", "speculation", "metrics", "adapters"):
            self.assertTrue(hasattr(rt, attr), f"facade lost {attr}")
        self.assertEqual(set(rt.adapters), set(AUDITED_APPS))


class TelemetryContractTest(unittest.TestCase):
    def test_maintenance_returns_the_audited_report_keys(self):
        report = hivemind_v15.HivemindV15().maintenance()
        self.assertEqual(
            set(report),
            {"apps", "memory", "rested_modules", "dissolved_clusters",
             "error_correction_gaps", "metrics", "anomaly_curriculum_level",
             "active_clusters"},
        )
        self.assertEqual(set(report["memory"]), {"removed", "retained"})


class PersistenceContractTest(unittest.TestCase):
    """The runtime holds no durable state. Pinned so the claim cannot rot unnoticed."""

    def test_module_performs_no_file_or_database_persistence(self):
        with open(_PY, encoding="utf-8") as fh:
            body = [ln for ln in fh if not ln.lstrip().startswith("#")]
        src = "".join(body)
        for forbidden in ("sqlite", "pickle", "shelve", "redis.", "open("):
            self.assertNotIn(forbidden, src,
                             f"{forbidden!r} appeared; the no-persistence audit is stale")

    def test_runtime_is_a_process_local_singleton(self):
        self.assertIs(hivemind_v15.runtime(), hivemind_v15.runtime())
        self.assertIsNot(hivemind_v15.runtime(), hivemind_v15.HivemindV15())

    def test_scheduled_tick_consolidates_an_empty_runtime(self):
        """AUDIT FINDING, pinned as a characterisation test — not an endorsement.

        hivemind_v15_tick.py runs in its own process, so runtime() hands it a fresh
        HivemindV15 with none of the runner's accumulated state. A fix that makes the
        300s tick meaningful (persistence, or in-process maintenance) SHOULD break this
        test; that is the signal to update docs/v15-00-baseline-contract-audit-slice-1.md.
        """
        fresh = hivemind_v15.HivemindV15()
        report = fresh.maintenance()
        self.assertEqual(report["memory"]["retained"], 0)
        self.assertEqual(report["active_clusters"], 0)
        self.assertEqual(report["metrics"], {})


class AuditDocumentTest(unittest.TestCase):
    def test_audit_document_is_checked_in_and_cites_both_source_commits(self):
        with open(_DOC, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("b3d38813ade9ccc8d989c03663c2f59ddddfcac8", text)
        self.assertIn("e2834ef5990e255d8b2baae7fab8132e8ce96a7d", text)
        for section in ("Public interface", "Feature flags", "Persistence format",
                        "Telemetry", "Privacy boundaries", "Current consumers"):
            self.assertIn(section, text)


if __name__ == "__main__":
    unittest.main()
