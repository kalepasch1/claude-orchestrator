#!/usr/bin/env python3
"""
Regression fixtures for canonical_proof_ledger.

The four defects named in the task spec each get a fixture, because each is a shape the
old scattered readers rendered as success:

  * phantom MERGED   — state says MERGED, no artifact exists
  * missing artifact — task_artifacts unreadable, which is not the same as empty
  * stale release    — release sha matches but the release predates the artifact
  * beyond row 1000  — evidence sitting past PostgREST's implicit response cap

Plus the two rules that hold everything together: PASS always carries a receipt, and
MERGED never renders as PASS.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import canonical_proof_ledger as cpl  # noqa: E402


# ---------------------------------------------------------------------------
# A stub that behaves like PostgREST: honours limit/offset and never returns more
# than POSTGREST_IMPLICIT_LIMIT rows in one response.
# ---------------------------------------------------------------------------

class FakeDB:
    def __init__(self, tables=None, unreadable=()):
        self.tables = tables or {}
        self.unreadable = set(unreadable)
        self.calls = []

    def select(self, table, params=None):
        params = params or {}
        self.calls.append((table, dict(params)))
        if table in self.unreadable:
            raise RuntimeError(f"{table} is unreadable")
        rows = list(self.tables.get(table, []))

        # Apply the eq./in. filters this projection actually sends.
        for key, raw in params.items():
            if key in ("select", "order", "limit", "offset"):
                continue
            value = str(raw)
            if value.startswith("eq."):
                rows = [r for r in rows if str(r.get(key)) == value[3:]]
            elif value.startswith("in.("):
                wanted = {v.strip().strip('"') for v in value[4:-1].split(",")}
                rows = [r for r in rows if str(r.get(key)) in wanted]

        offset = int(params.get("offset", 0) or 0)
        limit = int(params.get("limit", cpl.POSTGREST_IMPLICIT_LIMIT) or cpl.POSTGREST_IMPLICIT_LIMIT)
        limit = min(limit, cpl.POSTGREST_IMPLICIT_LIMIT)
        return rows[offset:offset + limit]


def artifact(slug, sha, captured_at="2026-08-01T00:00:00Z", branch="agent/x"):
    return {"slug": slug, "commit_sha": sha, "branch": branch,
            "captured_at": captured_at, "touched_files": [], "test_log": ""}


def release(rid, sha, status="success", created_at="2026-08-02T00:00:00Z", project="beethoven"):
    return {"id": rid, "project": project, "to_sha": sha, "deploy_status": status,
            "created_at": created_at, "deployed_at": created_at,
            "vercel_url": f"https://example.invalid/{rid}", "note": ""}


def journey(sha, name="checkout", ok=True, recorded_at="2026-08-03T00:00:00Z"):
    return {"release_sha": sha, "journey": name, "ok": ok,
            "url": f"https://example.invalid/j/{name}", "recorded_at": recorded_at}


def task(slug, state, sha=None):
    return {"id": slug, "slug": slug, "state": state, "artifact_commit": sha,
            "artifact_branch": "agent/x"}


SHA = "a" * 40
OTHER_SHA = "b" * 40


class PhantomMergedTests(unittest.TestCase):
    """A task claiming MERGED with nothing behind it must not read as progress."""

    def _ledger(self):
        db = FakeDB({"task_artifacts": [artifact("real", SHA)],
                     "releases": [], "shipped_metrics": []})
        return cpl.build_ledger(db.select, project="beethoven",
                                tasks=[task("phantom", "MERGED"), task("real", "MERGED", SHA)])

    def test_phantom_merge_is_not_a_pass(self):
        entry = next(e for e in self._ledger()["entries"] if e["slug"] == "phantom")
        self.assertNotEqual(entry["verdict"], cpl.PASS)
        self.assertEqual(entry["level"], cpl.LEVEL_NO_EVIDENCE)

    def test_phantom_merge_is_named_as_such(self):
        entry = next(e for e in self._ledger()["entries"] if e["slug"] == "phantom")
        self.assertTrue(any("phantom merge" in r for r in entry["reasons"]),
                        entry["reasons"])

    def test_phantom_merge_carries_no_receipt(self):
        entry = next(e for e in self._ledger()["entries"] if e["slug"] == "phantom")
        self.assertIsNone(entry["receipt"])


class MissingArtifactTests(unittest.TestCase):
    """An unreadable table is UNKNOWN. It is not 'no evidence', and never a pass."""

    def test_unreadable_artifacts_table_is_unknown_not_absent(self):
        db = FakeDB({"releases": [], "shipped_metrics": []}, unreadable={"task_artifacts"})
        ledger = cpl.build_ledger(db.select, project="beethoven",
                                  tasks=[task("t1", "MERGED")])
        entry = ledger["entries"][0]
        self.assertEqual(entry["verdict"], cpl.UNKNOWN)
        self.assertIn("task_artifacts", ledger["read_errors"])
        self.assertTrue(any("unknown, not absent" in r for r in entry["reasons"]),
                        entry["reasons"])

    def test_a_queued_task_with_no_artifact_is_pending_not_unknown(self):
        db = FakeDB({"task_artifacts": [artifact("other", SHA)],
                     "releases": [], "shipped_metrics": []})
        ledger = cpl.build_ledger(db.select, project="beethoven",
                                  tasks=[task("t1", "QUEUED")])
        self.assertEqual(ledger["entries"][0]["verdict"], cpl.PENDING)


class StaleReleaseTests(unittest.TestCase):
    """A release cut before the artifact cannot certify it, matching sha or not."""

    def test_release_predating_the_artifact_does_not_certify(self):
        db = FakeDB({
            "task_artifacts": [artifact("t1", SHA, captured_at="2026-08-05T00:00:00Z")],
            "releases": [release("r1", SHA, created_at="2026-08-01T00:00:00Z")],
            "shipped_metrics": [journey(SHA)],
        })
        entry = cpl.build_ledger(db.select, project="beethoven",
                                 tasks=[task("t1", "MERGED", SHA)])["entries"][0]
        self.assertEqual(entry["level"], cpl.LEVEL_MERGED)
        self.assertNotEqual(entry["verdict"], cpl.PASS)
        self.assertIn(cpl.STALE_RELEASE_NOTE, entry["reasons"])

    def test_a_failed_release_is_reported_with_its_status(self):
        db = FakeDB({
            "task_artifacts": [artifact("t1", SHA)],
            "releases": [release("r1", SHA, status="error")],
            "shipped_metrics": [journey(SHA)],
        })
        entry = cpl.build_ledger(db.select, project="beethoven",
                                 tasks=[task("t1", "MERGED", SHA)])["entries"][0]
        self.assertNotEqual(entry["verdict"], cpl.PASS)
        self.assertTrue(any("did not deploy" in r for r in entry["reasons"]), entry["reasons"])

    def test_a_release_for_a_different_sha_does_not_certify(self):
        db = FakeDB({
            "task_artifacts": [artifact("t1", SHA)],
            "releases": [release("r1", OTHER_SHA)],
            "shipped_metrics": [journey(OTHER_SHA)],
        })
        entry = cpl.build_ledger(db.select, project="beethoven",
                                 tasks=[task("t1", "MERGED", SHA)])["entries"][0]
        self.assertEqual(entry["level"], cpl.LEVEL_MERGED)
        self.assertTrue(any("no release names this artifact commit" in r
                            for r in entry["reasons"]), entry["reasons"])


class BeyondRowOneThousandTests(unittest.TestCase):
    """The defect that made every un-paginated reader lie: evidence past row 1000."""

    def _big_db(self):
        artifacts = [artifact(f"t{i:05d}", f"{i:040x}") for i in range(1500)]
        releases = [release(f"r{i:05d}", f"{i:040x}") for i in range(1500)]
        journeys = [journey(f"{i:040x}") for i in range(1500)]
        return FakeDB({"task_artifacts": artifacts, "releases": releases,
                       "shipped_metrics": journeys})

    def test_paginate_reads_past_the_implicit_cap(self):
        db = self._big_db()
        rows = cpl.paginate(db.select, "task_artifacts", {"select": "*"}, order="slug.asc")
        self.assertEqual(len(rows), 1500)

    def test_a_single_unpaginated_read_would_have_truncated(self):
        """Pins the premise: the stub really does cap at 1000, like PostgREST."""
        db = self._big_db()
        self.assertEqual(len(db.select("task_artifacts", {"select": "*"})), 1000)

    def test_evidence_at_row_1400_still_verifies(self):
        db = self._big_db()
        slug, sha = "t01400", f"{1400:040x}"
        entry = cpl.build_ledger(db.select, project=None,
                                 tasks=[task(slug, "MERGED", sha)])["entries"][0]
        self.assertEqual(entry["level"], cpl.LEVEL_DEPLOYED_AND_VERIFIED)
        self.assertEqual(entry["verdict"], cpl.PASS)
        self.assertIsNotNone(entry["receipt"])

    def test_paginate_respects_max_rows(self):
        db = self._big_db()
        rows = cpl.paginate(db.select, "task_artifacts", {"select": "*"},
                            max_rows=1200, order="slug.asc")
        self.assertEqual(len(rows), 1200)

    def test_paginate_always_sends_an_order(self):
        db = self._big_db()
        cpl.paginate(db.select, "task_artifacts", {"select": "*"}, order="slug.asc")
        self.assertTrue(all(c[1].get("order") for c in db.calls))


class MergedProvesReachabilityOnlyTests(unittest.TestCase):
    """Rule 3, pinned."""

    def test_merged_with_no_release_is_pending_at_level_merged(self):
        db = FakeDB({"task_artifacts": [artifact("t1", SHA)],
                     "releases": [], "shipped_metrics": []})
        entry = cpl.build_ledger(db.select, project="beethoven",
                                 tasks=[task("t1", "MERGED", SHA)])["entries"][0]
        self.assertEqual(entry["level"], cpl.LEVEL_MERGED)
        self.assertEqual(entry["verdict"], cpl.PENDING)
        self.assertIn("MERGED proves integration reachability only", entry["reasons"])

    def test_audit_rejects_a_merged_pass(self):
        forged = {"entries": [{"slug": "x", "level": cpl.LEVEL_MERGED,
                               "verdict": cpl.PASS, "receipt": {"ref": "abc"}}]}
        self.assertTrue(any("MERGED rendered as PASS" in v for v in cpl.audit(forged)))


class DeployedAndVerifiedTests(unittest.TestCase):
    """Rule 4: BOTH halves, or it is PENDING."""

    def _entry(self, releases, journeys, required=None):
        db = FakeDB({"task_artifacts": [artifact("t1", SHA)],
                     "releases": releases, "shipped_metrics": journeys})
        return cpl.build_ledger(db.select, project="beethoven",
                                tasks=[task("t1", "MERGED", SHA)],
                                required_journeys={"t1": required} if required else None)["entries"][0]

    def test_both_halves_present_is_a_pass(self):
        entry = self._entry([release("r1", SHA)], [journey(SHA)])
        self.assertEqual(entry["level"], cpl.LEVEL_DEPLOYED_AND_VERIFIED)
        self.assertEqual(entry["verdict"], cpl.PASS)
        self.assertEqual(entry["receipt"]["kind"], "production_journey")

    def test_release_without_a_journey_receipt_is_pending(self):
        entry = self._entry([release("r1", SHA)], [])
        self.assertEqual(entry["level"], cpl.LEVEL_RELEASED)
        self.assertEqual(entry["verdict"], cpl.PENDING)

    def test_a_failing_journey_receipt_is_not_a_pass(self):
        entry = self._entry([release("r1", SHA)], [journey(SHA, ok=False)])
        self.assertNotEqual(entry["verdict"], cpl.PASS)
        self.assertTrue(any("did not pass" in r for r in entry["reasons"]), entry["reasons"])

    def test_the_wrong_journey_does_not_satisfy_a_task_defined_one(self):
        entry = self._entry([release("r1", SHA)], [journey(SHA, name="healthcheck")],
                            required="checkout")
        self.assertEqual(entry["level"], cpl.LEVEL_RELEASED)
        self.assertNotEqual(entry["verdict"], cpl.PASS)
        self.assertTrue(any("checkout" in r for r in entry["reasons"]), entry["reasons"])

    def test_an_abbreviated_release_sha_still_matches(self):
        entry = self._entry([release("r1", SHA[:12])], [journey(SHA[:12])])
        self.assertEqual(entry["verdict"], cpl.PASS)

    def test_a_six_character_prefix_is_too_short_to_match(self):
        self.assertFalse(cpl._sha_matches(SHA, SHA[:6]))
        self.assertTrue(cpl._sha_matches(SHA, SHA[:7]))


class InvariantTests(unittest.TestCase):
    def test_no_pass_ever_lacks_a_receipt(self):
        db = FakeDB({
            "task_artifacts": [artifact(f"t{i}", f"{i:040x}") for i in range(20)],
            "releases": [release(f"r{i}", f"{i:040x}") for i in range(10)],
            "shipped_metrics": [journey(f"{i:040x}") for i in range(5)],
        })
        tasks = [task(f"t{i}", "MERGED", f"{i:040x}") for i in range(20)]
        ledger = cpl.build_ledger(db.select, project="beethoven", tasks=tasks)
        self.assertEqual(cpl.audit(ledger), [])
        for entry in ledger["entries"]:
            if entry["verdict"] == cpl.PASS:
                self.assertIsNotNone(entry["receipt"])
                self.assertTrue(entry["receipt"]["ref"])

    def test_a_receipt_with_a_blank_ref_is_not_a_receipt(self):
        self.assertIsNone(cpl.receipt("artifact_commit", ""))
        self.assertIsNone(cpl.receipt("artifact_commit", None))
        self.assertIsNone(cpl.receipt("artifact_commit", "   "))

    def test_projection_never_raises_on_garbage(self):
        for bad in (None, [], "x", {"slug": None}, 7):
            entry = cpl.project_task(bad, {})
            self.assertIn(entry["verdict"], cpl.VERDICTS)
            self.assertNotEqual(entry["verdict"], cpl.PASS)

    def test_summary_counts_every_entry_exactly_once(self):
        db = FakeDB({"task_artifacts": [artifact("t1", SHA)],
                     "releases": [], "shipped_metrics": []})
        ledger = cpl.build_ledger(db.select, project="beethoven",
                                  tasks=[task("t1", "MERGED", SHA), task("t2", "QUEUED")])
        self.assertEqual(sum(ledger["summary"].values()), 2)
        self.assertEqual(sum(ledger["by_level"].values()), 2)

    def test_snapshot_keeps_the_reasons(self):
        db = FakeDB({"task_artifacts": [], "releases": [], "shipped_metrics": []})
        snap = cpl.snapshot(cpl.build_ledger(db.select, tasks=[task("t1", "MERGED")]))
        self.assertTrue(snap["entries"][0]["reasons"])
        self.assertEqual(set(snap["entries"][0]), {"slug", "level", "verdict", "receipt", "reasons"})

    def test_levels_are_ordered_weakest_to_strongest(self):
        ranks = [cpl.level_rank(l) for l in cpl.LEVELS]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(cpl.level_rank("NOT_A_LEVEL"), -1)


if __name__ == "__main__":
    unittest.main()
