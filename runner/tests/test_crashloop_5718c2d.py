"""
test_crashloop_5718c2d.py — the two crash loops in backlog-batch-beethoven-5718c2d.

Both jobs were "failing silently" in the sense that mattered: they raised the SAME
traceback every scheduled invocation and nothing downstream ever ran.

A) portfolio_autopilot — KeyError: 'id' at run(), 90% of that job's tracebacks.
   Root cause is not a missing guard, it is schema drift: the module was written against
   a data model that does not exist. Verified against the live schema:

     code                                          reality
     growth_apps.id                                no such column; key is `app` (text)
     growth_apps.name                              no such column; it is `display_name`
     growth_distribution_run.app_id                no such column; it is `app`
     growth_distribution_run.signups/human_hours   neither exists
     growth_intake_suggestion.app_id/app_name      neither exists; the column is `app`
     cold_start_app(p_app_id, p_count, p_mode)     actual: (p_app, p_n, p_mode)
     auto_tune_distribution(p_ceiling)             actual: (p_cac_ceiling)

   Only the first raised; every other mismatch was a 400 swallowed by a bare except into a
   default. So the job had never completed once, and would still have done nothing useful
   after a naive KeyError guard. These tests pin the real schema.

B) committees — urllib URLError [Errno 61] Connection refused escaping run(),
   81 tracebacks, 52% of that job's failures, followed by
   "periodic committees: WEDGED — skipped 3 consecutive invocation(s)" as the crashed
   holder kept the lock. process_determination_actions() had an unguarded db.select and is
   the FIRST statement in run(). A transient DB outage must cost one skipped cycle.

No network: db is faked.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_autopilot as pa


# The five enabled rows exactly as growth_apps really returns them: keyed on `app`,
# labelled by `display_name`, and with no `id` or `name` key anywhere.
REAL_APP_ROWS = [
    {"app": "tomorrow", "display_name": "Tomorrow", "tier": "spearhead",
     "stage": "prelaunch", "enabled": True, "meta": {}},
    {"app": "apparently", "display_name": "Apparently", "tier": "spearhead",
     "stage": "live", "enabled": True, "meta": {}},
    {"app": "smarter", "display_name": "Smarter", "tier": "cluster",
     "stage": "prelaunch", "enabled": True, "meta": {}},
]


class FakeDb:
    """Rejects any column or RPC parameter the live schema does not have.

    This is the point of the fixture. A permissive fake would let the original code pass,
    because the original code's failure mode was asking for columns that do not exist.
    """

    COLUMNS = {
        "growth_apps": {"app", "display_name", "tier", "cluster", "stage", "audience",
                        "north_star", "monetization", "enabled", "meta",
                        "created_at", "updated_at"},
        "growth_distribution_run": {"id", "play_id", "app", "mode", "status",
                                    "outcome_score", "metrics", "created_at"},
        "growth_distribution_metric": {"id", "run_id", "app", "channel", "day", "reach",
                                       "clicks", "signups", "cost_usd", "created_at"},
        "growth_distribution_play": {"id", "play_id", "slug", "name", "human_minutes",
                                     "human_steps", "agent_steps", "status", "score",
                                     "channel", "objective", "cost_usd", "cycle_days",
                                     "expected_reach", "half_life_days", "meta",
                                     "app_scope", "created_at"},
        "growth_intake_suggestion": {"id", "app", "kind", "severity", "detail", "ref",
                                     "status", "created_at"},
        "growth_settings": {"key", "value"},
    }

    RPC_ARGS = {
        "cold_start_app": {"p_app", "p_n", "p_mode"},
        "auto_tune_distribution": {"p_cac_ceiling"},
        "score_distribution_runs": set(),
        "compute_relationship_strength": set(),
    }

    RESERVED = {"select", "limit", "offset", "order", "and", "or"}

    def __init__(self, rows=None):
        self.rows = rows or {}
        self.inserts = []
        self.rpc_calls = []

    def _validate(self, table, params):
        known = self.COLUMNS.get(table)
        if known is None:
            raise RuntimeError(f"HTTP 404: relation '{table}' does not exist")
        asked = set()
        for key, val in (params or {}).items():
            if key in self.RESERVED:
                if key == "select":
                    asked |= {c.strip() for c in str(val).split(",") if c.strip() != "*"}
                continue
            asked.add(key)
        unknown = {c for c in asked if c not in known}
        if unknown:
            raise RuntimeError(
                f"HTTP 400: column {sorted(unknown)} does not exist on {table}")

    def select(self, table, params=None):
        self._validate(table, params)
        return list(self.rows.get(table, []))

    def insert(self, table, row):
        self._validate(table, {k: v for k, v in row.items()})
        self.inserts.append((table, row))
        return [row]

    def rpc(self, name, args=None):
        if name not in self.RPC_ARGS:
            raise RuntimeError(f"HTTP 404: function {name} does not exist")
        expected, got = self.RPC_ARGS[name], set((args or {}).keys())
        if got - expected:
            raise RuntimeError(
                f"HTTP 404: {name} has no parameter(s) {sorted(got - expected)}; "
                f"expected {sorted(expected)}")
        self.rpc_calls.append((name, dict(args or {})))
        return {"ok": True}


class TestPortfolioAutopilotCrashLoop(unittest.TestCase):

    def setUp(self):
        os.environ["ORCH_PORTFOLIO_AUTOPILOT_ENABLED"] = "true"
        pa.ENABLED = True
        self.fake = FakeDb({
            "growth_apps": REAL_APP_ROWS,
            "growth_settings": [{"key": "distribution_cac_ceiling", "value": "100"}],
            "growth_distribution_run": [],
            "growth_distribution_metric": [],
            "growth_distribution_play": [],
        })
        self._real = pa.db
        pa.db = self.fake
        self.addCleanup(setattr, pa, "db", self._real)

    def test_run_does_not_raise_keyerror(self):
        """The crash loop itself: KeyError 'id' on the first enabled row."""
        summary = pa.run()
        self.assertEqual(summary["apps"], 3)
        self.assertNotIn("error", summary)

    def test_app_key_uses_the_real_column(self):
        self.assertEqual(pa._app_key(REAL_APP_ROWS[0]), "tomorrow")
        self.assertEqual(pa._app_label(REAL_APP_ROWS[0]), "Tomorrow")

    def test_app_key_is_total(self):
        """Never raise on a malformed row — that is what took the job down."""
        for bad in ({}, None, {"display_name": "no key"}, "not-a-dict", 42):
            self.assertEqual(pa._app_key(bad), "")
        self.assertEqual(pa._app_label({}), "unknown")

    def test_active_run_count_filters_on_app_not_app_id(self):
        """app_id returned 400, swallowed to -1, so cold-start could never fire."""
        self.assertEqual(pa._active_run_count("tomorrow"), 0)   # would raise on app_id

    def test_cold_start_fires_and_uses_the_real_rpc_signature(self):
        pa.run()
        cold = [c for c in self.fake.rpc_calls if c[0] == "cold_start_app"]
        self.assertEqual(len(cold), 3, "every app has zero active runs -> all cold-start")
        self.assertEqual(cold[0][1], {"p_app": "tomorrow", "p_n": 3, "p_mode": "approval"})

    def test_auto_tune_uses_p_cac_ceiling(self):
        pa.run()
        tune = [c for c in self.fake.rpc_calls if c[0] == "auto_tune_distribution"]
        self.assertEqual(tune[0][1], {"p_cac_ceiling": 100.0},
                         "p_ceiling is not a parameter of auto_tune_distribution")

    def test_digest_insert_uses_the_real_columns(self):
        pa.run()
        digests = [r for t, r in self.fake.inserts if t == "growth_intake_suggestion"]
        self.assertEqual(len(digests), 3, "every insert previously 400'd and was swallowed")
        self.assertIn("app", digests[0])
        self.assertNotIn("app_id", digests[0])
        self.assertNotIn("app_name", digests[0])
        self.assertEqual({d["app"] for d in digests},
                         {"tomorrow", "apparently", "smarter"})

    def test_unknown_ratio_does_not_raise_a_false_alarm(self):
        """sphr None (no data) must not be reported as 0 signups needing attention."""
        pa.run()
        digests = [r for t, r in self.fake.inserts if t == "growth_intake_suggestion"]
        for d in digests:
            self.assertEqual(d["severity"], "low")
            self.assertIn("unknown", d["detail"])
            self.assertNotIn("FLAG: 0 signups", d["detail"])

    def test_real_zero_signups_still_escalates(self):
        """A genuine 0 against real human effort must still be high severity."""
        self.fake.rows["growth_distribution_run"] = [
            {"id": "r1", "play_id": "p1", "app": "tomorrow", "status": "active"}]
        self.fake.rows["growth_distribution_play"] = [
            {"id": "p1", "human_minutes": 120}]
        self.fake.rows["growth_distribution_metric"] = [{"signups": 0}]
        self.assertEqual(pa._signups_per_human_hour(REAL_APP_ROWS[0]), 0.0)

    def test_signups_per_human_hour_computes_the_real_ratio(self):
        self.fake.rows["growth_distribution_run"] = [
            {"id": "r1", "play_id": "p1", "app": "tomorrow", "status": "active"}]
        self.fake.rows["growth_distribution_play"] = [
            {"id": "p1", "human_minutes": 30}]          # 0.5h
        self.fake.rows["growth_distribution_metric"] = [{"signups": 6}]
        self.assertEqual(pa._signups_per_human_hour(REAL_APP_ROWS[0]), 12.0)

    def test_no_active_runs_is_unknown_not_zero(self):
        self.assertIsNone(pa._signups_per_human_hour(REAL_APP_ROWS[0]))

    def test_stats_does_not_raise(self):
        self.assertEqual(sorted(pa.stats()["zero_run_apps"]),
                         ["Apparently", "Smarter", "Tomorrow"])


class TestCommitteesDbOutageIsNotACrashLoop(unittest.TestCase):
    """A transient DB outage must cost one skipped cycle, not a traceback every 30 min."""

    class DeadDb:
        def __init__(self):
            self.calls = 0

        def select(self, *a, **k):
            self.calls += 1
            raise OSError("[Errno 61] Connection refused")

        def __getattr__(self, _name):
            def _boom(*a, **k):
                raise OSError("[Errno 61] Connection refused")
            return _boom

    def setUp(self):
        import committees
        self.mod = committees
        self.dead = self.DeadDb()
        self._real = committees.db
        committees.db = self.dead
        self.addCleanup(setattr, committees, "db", self._real)

    def test_action_drain_is_fail_soft(self):
        self.assertEqual(self.mod.process_determination_actions(), 0)
        self.assertGreater(self.dead.calls, 0, "it must actually have tried the read")

    def test_run_skips_instead_of_raising(self):
        result = self.mod.run()
        self.assertEqual(result.get("skipped"), "db_unavailable")
        self.assertIn("Connection refused", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
