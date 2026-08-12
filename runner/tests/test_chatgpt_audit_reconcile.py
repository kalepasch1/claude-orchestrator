"""Disposition/reconciliation for the ChatGPT/Codex local-build audit registry.

The registry suppressed an evidence item forever once any intake manifest had
claimed it. The duplicate-manifest cleanup then deleted manifests without
recording why — 95 of 120 live entries pointed at files that no longer existed.
Those items were simultaneously un-queued and un-queueable: silently lost, with
no way to tell "already covered" from "dropped on the floor".

These tests pin the repair: suppression now requires either a live manifest or
an explicit recorded disposition, and `--reconcile` writes that disposition
with successor provenance.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "chatgpt-bridge" / "local_build_audit.py"
SPEC = importlib.util.spec_from_file_location("local_build_audit_reconcile", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(audit)


class _RegistryCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.intake = self.root / "intake"
        self.intake.mkdir()
        self.state = self.root / "registry.json"
        self.addCleanup(self._tmp.cleanup)

    def _write_state(self, payload):
        self.state.write_text(json.dumps(payload), encoding="utf-8")

    def _read_state(self):
        return json.loads(self.state.read_text(encoding="utf-8"))

    def _group(self, project="beethoven", kind="branch", path="/tmp/a"):
        return {project: [{"kind": kind, "path": path, "repo": project}]}


class TestOrphanedEvidenceReopens(_RegistryCase):

    def test_item_stays_suppressed_while_manifest_exists(self):
        """Normal dedupe is unchanged: a live manifest still suppresses."""
        groups = self._group()
        first, _dupes = audit.queue_groups(groups, self.intake, self.state)
        self.assertEqual(len(first), 1)
        self.assertTrue(Path(first[0]["intake"]).exists())

        second, dupes = audit.queue_groups(groups, self.intake, self.state)
        self.assertEqual(second, [], "identical evidence must not re-queue")
        self.assertEqual(len(dupes), 1)

    def test_deleted_manifest_without_disposition_reopens_item(self):
        """The regression: manifest cleanup must not silently lose evidence."""
        groups = self._group()
        first, _ = audit.queue_groups(groups, self.intake, self.state)
        Path(first[0]["intake"]).unlink()  # duplicate-manifest cleanup

        second, _dupes = audit.queue_groups(groups, self.intake, self.state)
        self.assertEqual(len(second), 1,
                         "evidence orphaned by manifest cleanup must re-queue")
        self.assertTrue(Path(second[0]["intake"]).exists())

    def test_deleted_manifest_with_disposition_stays_settled(self):
        """A recorded disposition is the thing that closes an entry."""
        groups = self._group()
        first, _ = audit.queue_groups(groups, self.intake, self.state)
        fp = first[0]["fingerprint"]
        Path(first[0]["intake"]).unlink()

        audit.reconcile_fingerprint(fp, self.state, disposition="covered",
                                    successor="agent/some-successor")

        second, dupes = audit.queue_groups(groups, self.intake, self.state)
        self.assertEqual(second, [],
                         "an explicitly covered entry must not re-queue")
        self.assertEqual(len(dupes), 1)

    def test_new_entries_record_owning_fingerprint(self):
        groups = self._group()
        first, _ = audit.queue_groups(groups, self.intake, self.state)
        fp = first[0]["fingerprint"]
        evidence = self._read_state()["evidence"]
        self.assertTrue(evidence, "evidence registry must not be empty")
        self.assertTrue(all(rec.get("queued_fp") == fp for rec in evidence.values()),
                        "each item needs a back-reference to its owning entry")


class TestOrphanReopenIsBounded(_RegistryCase):
    """Recovery must drain gradually, not flood the queue in one sweep."""

    def _many(self, n, project="beethoven"):
        return {project: [{"kind": "branch", "path": f"/tmp/b{i}", "repo": project}
                          for i in range(n)]}

    def _orphan_everything(self):
        state = self._read_state()
        for entry in state["queued"].values():
            path = Path(entry["intake"])
            if path.exists():
                path.unlink()
        return state

    def test_reopen_is_capped_per_run(self):
        groups = self._many(8)
        audit.queue_groups(groups, self.intake, self.state)
        self._orphan_everything()

        original = audit.ORPHAN_REOPEN_LIMIT
        audit.ORPHAN_REOPEN_LIMIT = 3
        try:
            requeued, _ = audit.queue_groups(groups, self.intake, self.state)
        finally:
            audit.ORPHAN_REOPEN_LIMIT = original

        self.assertEqual(len(requeued), 1, "one manifest per project per run")
        entry = next(iter(self._read_state()["queued"].values()))
        self.assertLessEqual(
            max(e.get("items", 0) for e in self._read_state()["queued"].values()), 8)
        self.assertEqual(requeued[0]["project"], "beethoven")
        # The new manifest must carry only the capped slice.
        new_entry = self._read_state()["queued"][requeued[0]["fingerprint"]]
        self.assertEqual(new_entry["items"], 3)
        self.assertIsNotNone(entry)

    def test_successive_runs_drain_the_backlog(self):
        groups = self._many(5)
        audit.queue_groups(groups, self.intake, self.state)
        self._orphan_everything()

        original = audit.ORPHAN_REOPEN_LIMIT
        audit.ORPHAN_REOPEN_LIMIT = 2
        try:
            recovered = 0
            for _ in range(4):
                out, _ = audit.queue_groups(groups, self.intake, self.state)
                for row in out:
                    recovered += self._read_state()["queued"][row["fingerprint"]]["items"]
                # Newly written manifests keep their items suppressed; orphan
                # the rest so the next run continues draining.
                for row in out:
                    Path(row["intake"]).unlink()
        finally:
            audit.ORPHAN_REOPEN_LIMIT = original
        self.assertGreaterEqual(recovered, 5, "backlog must fully drain over runs")

    def test_zero_limit_disables_reopen_but_keeps_new_evidence(self):
        groups = self._many(3)
        audit.queue_groups(groups, self.intake, self.state)
        self._orphan_everything()

        original = audit.ORPHAN_REOPEN_LIMIT
        audit.ORPHAN_REOPEN_LIMIT = 0
        try:
            blocked, _ = audit.queue_groups(groups, self.intake, self.state)
            self.assertEqual(blocked, [], "limit 0 must suppress orphan recovery")
            # A genuinely new item is unaffected by the orphan budget.
            grown = {"beethoven": groups["beethoven"] + [
                {"kind": "branch", "path": "/tmp/brand-new", "repo": "beethoven"}]}
            fresh, _ = audit.queue_groups(grown, self.intake, self.state)
            self.assertEqual(len(fresh), 1)
            self.assertEqual(
                self._read_state()["queued"][fresh[0]["fingerprint"]]["items"], 1)
        finally:
            audit.ORPHAN_REOPEN_LIMIT = original


class TestReconcileFingerprint(_RegistryCase):

    def test_unknown_fingerprint_reports_not_found(self):
        self._write_state({"schema": 2, "queued": {}, "evidence": {}})
        result = audit.reconcile_fingerprint("deadbeef", self.state)
        self.assertEqual(result["status"], "not_found")

    def test_short_prefix_resolves_to_full_fingerprint(self):
        groups = self._group()
        first, _ = audit.queue_groups(groups, self.intake, self.state)
        fp = first[0]["fingerprint"]
        result = audit.reconcile_fingerprint(fp[:12], self.state)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fingerprint"], fp)
        self.assertEqual(result["slug"], first[0]["slug"])

    def test_live_manifest_classifies_open(self):
        groups = self._group()
        first, _ = audit.queue_groups(groups, self.intake, self.state)
        result = audit.reconcile_fingerprint(first[0]["fingerprint"], self.state)
        self.assertEqual(result["disposition"], "open")
        self.assertTrue(result["manifest_present"])

    def test_missing_manifest_with_no_open_items_classifies_covered(self):
        groups = self._group()
        first, _ = audit.queue_groups(groups, self.intake, self.state)
        fp = first[0]["fingerprint"]
        Path(first[0]["intake"]).unlink()
        # Settle the member items first so nothing remains open.
        audit.reconcile_fingerprint(fp, self.state, disposition="covered")
        result = audit.reconcile_fingerprint(fp, self.state)
        self.assertEqual(result["disposition"], "covered")
        self.assertFalse(result["manifest_present"])
        self.assertEqual(result["open_evidence_items"], 0)

    def test_successor_and_note_are_durable(self):
        groups = self._group()
        first, _ = audit.queue_groups(groups, self.intake, self.state)
        fp = first[0]["fingerprint"]
        audit.reconcile_fingerprint(
            fp, self.state, disposition="superseded",
            successor="agent/live-successor-task", note="covered by live task")

        entry = self._read_state()["queued"][fp]
        self.assertEqual(entry["disposition"], "superseded")
        self.assertEqual(entry["successor"], "agent/live-successor-task")
        self.assertEqual(entry["reconcile_note"], "covered by live task")
        self.assertIsInstance(entry["reconciled_at"], int)
        self.assertGreater(entry["reconciled_at"], 0)

    def test_settling_propagates_to_member_evidence(self):
        groups = self._group()
        first, _ = audit.queue_groups(groups, self.intake, self.state)
        fp = first[0]["fingerprint"]
        audit.reconcile_fingerprint(fp, self.state, disposition="covered",
                                    successor="agent/x")
        evidence = self._read_state()["evidence"]
        self.assertTrue(evidence)
        for record in evidence.values():
            self.assertEqual(record["disposition"], "covered")
            self.assertEqual(record["successor"], "agent/x")

    def test_reconcile_never_touches_evidence_sources(self):
        """Only the registry file may be written."""
        groups = self._group()
        first, _ = audit.queue_groups(groups, self.intake, self.state)
        manifest = Path(first[0]["intake"])
        before = manifest.read_bytes()
        listing_before = sorted(p.name for p in self.intake.iterdir())

        audit.reconcile_fingerprint(first[0]["fingerprint"], self.state,
                                    disposition="covered")

        self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.intake.iterdir()),
                         listing_before)


class TestRegistryOrphans(_RegistryCase):

    def test_lists_only_undispositioned_missing_manifests(self):
        self._write_state({
            "schema": 2,
            "queued": {
                "aaa": {"project": "beethoven", "slug": "gone-no-disposition",
                        "intake": str(self.intake / "missing.md")},
                "bbb": {"project": "beethoven", "slug": "gone-but-covered",
                        "intake": str(self.intake / "missing2.md"),
                        "disposition": "covered"},
                "ccc": {"project": "tomorrow", "slug": "still-live",
                        "intake": str(self.intake / "live.md")},
            },
            "evidence": {},
        })
        (self.intake / "live.md").write_text("x", encoding="utf-8")

        orphans = audit.registry_orphans(self.state)
        self.assertEqual([o["slug"] for o in orphans], ["gone-no-disposition"])

    def test_empty_registry_is_fail_soft(self):
        self.assertEqual(audit.registry_orphans(self.root / "nope.json"), [])


class TestCli(_RegistryCase):

    def test_list_orphans_exits_clean(self):
        self._write_state({"schema": 2, "queued": {}, "evidence": {}})
        rc = audit.main(["--state", str(self.state), "--list-orphans"])
        self.assertEqual(rc, 0)

    def test_reconcile_unknown_fingerprint_exits_nonzero(self):
        self._write_state({"schema": 2, "queued": {}, "evidence": {}})
        rc = audit.main(["--state", str(self.state), "--reconcile", "nope"])
        self.assertEqual(rc, 1)

    def test_reconcile_records_disposition_via_cli(self):
        groups = self._group()
        first, _ = audit.queue_groups(groups, self.intake, self.state)
        fp = first[0]["fingerprint"]
        rc = audit.main(["--state", str(self.state), "--reconcile", fp[:12],
                         "--disposition", "covered",
                         "--successor", "agent/cli-successor"])
        self.assertEqual(rc, 0)
        entry = self._read_state()["queued"][fp]
        self.assertEqual(entry["disposition"], "covered")
        self.assertEqual(entry["successor"], "agent/cli-successor")


if __name__ == "__main__":
    unittest.main()
