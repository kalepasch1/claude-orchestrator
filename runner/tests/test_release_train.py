#!/usr/bin/env python3
"""Tests for release_train.py — dependency-aware release orchestration."""
import json, os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from release_train import _prepare_generated_types, sequence_releases, CyclicDependencyError


class TestLinearChain(unittest.TestCase):
    """A -> B -> C: C must deploy before B, B before A."""

    def test_all_changed(self):
        graph = {"A": ["B"], "B": ["C"], "C": []}
        order = sequence_releases(graph, {"A", "B", "C"})
        self.assertEqual(order, ["C", "B", "A"])

    def test_only_leaf_changed(self):
        graph = {"A": ["B"], "B": ["C"], "C": []}
        order = sequence_releases(graph, {"C"})
        self.assertEqual(order, ["C"])

    def test_middle_and_root_changed(self):
        graph = {"A": ["B"], "B": ["C"], "C": []}
        order = sequence_releases(graph, {"A", "B"})
        self.assertEqual(order, ["B", "A"])


class TestDiamondDependency(unittest.TestCase):
    """Diamond: D depends on B and C, both depend on A."""

    def test_full_diamond(self):
        graph = {"D": ["B", "C"], "B": ["A"], "C": ["A"], "A": []}
        order = sequence_releases(graph, {"A", "B", "C", "D"})
        self.assertEqual(order.index("A"), 0)
        self.assertLess(order.index("B"), order.index("D"))
        self.assertLess(order.index("C"), order.index("D"))

    def test_partial_diamond(self):
        graph = {"D": ["B", "C"], "B": ["A"], "C": ["A"], "A": []}
        order = sequence_releases(graph, {"B", "D"})
        self.assertLess(order.index("B"), order.index("D"))
        self.assertNotIn("A", order)
        self.assertNotIn("C", order)


class TestCycleDetection(unittest.TestCase):
    def test_simple_cycle(self):
        graph = {"A": ["B"], "B": ["A"]}
        with self.assertRaises(CyclicDependencyError):
            sequence_releases(graph, {"A", "B"})

    def test_three_node_cycle(self):
        graph = {"A": ["B"], "B": ["C"], "C": ["A"]}
        with self.assertRaises(CyclicDependencyError):
            sequence_releases(graph, {"A"})

    def test_cycle_among_unchanged_still_errors(self):
        graph = {"A": ["B"], "B": ["A"], "C": []}
        with self.assertRaises(CyclicDependencyError):
            sequence_releases(graph, {"C"})


class TestIndependentApps(unittest.TestCase):
    def test_no_dependencies(self):
        graph = {"X": [], "Y": [], "Z": []}
        order = sequence_releases(graph, {"X", "Y", "Z"})
        self.assertEqual(sorted(order), ["X", "Y", "Z"])
        self.assertEqual(len(order), 3)

    def test_subset_independent(self):
        graph = {"X": [], "Y": [], "Z": []}
        order = sequence_releases(graph, {"Y"})
        self.assertEqual(order, ["Y"])


class TestSingleApp(unittest.TestCase):
    def test_single_app_no_graph(self):
        order = sequence_releases({}, {"solo"})
        self.assertEqual(order, ["solo"])

    def test_single_app_in_graph(self):
        graph = {"solo": []}
        order = sequence_releases(graph, {"solo"})
        self.assertEqual(order, ["solo"])


class TestEmptyInput(unittest.TestCase):
    def test_no_changed_apps(self):
        graph = {"A": ["B"], "B": []}
        order = sequence_releases(graph, set())
        self.assertEqual(order, [])

    def test_empty_graph_empty_changes(self):
        order = sequence_releases({}, set())
        self.assertEqual(order, [])


class TestImplicitDependencies(unittest.TestCase):
    """Dependencies referenced in the graph but not defined as keys."""

    def test_dependency_not_in_graph_keys(self):
        # "lib" is referenced but not a key — treated as having no deps
        graph = {"app": ["lib"]}
        order = sequence_releases(graph, {"app", "lib"})
        self.assertLess(order.index("lib"), order.index("app"))


class TestReleaseSnapshotOrdering(unittest.TestCase):
    def test_refresh_precedes_gates_and_snapshot_guard_precedes_push(self):
        path = os.path.join(os.path.dirname(__file__), "..", "release_train.py")
        with open(path, encoding="utf-8") as source:
            text = source.read()

        refresh = text.index("refreshed, refresh_note = _refresh_staging_with_prod")
        qa_gate = text.index("# QA staging tests")
        snapshot_guard = text.index("current_staging_sha != staging_sha")
        exact_push = text.index('f"{staging_sha}:refs/heads/{prod}"')
        self.assertLess(refresh, qa_gate)
        self.assertLess(snapshot_guard, exact_push)

    def test_verified_sha_is_the_release_sha(self):
        path = os.path.join(os.path.dirname(__file__), "..", "release_train.py")
        with open(path, encoding="utf-8") as source:
            text = source.read()
        self.assertIn("to_sha = staging_sha", text)
        self.assertIn('"snapshot": "CHANGED"', text)


class TestGeneratedTypePreparation(unittest.TestCase):
    def test_prepares_nested_nuxt_package_root(self):
        with tempfile.TemporaryDirectory() as repo:
            web = os.path.join(repo, "web")
            os.makedirs(web)
            with open(os.path.join(web, "package.json"), "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"nuxt": "3.0.0"}}, f)
            with open(os.path.join(web, "tsconfig.json"), "w", encoding="utf-8") as f:
                json.dump({"extends": "./.nuxt/tsconfig.json"}, f)

            def prepare(_cmd, cwd, **_kwargs):
                generated = os.path.join(cwd, ".nuxt")
                os.makedirs(generated)
                with open(os.path.join(generated, "tsconfig.json"), "w", encoding="utf-8") as f:
                    f.write("{}")
                return type("Result", (), {"returncode": 0, "stdout": "prepared", "stderr": ""})()

            with mock.patch("dependency_prewarm.package_roots", return_value=[web]), \
                    mock.patch("release_train.subprocess.run", side_effect=prepare) as run:
                ok, log = _prepare_generated_types(repo)

            self.assertTrue(ok, log)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs["cwd"], web)


if __name__ == "__main__":
    unittest.main()
