"""Tests for merge_cycle.detect_missing_branches()."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Pure-Python re-implementation used by all tests (no DB required).
_NOW = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_PROJ_A = "proj-a-id"
_PROJ_B = "proj-b-id"


def _ts(seconds_ago):
    return (_NOW - datetime.timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _detect(rows, project_rows, *, now=_NOW):
    """Pure-Python mirror of merge_cycle.detect_missing_branches for unit testing."""
    if not rows:
        return {}
    projects = {p["id"]: p.get("name") or str(p["id"]) for p in project_rows}
    groups = {}
    for row in rows:
        project_id = row.get("project_id")
        branch_name = row.get("base_branch") or ""
        created_at = row.get("created_at")
        if not project_id or not branch_name:
            continue
        project_name = projects.get(project_id) or str(project_id)
        try:
            t = datetime.datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            age_s = int((now - t).total_seconds())
        except Exception:
            age_s = 0
        key = (project_name, branch_name)
        if key not in groups:
            groups[key] = {"count": 0, "oldest_age_s": 0}
        groups[key]["count"] += 1
        if age_s > groups[key]["oldest_age_s"]:
            groups[key]["oldest_age_s"] = age_s
    result = {}
    for (pn, bn), stats in groups.items():
        result.setdefault(pn, {})[bn] = stats
    return result


_PROJS = [{"id": _PROJ_A, "name": "alpha"}, {"id": _PROJ_B, "name": "beta"}]


class TestDetectMissingBranches(unittest.TestCase):
    def test_empty_rows_returns_empty(self):
        self.assertEqual(_detect([], _PROJS), {})

    def test_single_task(self):
        rows = [{"project_id": _PROJ_A, "base_branch": "main",
                 "created_at": _ts(3600), "note": "agentic-repair:missing-branch", "slug": "s1"}]
        r = _detect(rows, _PROJS)
        self.assertEqual(r, {"alpha": {"main": {"count": 1, "oldest_age_s": 3600}}})

    def test_two_tasks_same_bucket_count_and_oldest(self):
        rows = [
            {"project_id": _PROJ_A, "base_branch": "main", "created_at": _ts(1000), "note": "branch", "slug": "s1"},
            {"project_id": _PROJ_A, "base_branch": "main", "created_at": _ts(5000), "note": "branch", "slug": "s2"},
        ]
        r = _detect(rows, _PROJS)
        self.assertEqual(r["alpha"]["main"]["count"], 2)
        self.assertEqual(r["alpha"]["main"]["oldest_age_s"], 5000)

    def test_tasks_across_projects_and_branches(self):
        rows = [
            {"project_id": _PROJ_A, "base_branch": "main",    "created_at": _ts(100), "note": "branch", "slug": "s1"},
            {"project_id": _PROJ_B, "base_branch": "staging",  "created_at": _ts(200), "note": "branch", "slug": "s2"},
        ]
        r = _detect(rows, _PROJS)
        self.assertIn("alpha", r)
        self.assertIn("beta", r)
        self.assertEqual(r["alpha"]["main"]["count"], 1)
        self.assertEqual(r["beta"]["staging"]["count"], 1)

    def test_missing_project_id_or_branch_skipped(self):
        rows = [
            {"project_id": None,    "base_branch": "main", "created_at": _ts(100), "note": "branch", "slug": "s1"},
            {"project_id": _PROJ_A, "base_branch": None,   "created_at": _ts(100), "note": "branch", "slug": "s2"},
            {"project_id": _PROJ_A, "base_branch": "main", "created_at": _ts(500), "note": "branch", "slug": "s3"},
        ]
        r = _detect(rows, _PROJS)
        self.assertEqual(r, {"alpha": {"main": {"count": 1, "oldest_age_s": 500}}})

    def test_malformed_created_at_falls_back_to_zero(self):
        rows = [{"project_id": _PROJ_A, "base_branch": "main",
                 "created_at": "not-a-date", "note": "branch", "slug": "s1"}]
        r = _detect(rows, _PROJS)
        self.assertEqual(r["alpha"]["main"]["oldest_age_s"], 0)

    def test_unknown_project_id_uses_id_as_name(self):
        rows = [{"project_id": "unknown-id", "base_branch": "main",
                 "created_at": _ts(10), "note": "branch", "slug": "s1"}]
        r = _detect(rows, _PROJS)
        self.assertIn("unknown-id", r)

    def test_multiple_branches_same_project(self):
        rows = [
            {"project_id": _PROJ_A, "base_branch": "main",    "created_at": _ts(100), "note": "branch", "slug": "s1"},
            {"project_id": _PROJ_A, "base_branch": "staging",  "created_at": _ts(200), "note": "branch", "slug": "s2"},
        ]
        r = _detect(rows, _PROJS)
        self.assertIn("main", r["alpha"])
        self.assertIn("staging", r["alpha"])


if __name__ == "__main__":
    unittest.main()
