"""Artifact-recovery contract for consolidated stale backlog recovery.

`consolidate_duplicates` is heavily covered (test_stale_backlog_consolidation.py)
and the pipeline has broad coverage (test_stale_backlog_recovery.py), but the
artifact side of the feature did not: `get_artifact_data` had no direct test at
all, and `detect_lost_data` carried an unwritten contract that is easy to
"fix" into a bug.

That contract is the reason this file exists. `detect_lost_data` reports a task
only when the `artifact_id` KEY IS PRESENT and falsy — a row that omits the key
entirely is NOT reported. That looks like an oversight and is not: callers hand
this function rows straight out of `db.select`, and a narrow column list produces
rows with no `artifact_id` key at all. Treating those as lost would report every
task in a partial select as unrecoverable work. Pinning it here means a later
change has to argue with a test instead of silently flipping the pipeline into
false positives.

Pure: `task_artifacts` is stubbed, no DB, no network, no git.
"""
import os
import sys
import types
import unittest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import stale_backlog_recovery as sbr  # noqa: E402


class _StubArtifacts:
    """Install a fake `task_artifacts` module for the duration of a test."""

    def __init__(self, get_artifacts):
        self._get = get_artifacts
        self._saved = None

    def __enter__(self):
        self._saved = sys.modules.get("task_artifacts")
        module = types.ModuleType("task_artifacts")
        module.get_artifacts = self._get
        sys.modules["task_artifacts"] = module
        return module

    def __exit__(self, *exc):
        if self._saved is None:
            sys.modules.pop("task_artifacts", None)
        else:
            sys.modules["task_artifacts"] = self._saved
        return False


class GetArtifactDataTest(unittest.TestCase):
    """Fail-soft lookup: never raises, None whenever data is unavailable."""

    def test_falsy_key_returns_none_without_importing(self):
        def explode(_):  # pragma: no cover - must never run
            raise AssertionError("lookup attempted for a falsy key")

        with _StubArtifacts(explode):
            for key in (None, "", 0):
                self.assertIsNone(sbr.get_artifact_data(key))

    def test_delegates_to_task_artifacts(self):
        seen = []

        def capture(key):
            seen.append(key)
            return {"key": key, "commit": "abc123"}

        with _StubArtifacts(capture):
            data = sbr.get_artifact_data("slug-1")
        self.assertEqual(seen, ["slug-1"])
        self.assertEqual(data, {"key": "slug-1", "commit": "abc123"})

    def test_lookup_error_is_swallowed(self):
        def boom(_):
            raise RuntimeError("artifact store down")

        with _StubArtifacts(boom):
            self.assertIsNone(sbr.get_artifact_data("slug-1"))

    def test_missing_task_artifacts_module_returns_none(self):
        saved = sys.modules.pop("task_artifacts", None)
        blocker = object()
        sys.modules["task_artifacts"] = None  # forces ImportError on import
        try:
            self.assertIsNone(sbr.get_artifact_data("slug-1"))
        finally:
            sys.modules.pop("task_artifacts", None)
            if saved is not None:
                sys.modules["task_artifacts"] = saved
        del blocker


class MaterializeLostDataTest(unittest.TestCase):
    def test_non_dict_is_fail_soft(self):
        for bad in (None, "slug", 7, [], object()):
            self.assertIsNone(sbr.materialize_lost_data(bad))

    def test_artifact_id_is_preferred_over_slug(self):
        with _StubArtifacts(lambda key: {"key": key}):
            data = sbr.materialize_lost_data({"artifact_id": "A", "slug": "S"})
        self.assertEqual(data["key"], "A")

    def test_slug_is_the_fallback_key(self):
        with _StubArtifacts(lambda key: {"key": key}):
            data = sbr.materialize_lost_data({"slug": "S"})
        self.assertEqual(data["key"], "S")

    def test_empty_artifact_id_falls_back_to_slug(self):
        with _StubArtifacts(lambda key: {"key": key}):
            data = sbr.materialize_lost_data({"artifact_id": "", "slug": "S"})
        self.assertEqual(data["key"], "S")

    def test_no_stored_data_returns_none(self):
        with _StubArtifacts(lambda key: None):
            self.assertIsNone(sbr.materialize_lost_data({"slug": "S"}))

    def test_result_is_a_copy_so_callers_cannot_mutate_the_store(self):
        stored = {"key": "S", "files": ["a.py"]}
        with _StubArtifacts(lambda key: stored):
            data = sbr.materialize_lost_data({"slug": "S"})
        self.assertIsNot(data, stored)
        data["key"] = "mutated"
        self.assertEqual(stored["key"], "S")


class DetectLostDataKeyPresenceTest(unittest.TestCase):
    """The deliberate contract: absent key != lost artifact."""

    def test_present_but_falsy_artifact_id_is_reported(self):
        for falsy in (None, "", 0):
            found = sbr.detect_lost_data([{"id": 1, "slug": "a", "artifact_id": falsy}])
            self.assertEqual(found, [{"id": 1, "slug": "a", "issue": "missing_artifacts"}])

    def test_absent_key_is_not_reported(self):
        """A narrow db.select omits the column; that is not lost work."""
        self.assertEqual(sbr.detect_lost_data([{"id": 1, "slug": "a"}]), [])

    def test_populated_artifact_id_is_not_reported(self):
        self.assertEqual(sbr.detect_lost_data([{"id": 1, "slug": "a", "artifact_id": "x"}]), [])

    def test_non_dict_rows_are_skipped(self):
        self.assertEqual(sbr.detect_lost_data(["x", None, 7]), [])

    def test_none_input_is_fail_soft(self):
        self.assertEqual(sbr.detect_lost_data(None), [])

    def test_mixed_batch_reports_only_the_lost_rows(self):
        found = sbr.detect_lost_data([
            {"id": 1, "slug": "keep", "artifact_id": "abc"},
            {"id": 2, "slug": "lost", "artifact_id": None},
            {"id": 3, "slug": "partial-select"},
        ])
        self.assertEqual([r["slug"] for r in found], ["lost"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
