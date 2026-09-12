"""A release batch carrying a measured regression must not reach the production branch.

Every pre-existing gate on the promotion path asks whether a change is CORRECT --
conflict markers, IP scan, tests, build, build provenance. None asked whether it
HELPED. Measured 2026-09-01: of 1003 rows in improvement_proposals, 395 reached
status='merged' (their code landed) and exactly ONE was ever 'validated'. Zero were
'regressed', because settle() is starved -- but improvement_verify does write that
verdict, by re-running each proposal's own declared metric_query after its window.

This gate is the first consumer of that verdict on the promotion path.
"""
import importlib.util
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

_spec = importlib.util.spec_from_file_location(
    "_release_train_under_test", os.path.join(RUNNER, "release_train.py"))
rt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rt)

MANIFEST = {"id": "m-1"}
CANDIDATES = [{"slug": "improve-cache-the-route-table"}]
MANIFEST_TASKS = [{"slug": "improve-render-gate"}, {"slug": "build-payment-flow"}]


class _FakeDB:
    def __init__(self, regressed_slugs=(), boom=False):
        self.regressed = set(regressed_slugs)
        self.boom = boom
        self.queries = []

    def select(self, table, params):
        self.queries.append((table, params))
        if self.boom:
            raise RuntimeError("supabase unreachable")
        if table != "improvement_proposals":
            return []
        raw = params.get("task_slug", "")
        asked = {s.strip().strip('"') for s in raw[4:-1].split(",")} if raw.startswith("in.(") else set()
        return [{"task_slug": s, "status": "regressed", "title": "t",
                 "realized_multiplier": 0.4, "required_margin": 1.1}
                for s in sorted(asked & self.regressed)]


class ValueGateTests(unittest.TestCase):
    def setUp(self):
        self._db = rt.db
        self._rm = rt.release_manifest
        self.gates = []
        class _RM:
            def record_gate(_s, mid, name, ok, command=""):
                self.gates.append((mid, name, ok, command))
        rt.release_manifest = _RM()

    def tearDown(self):
        rt.db = self._db
        rt.release_manifest = self._rm
        os.environ.pop("ORCH_RELEASE_VALUE_GATE", None)

    # ── the point of the whole thing ─────────────────────────────────────────
    def test_batch_with_a_regression_is_held(self):
        rt.db = _FakeDB(regressed_slugs={"improve-render-gate"})
        out = rt._release_value_gate("tomorrow", MANIFEST, MANIFEST_TASKS, CANDIDATES)
        self.assertIsNotNone(out, "a measured regression was promoted to production")
        self.assertEqual(out["value"], "RED")
        self.assertIn("improve-render-gate", out["regressed"])
        self.assertIn("REGRESSIONS", out["note"])
        self.assertIn(("m-1", "value", False), [(g[0], g[1], g[2]) for g in self.gates])

    def test_clean_batch_proceeds(self):
        rt.db = _FakeDB(regressed_slugs=set())
        out = rt._release_value_gate("tomorrow", MANIFEST, MANIFEST_TASKS, CANDIDATES)
        self.assertIsNone(out, "a clean batch must not be held")
        self.assertIn(("m-1", "value", True), [(g[0], g[1], g[2]) for g in self.gates])

    def test_regression_in_the_candidate_list_is_also_caught(self):
        """Slugs arrive from two places; both must be checked."""
        rt.db = _FakeDB(regressed_slugs={"improve-cache-the-route-table"})
        out = rt._release_value_gate("tomorrow", MANIFEST, MANIFEST_TASKS, CANDIDATES)
        self.assertIsNotNone(out)
        self.assertIn("improve-cache-the-route-table", out["regressed"])

    def test_underdelivered_does_not_block(self):
        """An improvement that helped but missed its ambitious target must still ship.

        The gate queries status='regressed' only. With the three-way verdict, a 1.6x win
        against a 5x margin is 'underdelivered' and never appears in this query -- so the
        batch proceeds. This test pins that: an 'underdelivered' row must not hold a release.
        """
        class _UnderDB(_FakeDB):
            def select(self, table, params):
                self.queries.append((table, params))
                return []   # nothing with status='regressed'
        rt.db = _UnderDB()
        out = rt._release_value_gate("tomorrow", MANIFEST, MANIFEST_TASKS, CANDIDATES)
        self.assertIsNone(out, "an underdelivered improvement blocked the release")
        q = [p for t, p in rt.db.queries if t == "improvement_proposals"]
        self.assertTrue(all(p.get("status") == "eq.regressed" for p in q),
                        "the gate must ask only for true regressions")

    def test_unrelated_regression_does_not_block(self):
        """Only regressions carried BY THIS BATCH may hold it."""
        rt.db = _FakeDB(regressed_slugs={"some-other-project-task"})
        self.assertIsNone(rt._release_value_gate("tomorrow", MANIFEST, MANIFEST_TASKS, CANDIDATES))

    # ── operability ──────────────────────────────────────────────────────────
    def test_gate_is_on_by_default(self):
        rt.db = _FakeDB(regressed_slugs={"improve-render-gate"})
        self.assertIsNotNone(rt._release_value_gate("t", MANIFEST, MANIFEST_TASKS, CANDIDATES))

    def test_flag_disables_the_gate(self):
        os.environ["ORCH_RELEASE_VALUE_GATE"] = "false"
        rt.db = _FakeDB(regressed_slugs={"improve-render-gate"})
        self.assertIsNone(rt._release_value_gate("t", MANIFEST, MANIFEST_TASKS, CANDIDATES))

    def test_unreadable_evidence_does_not_wedge_the_train(self):
        """Fail open, loudly -- a broken gate must not stop all releases forever."""
        rt.db = _FakeDB(boom=True)
        self.assertIsNone(rt._release_value_gate("t", MANIFEST, MANIFEST_TASKS, CANDIDATES))

    def test_empty_batch_proceeds(self):
        rt.db = _FakeDB()
        self.assertIsNone(rt._release_value_gate("t", MANIFEST, [], []))

    def test_slugs_are_deduped_across_both_sources(self):
        dup = [{"slug": "a"}, {"slug": "b"}, {"slug": None}, {}]
        self.assertEqual(rt._batch_slugs(dup, [{"slug": "b"}, {"slug": "c"}]), ["a", "b", "c"])

    def test_large_batch_is_chunked(self):
        """PostgREST in.(...) has a URL-length ceiling."""
        many = [{"slug": f"task-{i}"} for i in range(95)]
        fake = _FakeDB()
        rt.db = fake
        rt._release_value_gate("t", MANIFEST, many, [])
        self.assertEqual(len(fake.queries), 3, "95 slugs should chunk into 3 queries of <=40")


if __name__ == "__main__":
    unittest.main()
