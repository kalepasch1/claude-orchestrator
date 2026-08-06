"""
test_scan_window_correctness.py — the client-side scan window as a CLASS of bug.

The shape `select(table, {"limit": "<big>"})` with no ORDER BY has produced four
outage-class failures on this fleet:

  1. merge_train._pick_cards        — newest 3,000 of 238,177 approvals -> months of
                                      stranded work. Fixed in 7ec2d4e.
  2. merge_train.ensure_integration_card — 240 duplicates of one slug.
  3. ev_scheduler._scored_queue     — an arbitrary, non-reproducible 500 of 1,407 QUEUED
                                      tasks, so ~907 were invisible to EV ordering AND to
                                      zero-EV parking. Fixed here.
  4. config_optimizer queue depth   — len() of a 1,000-row page, so the autoscaler's
                                      queue_depth could not exceed 1,000 at any real load.
                                      Fixed here.

These tests pin the corrected behaviour of the class, not just the two instances:
  1. ev_scheduler scores EVERY queued task, deterministically ordered.
  2. config_optimizer reports true queue depth above 1,000.
  3. A LOOKUP-class query finds its target with 10,000 newer rows present.
  4. The lint rule flags limit>=100 with no order, and passes one with an order.
  5. The 5001 "more than 5000?" sentinel is not flagged.

All db access is faked — no network.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as real_db


class FakeDb:
    """A PostgREST-shaped fake: it enforces the 1,000-row per-response cap.

    The cap is the whole point. A fake that happily returns 5,000 rows for
    `limit: "5000"` would let every one of these bugs pass its own test.
    """

    HARD_PAGE_CAP = 1000

    def __init__(self, rows_by_table):
        self.rows = rows_by_table
        self.select_calls = []

    # -- PostgREST emulation ------------------------------------------------------
    def _filtered(self, table, params):
        rows = list(self.rows.get(table, []))
        for key, val in (params or {}).items():
            if key in ("select", "limit", "offset", "order", "and"):
                continue
            if isinstance(val, str) and val.startswith("eq."):
                want = val[3:]
                rows = [r for r in rows if str(r.get(key)) == want]
            elif isinstance(val, str) and val.startswith("in."):
                want = {w for w in val[3:].strip("()").split(",")}
                rows = [r for r in rows if str(r.get(key)) in want]
        order = (params or {}).get("order")
        if order:
            for spec in reversed(order.split(",")):
                field, _, direction = spec.strip().partition(".")
                rows.sort(key=lambda r: str(r.get(field) or ""),
                          reverse=direction.startswith("desc"))
        return rows

    def select(self, table, params=None):
        self.select_calls.append((table, dict(params or {})))
        rows = self._filtered(table, params)
        offset = int((params or {}).get("offset", 0) or 0)
        limit = int((params or {}).get("limit", self.HARD_PAGE_CAP) or self.HARD_PAGE_CAP)
        limit = min(limit, self.HARD_PAGE_CAP)      # PostgREST never returns more
        return rows[offset:offset + limit]

    def count(self, table, params=None):
        return len(self._filtered(table, params))   # server-side: no cap

    def select_all(self, table, params=None, page_size=None, max_rows=None, order=None):
        return self._select_all(table, params, order)

    def _select_all(self, table, params=None, order=None):
        q = dict(params or {})
        q["order"] = order or q.get("order") or "id.asc"
        q.pop("limit", None)
        q.pop("offset", None)
        out, offset = [], 0
        while True:
            page = self.select(table, dict(q, limit=str(self.HARD_PAGE_CAP),
                                           offset=str(offset)))
            out.extend(page)
            if len(page) < self.HARD_PAGE_CAP:
                return out
            offset += self.HARD_PAGE_CAP

    # -- writes the modules under test may attempt -------------------------------
    def update(self, *a, **k):
        return None

    def upsert(self, *a, **k):
        return None

    def insert(self, *a, **k):
        return None


def _queued(n, project_id="p1"):
    """n QUEUED tasks, oldest first, with ids that do NOT sort like created_at.

    Deliberately adversarial: ids are reversed relative to age, so a test that passes
    under an id-ordered scan but not a created_at-ordered one gets caught.
    """
    return [{"id": f"t{n - i:05d}", "slug": f"task-{i}", "project_id": project_id,
             "state": "QUEUED", "kind": "build", "prompt": "do a thing",
             "attempt": 0, "transient_retries": 0,
             "created_at": f"2026-08-{(i % 28) + 1:02d}T00:{i % 60:02d}:00Z"}
            for i in range(n)]


class TestEvSchedulerScansWholeQueue(unittest.TestCase):
    """Case 1: 1,500 QUEUED tasks are ALL scored, deterministically ordered."""

    def setUp(self):
        import ev_scheduler
        self.mod = ev_scheduler
        self.tasks = _queued(1500)
        self.fake = FakeDb({"tasks": self.tasks,
                            "projects": [{"id": "p1", "name": "beethoven"}]})
        self._real = self.mod.db
        self.mod.db = self.fake
        self.addCleanup(setattr, self.mod, "db", self._real)

    def test_every_queued_task_is_scored(self):
        scored = self.mod._scored_queue(ctx={"revenue_by_project": {},
                                             "surface_returns": {},
                                             "outcome_stats": {},
                                             "approved_slugs": set()})
        self.assertEqual(len(scored), 1500,
                         "the whole queue must be scored; a 500-row window left ~907 "
                         "tasks invisible to EV ordering and parking")
        self.assertEqual(len({t["id"] for _, t in scored}), 1500,
                         "offset paging must not duplicate rows")

    def test_scan_is_deterministically_ordered(self):
        self.mod._scored_queue(ctx={"revenue_by_project": {}, "surface_returns": {},
                                    "outcome_stats": {}, "approved_slugs": set()})
        params = [p for tbl, p in self.fake.select_calls if tbl == "tasks"]
        self.assertTrue(params, "expected at least one tasks read")
        for p in params:
            self.assertIn("order", p,
                          "every paged read needs a deterministic order or offset paging "
                          "can repeat and skip rows between pages")
            self.assertTrue(p["order"].startswith("created_at.asc"),
                            f"oldest-first is the point: {p['order']}")

    def test_repeated_scans_are_reproducible(self):
        ctx = {"revenue_by_project": {}, "surface_returns": {},
               "outcome_stats": {}, "approved_slugs": set()}
        first = [t["id"] for _, t in self.mod._scored_queue(ctx=ctx)]
        second = [t["id"] for _, t in self.mod._scored_queue(ctx=ctx)]
        self.assertEqual(first, second)

    def test_coverage_reports_incomplete_scan(self):
        self.assertTrue(self.mod.scan_coverage(1500)["complete"])
        short = self.mod.scan_coverage(500)
        self.assertFalse(short["complete"])
        self.assertEqual(short["queue_depth"], 1500,
                         "a short scan must be reported against the TRUE depth")


class TestConfigOptimizerTrueQueueDepth(unittest.TestCase):
    """Case 2: queue depth is reported above 1,000, not clamped to the page cap."""

    def setUp(self):
        import config_optimizer
        self.mod = config_optimizer
        self.fake = FakeDb({"tasks": _queued(1407), "fleet_config": []})
        self._real = self.mod.db
        self.mod.db = self.fake
        self.addCleanup(setattr, self.mod, "db", self._real)

    def test_reports_depth_above_page_cap(self):
        os.environ["MAX_PARALLEL_CEILING"] = "4"
        suggestions = self.mod.suggest_config_changes()
        depth_reasons = [s["reason"] for s in suggestions if "Queue depth=" in s.get("reason", "")]
        self.assertTrue(depth_reasons, f"expected a queue-depth suggestion: {suggestions}")
        reported = int(depth_reasons[0].split("Queue depth=")[1].split(",")[0])
        self.assertEqual(reported, 1407,
                         "len() of a 1,000-row page made queue_depth structurally "
                         "incapable of exceeding 1,000; the autoscaler read that number")

    def test_depth_is_a_server_side_count_not_a_page(self):
        self.fake.rows["tasks"] = _queued(10000)
        self.assertEqual(self.fake.count("tasks", {"state": "eq.QUEUED"}), 10000)
        os.environ["MAX_PARALLEL_CEILING"] = "4"
        reason = [s["reason"] for s in self.mod.suggest_config_changes()
                  if "Queue depth=" in s.get("reason", "")][0]
        self.assertIn("Queue depth=10000", reason)


class TestLookupClassQuery(unittest.TestCase):
    """Case 3: a LOOKUP finds its target even with 10,000 newer rows present."""

    def setUp(self):
        newer = _queued(10000)
        self.target = {"id": "target-row", "slug": "the-one-we-want",
                       "project_id": "p1", "state": "QUEUED", "kind": "build",
                       "created_at": "2026-01-01T00:00:00Z"}
        self.fake = FakeDb({"tasks": [self.target] + newer})

    def test_scan_and_filter_client_side_misses_the_target(self):
        page = self.fake.select("tasks", {"select": "*", "state": "eq.QUEUED",
                                          "order": "created_at.desc", "limit": "3000"})
        self.assertEqual(len(page), FakeDb.HARD_PAGE_CAP,
                         "PostgREST caps the response at 1,000 — a bigger limit does not "
                         "widen the window, it only hides the truncation")
        self.assertNotIn("target-row", {r["id"] for r in page},
                         "this is the bug: the row exists and the scan cannot see it")

    def test_server_side_filter_finds_it(self):
        found = self.fake.select("tasks", {"select": "*", "slug": "eq.the-one-we-want"})
        self.assertEqual([r["id"] for r in found], ["target-row"])

    def test_full_scan_also_finds_it(self):
        every = self.fake._select_all("tasks", {"select": "*", "state": "eq.QUEUED"},
                                      order="created_at.asc,id.asc")
        self.assertEqual(len(every), 10001)
        self.assertIn("target-row", {r["id"] for r in every})


class TestDoneSlugsSeesEveryCompletion(unittest.TestCase):
    """The dependency-resolution cache must not be capped at one page.

    db._done_slugs() answers "is this task's dependency finished?" for every claim
    decision. It read `limit: "10000"`, which PostgREST served as 1,000. Measured on prod
    2026-08-06: 3,908 DONE/MERGED against 1,379 QUEUED (462 with deps), so ~74% of
    completions were invisible and satisfied deps were held as blocked.
    """

    def setUp(self):
        self.done = [{"id": f"d{i:05d}", "slug": f"finished-{i}", "project_id": "p1",
                      "state": "DONE"} for i in range(3908)]
        self.fake = FakeDb({"tasks": self.done,
                            "projects": [{"id": "p1", "name": "beethoven"}]})
        self._orig = {name: getattr(real_db, name)
                      for name in ("select", "select_all", "_done_cache")}
        real_db.select = self.fake.select
        real_db.select_all = self.fake.select_all
        real_db._done_cache = {"ts": 0.0, "ttl": 60, "slugs": set()}
        self.addCleanup(lambda: [setattr(real_db, k, v) for k, v in self._orig.items()])

    def test_all_done_slugs_are_visible(self):
        slugs = real_db._done_slugs()
        self.assertIn("finished-0", slugs)
        self.assertIn("finished-3907", slugs,
                      "a completion past the 1,000-row page cap must still resolve deps; "
                      "otherwise satisfied dependencies are held as blocked forever")
        bare = {s for s in slugs if not s.startswith("beethoven:")}
        self.assertEqual(len(bare), 3908,
                         f"expected every completion, cache held {len(bare)}")


class TestScanWindowLintRule(unittest.TestCase):
    """Cases 4 and 5: the lint rule flags the shape, and spares the sentinel."""

    def setUp(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "tools"))
        import convention_lint
        self.lint = convention_lint

    def _check(self, src):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(src)
            path = fh.name
        self.addCleanup(os.unlink, path)
        return [v for v in self.lint.check_file(path) if v.rule == "SCAN_WINDOW_NO_ORDER"]

    def test_flags_large_limit_without_order(self):
        found = self._check(
            'import db\n'
            'def f():\n'
            '    return db.select("tasks", {"select": "*", "state": "eq.QUEUED",\n'
            '                               "limit": "500"})\n')
        self.assertEqual(len(found), 1, "limit=500 with no order must be flagged")
        self.assertIn("db.select_all", found[0].message,
                      "the message must name the fix, not just the smell")

    def test_flags_str_wrapped_limit(self):
        self.assertEqual(len(self._check(
            'import db\n'
            'def f(n=800):\n'
            '    return db.select("tasks", {"select": "id", "limit": str(800)})\n')), 1)

    def test_passes_when_order_present(self):
        self.assertEqual(self._check(
            'import db\n'
            'def f():\n'
            '    return db.select("tasks", {"select": "*", "state": "eq.QUEUED",\n'
            '                               "order": "created_at.asc", "limit": "500"})\n'
        ), [])

    def test_passes_small_limit(self):
        self.assertEqual(self._check(
            'import db\n'
            'def f():\n'
            '    return db.select("tasks", {"select": "*", "limit": "1"})\n'), [])

    def test_passes_select_all(self):
        self.assertEqual(self._check(
            'import db\n'
            'def f():\n'
            '    return db.select_all("tasks", {"select": "*", "state": "eq.QUEUED"})\n'
        ), [])

    def test_does_not_flag_the_5001_sentinel(self):
        """Case 5: `limit: "5001"` answers "more than 5000?" — legitimate idiom."""
        self.assertEqual(self._check(
            'import db\n'
            'def f():\n'
            '    queued = len(db.select("tasks", {"select": "id", "state": "eq.QUEUED",\n'
            '                                     "limit": "5001"}) or [])\n'
            '    return queued\n'), [])

    def test_real_sentinel_site_is_clean(self):
        alarm = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "fleet_stuck_alarm.py")
        if not os.path.exists(alarm):
            self.skipTest("fleet_stuck_alarm.py not present")
        self.assertEqual(
            [v for v in self.lint.check_file(alarm) if v.rule == "SCAN_WINDOW_NO_ORDER"],
            [], "the documented 5001 sentinel must not be 'fixed' by the linter")

    def test_noqa_suppresses_the_rule(self):
        self.assertEqual(self._check(
            'import db\n'
            'def f():\n'
            '    return db.select("tasks", {"select": "*", "limit": "500"})  '
            '# noqa: SCAN_WINDOW_NO_ORDER\n'), [])


class TestFixedSitesStayFixed(unittest.TestCase):
    """Regression guard: the two live instances must not reacquire the shape."""

    def setUp(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "tools"))
        import convention_lint
        self.lint = convention_lint
        self.runner = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_ev_scheduler_and_config_optimizer_are_clean(self):
        for name in ("ev_scheduler.py", "config_optimizer.py"):
            path = os.path.join(self.runner, name)
            found = [v for v in self.lint.check_file(path)
                     if v.rule == "SCAN_WINDOW_NO_ORDER"]
            self.assertEqual(found, [], f"{name} reacquired an unordered scan window: "
                                        f"{[str(v) for v in found]}")

    def test_db_select_all_exists_and_pages(self):
        self.assertTrue(hasattr(real_db, "select_all"))
        self.assertTrue(hasattr(real_db, "count"))
        self.assertEqual(real_db.PAGE_SIZE, 1000,
                         "PAGE_SIZE must match the PostgREST response cap")


if __name__ == "__main__":
    unittest.main()
