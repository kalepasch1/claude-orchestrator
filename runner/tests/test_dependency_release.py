#!/usr/bin/env python3
"""Tests for dependency_release.py — DAG-based release ordering."""
import json, os, sys, tempfile, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dependency_release


class TestCheckDependencies(unittest.TestCase):
    """Dependency checking from package.json and requirements.txt."""

    def test_package_json(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = {
                "dependencies": {"react": "^18.2.0", "lodash": "4.17.21"},
                "devDependencies": {"jest": "^29.0.0"},
            }
            with open(os.path.join(d, "package.json"), "w") as f:
                json.dump(pkg, f)
            deps = dependency_release.check_dependencies(d)
            self.assertEqual(deps["react"], "^18.2.0")
            self.assertEqual(deps["lodash"], "4.17.21")
            self.assertEqual(deps["jest"], "^29.0.0")

    def test_requirements_txt(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "requirements.txt"), "w") as f:
                f.write("flask==2.3.0\nrequests>=2.28\n# comment\nnumpy\n")
            deps = dependency_release.check_dependencies(d)
            self.assertEqual(deps["flask"], "==2.3.0")
            self.assertEqual(deps["requests"], ">=2.28")
            self.assertEqual(deps["numpy"], "*")

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            deps = dependency_release.check_dependencies(d)
            self.assertEqual(deps, {})

    def test_disabled(self):
        with patch.object(dependency_release, "ENABLED", False):
            deps = dependency_release.check_dependencies("/nonexistent")
            self.assertEqual(deps, {})

    def test_stats_incremented(self):
        with tempfile.TemporaryDirectory() as d:
            before = dependency_release.stats()["dependencies_checked"]
            dependency_release.check_dependencies(d)
            after = dependency_release.stats()["dependencies_checked"]
            self.assertEqual(after, before + 1)


class TestValidateReleaseOrder(unittest.TestCase):
    """Release order validation."""

    def test_correct_order_passes(self):
        releases = [
            {"name": "core", "version": "2.0.0", "breaking": True, "depends_on": []},
            {"name": "api", "version": "1.1.0", "breaking": False, "depends_on": ["core"]},
            {"name": "web", "version": "3.0.0", "breaking": False, "depends_on": ["api", "core"]},
        ]
        result = dependency_release.validate_release_order(releases)
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_wrong_order_fails(self):
        releases = [
            {"name": "web", "version": "3.0.0", "breaking": False, "depends_on": ["api"]},
            {"name": "api", "version": "1.1.0", "breaking": False, "depends_on": []},
        ]
        result = dependency_release.validate_release_order(releases)
        self.assertFalse(result["valid"])
        self.assertTrue(len(result["errors"]) > 0)
        self.assertIn("api", result["errors"][0])

    def test_no_deps_always_valid(self):
        releases = [
            {"name": "standalone", "version": "1.0.0", "breaking": False, "depends_on": []},
        ]
        result = dependency_release.validate_release_order(releases)
        self.assertTrue(result["valid"])

    def test_disabled(self):
        with patch.object(dependency_release, "ENABLED", False):
            result = dependency_release.validate_release_order([])
            self.assertTrue(result["valid"])


class TestBuildReleaseGraph(unittest.TestCase):
    """Graph building with circular dependency detection."""

    def test_simple_graph(self):
        tasks = [
            {"name": "core", "depends_on": []},
            {"name": "api", "depends_on": ["core"]},
            {"name": "web", "depends_on": ["api", "core"]},
        ]
        graph = dependency_release.build_release_graph(tasks)
        self.assertEqual(graph["core"], set())
        self.assertEqual(graph["api"], {"core"})
        self.assertEqual(graph["web"], {"api", "core"})

    def test_circular_dependency_detected(self):
        tasks = [
            {"name": "a", "depends_on": ["b"]},
            {"name": "b", "depends_on": ["a"]},
        ]
        with self.assertRaises(dependency_release.CyclicDependencyError):
            dependency_release.build_release_graph(tasks)

    def test_self_cycle(self):
        tasks = [{"name": "x", "depends_on": ["x"]}]
        with self.assertRaises(dependency_release.CyclicDependencyError):
            dependency_release.build_release_graph(tasks)

    def test_disabled(self):
        with patch.object(dependency_release, "ENABLED", False):
            graph = dependency_release.build_release_graph([{"name": "a", "depends_on": []}])
            self.assertEqual(graph, {})


class TestSafeReleaseSequence(unittest.TestCase):
    """Topological sort produces valid sequence."""

    def test_linear_chain(self):
        graph = {"core": set(), "api": {"core"}, "web": {"api"}}
        seq = dependency_release.safe_release_sequence(graph)
        self.assertEqual(seq, ["core", "api", "web"])

    def test_diamond_dependency(self):
        graph = {
            "base": set(),
            "left": {"base"},
            "right": {"base"},
            "top": {"left", "right"},
        }
        seq = dependency_release.safe_release_sequence(graph)
        self.assertEqual(seq[0], "base")
        self.assertEqual(seq[-1], "top")
        self.assertIn("left", seq)
        self.assertIn("right", seq)
        # Both left and right must come after base and before top
        self.assertGreater(seq.index("left"), seq.index("base"))
        self.assertGreater(seq.index("right"), seq.index("base"))
        self.assertLess(seq.index("left"), seq.index("top"))
        self.assertLess(seq.index("right"), seq.index("top"))

    def test_empty_graph(self):
        seq = dependency_release.safe_release_sequence({})
        self.assertEqual(seq, [])

    def test_single_node(self):
        seq = dependency_release.safe_release_sequence({"solo": set()})
        self.assertEqual(seq, ["solo"])

    def test_disabled(self):
        with patch.object(dependency_release, "ENABLED", False):
            seq = dependency_release.safe_release_sequence({"a": set()})
            self.assertEqual(seq, [])


class TestStats(unittest.TestCase):
    """Stats output."""

    def test_stats_returns_dict(self):
        s = dependency_release.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("dependencies_checked", s)
        self.assertIn("graphs_built", s)
        self.assertIn("sequences_computed", s)
        self.assertIn("circular_deps_detected", s)
        self.assertIn("validation_failures", s)
        self.assertIn("releases_validated", s)

    def test_stats_returns_copy(self):
        s1 = dependency_release.stats()
        s1["dependencies_checked"] = -999
        s2 = dependency_release.stats()
        self.assertNotEqual(s2["dependencies_checked"], -999)


if __name__ == "__main__":
    unittest.main()
