"""Tests for route_consolidation."""
import unittest


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

    def test_syntax(self):
        import py_compile
        py_compile.compile("runner/route_consolidation.py", doraise=True)


if __name__ == "__main__":
    unittest.main()
