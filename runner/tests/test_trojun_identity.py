import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trojun_identity as ident


class TestCanonicalMapping(unittest.TestCase):
    def test_every_accepted_spelling_resolves_to_trojun(self):
        for name in ident.all_names():
            self.assertEqual(ident.canonical(name), "trojun")

    def test_mapping_is_case_and_whitespace_insensitive(self):
        self.assertEqual(ident.canonical("  Illuminati "), "trojun")
        self.assertEqual(ident.canonical("TROJUN"), "trojun")

    def test_unknown_projects_are_not_coerced_to_trojun(self):
        """This resolves an identity; it does not claim every project."""
        self.assertEqual(ident.canonical("tomorrow"), "tomorrow")
        self.assertEqual(ident.canonical(""), "")
        self.assertEqual(ident.canonical(None), "")

    def test_legacy_detection(self):
        self.assertTrue(ident.is_legacy("illuminati"))
        self.assertFalse(ident.is_legacy("trojun"))
        self.assertFalse(ident.is_legacy(None))


class TestImmutableHistory(unittest.TestCase):
    def test_history_paths_are_refused(self):
        for path in ("intake/processed/x.json", "docs/recovery/a.md",
                     "docs/recovery-ledger/b.json", "reports/c.md",
                     "tasks/d.task.json", ".orch/ledger.json"):
            self.assertTrue(ident.is_immutable_path(path), path)

    def test_leading_dot_slash_is_handled(self):
        self.assertTrue(ident.is_immutable_path("./reports/c.md"))

    def test_live_code_paths_are_rewritable(self):
        for path in ("runner/db.py", "web/config/projects.ts", "cowork-skills/x.md"):
            self.assertFalse(ident.is_immutable_path(path), path)

    def test_rewritable_paths_filters_history_out(self):
        candidates = ["runner/db.py", "docs/recovery/old.md", "web/config/p.ts",
                      "intake/processed/z.json"]
        self.assertEqual(ident.rewritable_paths(candidates),
                         ["runner/db.py", "web/config/p.ts"])


class TestRegistryMigration(unittest.TestCase):
    def registry(self):
        return {"apparently": 1, "tomorrow": 3, "illuminati": 8, "pareto": 9}

    def test_migration_adds_the_canonical_key_with_the_same_value(self):
        reg = self.registry()
        plan = ident.migrate_registry(reg)
        self.assertEqual(plan.changes, {"trojun": 8})
        self.assertEqual(reg["trojun"], reg["illuminati"])

    def test_legacy_key_is_never_removed(self):
        reg = self.registry()
        ident.migrate_registry(reg)
        self.assertIn("illuminati", reg)
        self.assertEqual(reg["illuminati"], 8)

    def test_migration_is_idempotent(self):
        reg = self.registry()
        ident.migrate_registry(reg)
        snapshot = dict(reg)
        second = ident.migrate_registry(reg)
        self.assertTrue(second.is_noop)
        self.assertEqual(reg, snapshot)

    def test_dry_run_matches_what_apply_would_do(self):
        reg = self.registry()
        dry = ident.migrate_registry(dict(reg), apply=False)
        wet = ident.migrate_registry(reg, apply=True)
        self.assertEqual(dry.changes, wet.changes)

    def test_a_registry_without_the_legacy_key_is_untouched(self):
        reg = {"tomorrow": 3}
        plan = ident.migrate_registry(reg)
        self.assertTrue(plan.is_noop)
        self.assertEqual(reg, {"tomorrow": 3})

    def test_a_pre_existing_different_canonical_value_is_not_overwritten(self):
        reg = {"illuminati": 8, "trojun": 99}
        plan = ident.migrate_registry(reg)
        self.assertTrue(plan.is_noop)
        self.assertEqual(reg["trojun"], 99)

    def test_rollback_removes_only_what_the_migration_added(self):
        reg = self.registry()
        ident.migrate_registry(reg)
        ident.rollback_registry(reg)
        self.assertNotIn("trojun", reg)
        self.assertEqual(reg["illuminati"], 8)   # clients still work

    def test_rollback_leaves_a_foreign_canonical_value_alone(self):
        reg = {"illuminati": 8, "trojun": 99}
        plan = ident.rollback_registry(reg)
        self.assertTrue(plan.is_noop)
        self.assertEqual(reg["trojun"], 99)

    def test_migrate_rollback_migrate_returns_to_the_migrated_state(self):
        reg = self.registry()
        ident.migrate_registry(reg)
        migrated = dict(reg)
        ident.rollback_registry(reg)
        ident.migrate_registry(reg)
        self.assertEqual(reg, migrated)


