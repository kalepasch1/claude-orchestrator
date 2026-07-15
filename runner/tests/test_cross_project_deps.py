#!/usr/bin/env python3
"""Tests for cross-project dependency resolution (project:slug format)."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestParseDepRef(unittest.TestCase):
    """db.parse_dep_ref correctly splits bare and qualified dep references."""

    def test_bare_slug(self):
        from db import parse_dep_ref
        project, slug = parse_dep_ref("my-task-slug")
        self.assertIsNone(project)
        self.assertEqual(slug, "my-task-slug")

    def test_qualified_slug(self):
        from db import parse_dep_ref
        project, slug = parse_dep_ref("apparently:curation-layer-land")
        self.assertEqual(project, "apparently")
        self.assertEqual(slug, "curation-layer-land")

    def test_colon_in_slug_only_first_split(self):
        from db import parse_dep_ref
        project, slug = parse_dep_ref("proj:task:extra")
        self.assertEqual(project, "proj")
        self.assertEqual(slug, "task:extra")

    def test_empty_string(self):
        from db import parse_dep_ref
        project, slug = parse_dep_ref("")
        self.assertIsNone(project)
        self.assertEqual(slug, "")


class TestDepsSatisfied(unittest.TestCase):
    """db.deps_satisfied handles both bare and cross-project deps."""

    def test_empty_deps(self):
        from db import deps_satisfied
        self.assertTrue(deps_satisfied([]))
        self.assertTrue(deps_satisfied(None))

    def test_bare_deps_all_done(self):
        from db import deps_satisfied
        done = {"contracts", "setup-db"}
        self.assertTrue(deps_satisfied(["contracts", "setup-db"], done))

    def test_bare_deps_missing(self):
        from db import deps_satisfied
        done = {"contracts"}
        self.assertFalse(deps_satisfied(["contracts", "setup-db"], done))

    def test_cross_project_dep_satisfied(self):
        from db import deps_satisfied
        done = {"contracts", "apparently:curation-layer-land"}
        self.assertTrue(deps_satisfied(["contracts", "apparently:curation-layer-land"], done))

    def test_cross_project_dep_missing(self):
        from db import deps_satisfied
        done = {"contracts", "curation-layer-land"}  # bare slug present but not qualified
        self.assertFalse(deps_satisfied(["contracts", "apparently:curation-layer-land"], done))

    def test_mixed_deps(self):
        from db import deps_satisfied
        done = {"contracts", "apparently:curation-layer-land", "build-ui"}
        self.assertTrue(deps_satisfied(["contracts", "apparently:curation-layer-land", "build-ui"], done))

    def test_bare_slug_matches_without_project_qualifier(self):
        """Bare dep 'foo' matches bare entry 'foo' in done set (backward compat)."""
        from db import deps_satisfied
        done = {"foo", "myproject:foo"}
        self.assertTrue(deps_satisfied(["foo"], done))


if __name__ == "__main__":
    unittest.main()
