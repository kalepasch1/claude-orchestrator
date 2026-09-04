"""Tests for route_consolidation."""
import os
import sys
import types
import unittest
from unittest.mock import patch


class _NoOpRouterStats(types.ModuleType):
    """Stand-in for the learned router so these tests exercise the pick() branch.

    router_stats.best_coder() reads a real stats table; with no data it returns None anyway,
    but pinning it to None here keeps the tests about routing PRECEDENCE rather than about
    whatever happens to be in fleet_config on this machine.
    """

    def __init__(self):
        super().__init__("router_stats")

    @staticmethod
    def best_coder(kind, available, stage=None):
        return None


_NoOpRouterStats = _NoOpRouterStats()


class TestRouteConsolidation(unittest.TestCase):
    def test_unified_route_fallback(self):
        from runner.route_consolidation import unified_route
        task = {"kind": "build", "slug": "test", "project_id": "p1"}
        coder, source = unified_route(task, ["claude", "deepseek"])
        self.assertIsNotNone(coder)
        self.assertIn(source, ("router_stats", "agentic_coders.pick", "bandit", "fallback"))

    def test_unified_route_empty_coders(self):
        from runner.route_consolidation import unified_route
        task = {"kind": "build", "slug": "test"}
        coder, source = unified_route(task, [])
        self.assertEqual(coder, "claude")
        self.assertEqual(source, "fallback")

    def test_routing_diagnosis_structure(self):
        from runner.route_consolidation import routing_diagnosis
        task = {"kind": "build", "slug": "test"}
        result = routing_diagnosis(task, ["claude"])
        self.assertIn("unified_pick", result)
        self.assertIn("agreement", result)

    def test_pick_is_called_with_its_real_signature(self):
        """agentic_coders.pick(task, slot_index=0) takes an INTEGER lane index second, not a
        candidate list.

        Regression: unified_route() called pick(task, available_coders), which handed a list
        to a parameter that indexes a lane. The pick was therefore never restricted to what
        the caller said was available, so this branch could route a task to an excluded coder
        and report it as a real routing verdict.
        """
        import runner.route_consolidation as rc
        seen = []

        class FakeCoders:
            @staticmethod
            def pick(task, slot_index=0):
                seen.append(slot_index)
                return "deepseek"

        with patch.dict(sys.modules, {"agentic_coders": FakeCoders,
                                      "router_stats": _NoOpRouterStats}):
            coder, source = rc.unified_route({"kind": "build", "slug": "t"},
                                             ["claude", "deepseek"])

        self.assertEqual(coder, "deepseek")
        self.assertEqual(source, "agentic_coders.pick")
        # pick() got its own default slot index — nothing was smuggled into that parameter.
        self.assertEqual(seen, [0])

    def test_pick_result_outside_the_available_set_is_not_returned(self):
        """The caller's availability list is a constraint, not a hint.

        pick() has no availability parameter to intersect with, so the restriction has to be
        applied to its answer. A coder the caller excluded must fall through to the remaining
        routers instead of being handed back.
        """
        import runner.route_consolidation as rc

        class FakeCoders:
            @staticmethod
            def pick(task, slot_index=0):
                return "gemini"          # not in the available list below

        with patch.dict(sys.modules, {"agentic_coders": FakeCoders,
                                      "router_stats": _NoOpRouterStats}):
            coder, source = rc.unified_route({"kind": "build", "slug": "t"},
                                             ["claude", "deepseek"])

        self.assertEqual(coder, "claude")
        self.assertEqual(source, "fallback")

    def test_no_available_coder_never_reports_a_router_verdict(self):
        """unified_route(task, []) must not launder pick()'s hardcoded default into a real
        routing decision — the caller has said nothing is available."""
        import runner.route_consolidation as rc

        class FakeCoders:
            @staticmethod
            def pick(task, slot_index=0):
                return "claude"          # pick()'s own default, with no pool to consult

        with patch.dict(sys.modules, {"agentic_coders": FakeCoders,
                                      "router_stats": _NoOpRouterStats}):
            coder, source = rc.unified_route({"kind": "build", "slug": "t"}, [])

        self.assertEqual(source, "fallback")

    def test_available_coder_from_pick_is_honoured(self):
        """Guard against overcorrecting: an available pick must still win over the fallback."""
        import runner.route_consolidation as rc

        class FakeCoders:
            @staticmethod
            def pick(task, slot_index=0):
                return "deepseek"

        with patch.dict(sys.modules, {"agentic_coders": FakeCoders,
                                      "router_stats": _NoOpRouterStats}):
            coder, source = rc.unified_route({"kind": "build", "slug": "t"},
                                             ["claude", "deepseek", "gemini"])

        self.assertEqual((coder, source), ("deepseek", "agentic_coders.pick"))

    def test_syntax(self):
        import os
        import py_compile
<<<<<<< HEAD
        # Derived from __file__, not a repo-root-relative literal: pytest runs
        # from runner/, so this failed on the invocation directory rather than
        # on the syntax it exists to check.
        target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "route_consolidation.py")
        py_compile.compile(target, doraise=True)
=======
        # Resolve relative to this test file so the check passes regardless of
        # pytest's working directory (CI runs the suite from runner/).
        py_compile.compile(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "route_consolidation.py"),
            doraise=True,
        )
>>>>>>> agent/improve-enhance-testing-framework-slice-4


if __name__ == "__main__":
    unittest.main()