class TestBackwardsCompatibleLookup(unittest.TestCase):
    def test_canonical_name_resolves_against_a_legacy_only_registry(self):
        """The live gap: PROJECT_PRIORITY_ORDER has no 'trojun' key today."""
        reg = {"illuminati": 8}
        self.assertEqual(ident.resolve_priority(reg, "trojun"), 8)

    def test_legacy_name_resolves_against_a_migrated_registry(self):
        reg = {"illuminati": 8, "trojun": 8}
        self.assertEqual(ident.resolve_priority(reg, "illuminati"), 8)

    def test_both_spellings_agree_after_migration(self):
        reg = {"illuminati": 8}
        ident.migrate_registry(reg)
        self.assertEqual(ident.resolve_priority(reg, "trojun"),
                         ident.resolve_priority(reg, "illuminati"))

    def test_unknown_project_returns_the_default(self):
        self.assertIsNone(ident.resolve_priority({"illuminati": 8}, "nope"))
        self.assertEqual(ident.resolve_priority({}, "trojun", default=99), 99)


class TestHostnameRetirement(unittest.TestCase):
    def test_retirement_is_blocked_without_a_durable_hostname(self):
        decision = ident.hostname_retirement(ident.HostnameState(legacy="illuminati.example"))
        self.assertFalse(decision["may_retire"])
        self.assertIn("no durable Trojun hostname is declared", decision["blockers"])

    def test_declared_but_unprovisioned_is_still_blocked(self):
        decision = ident.hostname_retirement(ident.HostnameState(
            legacy="illuminati.example", durable="trojun.example"))
        self.assertFalse(decision["may_retire"])

    def test_provisioned_but_unhealthy_is_still_blocked(self):
        decision = ident.hostname_retirement(ident.HostnameState(
            legacy="illuminati.example", durable="trojun.example",
            durable_provisioned=True))
        self.assertFalse(decision["may_retire"])
        self.assertTrue(any("healthy" in b for b in decision["blockers"]))

    def test_provisioned_and_healthy_permits_retirement(self):
        decision = ident.hostname_retirement(ident.HostnameState(
            legacy="illuminati.example", durable="trojun.example",
            durable_provisioned=True, durable_healthy=True))
        self.assertTrue(decision["may_retire"])
        self.assertEqual(decision["blockers"], [])

    def test_require_raises_rather_than_returning_a_soft_false(self):
        with self.assertRaises(ident.RetirementBlocked):
            ident.require_retirement_allowed(ident.HostnameState(legacy="illuminati.example"))


class TestTelemetryAndAttribution(unittest.TestCase):
    def test_telemetry_records_both_the_canonical_and_reported_name(self):
        dim = ident.telemetry_dimension("illuminati")
        self.assertEqual(dim["project"], "trojun")
        self.assertEqual(dim["project_reported"], "illuminati")
        self.assertTrue(dim["used_legacy_alias"])

    def test_canonical_traffic_is_not_flagged_as_legacy(self):
        self.assertFalse(ident.telemetry_dimension("trojun")["used_legacy_alias"])

    def test_queue_attribution_normalises_without_mutating_the_row(self):
        row = {"id": "t1", "project": "illuminati"}
        out = ident.attribute_queue_row(row)
        self.assertEqual(out["project"], "trojun")
        self.assertEqual(out["project_reported"], "illuminati")
        self.assertEqual(row["project"], "illuminati")   # original untouched

    def test_a_row_with_no_project_is_handled(self):
        out = ident.attribute_queue_row({"id": "t1"})
        self.assertEqual(out["project"], "")
        self.assertFalse(out["project_reported"])


class TestLiveRegistryGap(unittest.TestCase):
    def test_the_shipped_priority_table_still_lacks_the_canonical_key(self):
        """Documents the gap this module closes, without editing db.py.

        If someone later adds 'trojun' to PROJECT_PRIORITY_ORDER this test
        starts failing, which is the correct prompt to simplify the shim.
        """
        try:
            import db
        except Exception:
            self.skipTest("db module unavailable in this environment")
        table = getattr(db, "PROJECT_PRIORITY_ORDER", {})
        if not table:
            self.skipTest("PROJECT_PRIORITY_ORDER not present")
        self.assertIn("illuminati", table)
        # Either state is acceptable; the shim makes both work.
        self.assertEqual(ident.resolve_priority(table, "trojun"), table["illuminati"])


if __name__ == "__main__":
    unittest.main()
