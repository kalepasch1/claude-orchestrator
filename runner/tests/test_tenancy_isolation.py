#!/usr/bin/env python3
"""Execution isolation between tenants.

The prompt's hard requirement is that a task in tenant A cannot reach tenant B's
repo, bindings or knowledge store. These tests are the proof, and they are
written adversarially rather than happily: the interesting cases are the ones
where a string compare would say "same path" and reality says otherwise —
symlinks, `..` segments, trailing slashes, `~`.

They also pin the two rules that are easiest to erode later:

  1. `assert_repo_access` DENIES when it cannot tell. Fail-soft is right for
     reads and wrong for a guard; a guard that returns allowed on error is not
     a guard.
  2. The founding tenant keeps its EXISTING knowledge path, so introducing
     tenancy moves nothing the current portfolio has already learned.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tenancy  # noqa: E402


class TenancyTestBase(unittest.TestCase):
    """Two tenants with one real directory each, wired without a database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.repo_a = os.path.join(root, "tenant-a-repo")
        self.repo_b = os.path.join(root, "tenant-b-repo")
        os.makedirs(self.repo_a)
        os.makedirs(self.repo_b)

        tenancy.invalidate()
        # Inject bindings directly: these tests are about the guard, not the loader.
        tenancy._registry._by_tenant = {  # noqa: SLF001 — deliberate test seam
            "tenant-a": [{"tenant_id": "tenant-a", "app": "alpha", "repo_path": self.repo_a,
                          "github_repo": "org/alpha", "branch": "main"}],
            "tenant-b": [{"tenant_id": "tenant-b", "app": "beta", "repo_path": self.repo_b,
                          "github_repo": "org/beta", "branch": "main"}],
        }
        tenancy._registry._loaded = True  # noqa: SLF001

    def tearDown(self):
        tenancy.invalidate()
        self.tmp.cleanup()


class CrossTenantRepoAccessTest(TenancyTestBase):
    """A task in tenant A must not be able to reference tenant B's repo."""

    def test_own_repo_is_allowed(self):
        self.assertTrue(tenancy.assert_repo_access("tenant-a", self.repo_a)["allowed"])

    def test_other_tenants_repo_is_denied(self):
        verdict = tenancy.assert_repo_access("tenant-a", self.repo_b)
        self.assertFalse(verdict["allowed"])
        self.assertIn("tenant-b", verdict["reason"])

    def test_denial_is_symmetric(self):
        self.assertFalse(tenancy.assert_repo_access("tenant-b", self.repo_a)["allowed"])

    def test_unclaimed_path_is_denied_not_allowed(self):
        # An unknown path is unknown, and unknown is not permission.
        stray = os.path.join(self.tmp.name, "not-a-binding")
        os.makedirs(stray)
        verdict = tenancy.assert_repo_access("tenant-a", stray)
        self.assertFalse(verdict["allowed"])
        self.assertIn("no deployment binding", verdict["reason"])

    def test_unknown_tenant_gets_nothing(self):
        self.assertFalse(tenancy.assert_repo_access("tenant-zzz", self.repo_a)["allowed"])


class PathSmugglingTest(TenancyTestBase):
    """The ways a plain string compare gets this wrong."""

    def test_symlink_into_another_tenant_is_denied(self):
        link = os.path.join(self.tmp.name, "tenant-a-repo-link")
        os.symlink(self.repo_b, link)
        # The link SITS in tenant A's naming space but RESOLVES to tenant B.
        verdict = tenancy.assert_repo_access("tenant-a", link)
        self.assertFalse(verdict["allowed"], "symlink resolved past the tenant boundary")

    def test_dotdot_traversal_is_denied(self):
        sneaky = os.path.join(self.repo_a, "..", "tenant-b-repo")
        self.assertFalse(tenancy.assert_repo_access("tenant-a", sneaky)["allowed"])

    def test_trailing_slash_still_matches_own_repo(self):
        self.assertTrue(tenancy.assert_repo_access("tenant-a", self.repo_a + "/")["allowed"])

    def test_tilde_expansion_does_not_crash_or_allow(self):
        self.assertFalse(tenancy.assert_repo_access("tenant-a", "~/definitely-not-a-binding")["allowed"])


class BadInputTest(TenancyTestBase):
    """Bad input denies; it does not raise, and it does not allow."""

    def test_none_and_empty_deny(self):
        for bad in (None, "", "   "):
            with self.subTest(bad=repr(bad)):
                self.assertFalse(tenancy.assert_repo_access("tenant-a", bad)["allowed"])

    def test_non_string_denies(self):
        for bad in (0, 1, [], {}, object()):
            with self.subTest(bad=type(bad).__name__):
                self.assertFalse(tenancy.assert_repo_access("tenant-a", bad)["allowed"])

    def test_reason_is_always_present_on_denial(self):
        verdict = tenancy.assert_repo_access("tenant-a", self.repo_b)
        self.assertTrue(verdict["reason"], "a denial with no reason is unactionable")


class BindingScopeTest(TenancyTestBase):
    """Bindings and app resolution are tenant-scoped, not global."""

    def test_bindings_are_scoped(self):
        a_paths = [r["repo_path"] for r in tenancy.bindings_for("tenant-a")]
        self.assertEqual(a_paths, [self.repo_a])
        self.assertNotIn(self.repo_b, a_paths)

    def test_resolve_repo_does_not_cross_tenants(self):
        # 'beta' exists — in the other tenant. Tenant A must not resolve it.
        self.assertIsNone(tenancy.resolve_repo("tenant-a", "beta"))
        self.assertIsNotNone(tenancy.resolve_repo("tenant-b", "beta"))

    def test_resolve_repo_handles_missing_app(self):
        self.assertIsNone(tenancy.resolve_repo("tenant-a", None))
        self.assertIsNone(tenancy.resolve_repo("tenant-a", "nonexistent"))

    def test_tenant_of_repo(self):
        self.assertEqual(tenancy.tenant_of_repo(self.repo_a), "tenant-a")
        self.assertEqual(tenancy.tenant_of_repo(self.repo_b), "tenant-b")
        self.assertIsNone(tenancy.tenant_of_repo("/nowhere/at/all"))


class TaskScopeTest(TenancyTestBase):
    """Task dicts route through the same gate, and untenanted tasks are founding."""

    def test_task_with_tenant(self):
        self.assertFalse(
            tenancy.assert_task_repo_access({"tenant_id": "tenant-a"}, self.repo_b)["allowed"])
        self.assertTrue(
            tenancy.assert_task_repo_access({"tenant_id": "tenant-a"}, self.repo_a)["allowed"])

    def test_task_without_tenant_is_founding_not_wildcard(self):
        # The existing fleet's tasks carry no tenant. They must become FOUNDING,
        # not "any tenant" — otherwise tenancy is decorative.
        verdict = tenancy.assert_task_repo_access({}, self.repo_a)
        self.assertFalse(verdict["allowed"])
        self.assertIn(tenancy.FOUNDING_TENANT, verdict["reason"])

    def test_none_task_is_handled(self):
        self.assertFalse(tenancy.assert_task_repo_access(None, self.repo_a)["allowed"])


class KnowledgeIsolationTest(unittest.TestCase):
    """Knowledge stores never cross tenants, and the founding one never moves."""

    def test_founding_keeps_the_existing_path(self):
        home = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
        self.assertEqual(tenancy.knowledge_root(), os.path.join(home, "knowledge"))
        self.assertEqual(tenancy.knowledge_root(tenancy.FOUNDING_TENANT),
                         os.path.join(home, "knowledge"))

    def test_other_tenants_are_nested_and_distinct(self):
        a = tenancy.knowledge_root("tenant-a")
        b = tenancy.knowledge_root("tenant-b")
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, tenancy.knowledge_root())
        self.assertTrue(a.endswith(os.path.join("tenants", "tenant-a")))

    def test_no_tenant_root_is_a_prefix_of_another(self):
        # 'a' must not sit inside 'ab': a prefix relationship makes a recursive
        # read from one tenant walk into the other.
        a = tenancy.knowledge_root("a")
        ab = tenancy.knowledge_root("ab")
        self.assertFalse(ab.startswith(a + os.sep))


class SeedFallbackTest(unittest.TestCase):
    """The on-disk manifest still resolves the founding portfolio."""

    def setUp(self):
        tenancy.invalidate()

    def tearDown(self):
        tenancy.invalidate()

    def test_seed_loads_founding_bindings(self):
        rows = tenancy.bindings_for(tenancy.FOUNDING_TENANT)
        self.assertGreater(len(rows), 0, "founding tenant lost its bindings")
        for r in rows:
            self.assertTrue(r.get("repo_path"))
            self.assertEqual(r.get("tenant_id"), tenancy.FOUNDING_TENANT)

    def test_existing_portfolio_still_resolves(self):
        # No-regression check: a repo the fleet uses today must still be
        # reachable by the founding tenant after tenancy lands.
        rows = tenancy.bindings_for(tenancy.FOUNDING_TENANT)
        apps = {r.get("app") for r in rows}
        self.assertIn("beethoven", apps)
        binding = tenancy.resolve_repo(tenancy.FOUNDING_TENANT, "beethoven")
        self.assertIsNotNone(binding)
        self.assertTrue(tenancy.assert_repo_access(
            tenancy.FOUNDING_TENANT, binding["repo_path"])["allowed"])

    def test_stats_and_invalidate(self):
        s = tenancy.stats()
        self.assertGreaterEqual(s["bindings"], 1)
        tenancy.invalidate()
        self.assertGreaterEqual(tenancy.stats()["bindings"], 1)  # reloads


if __name__ == "__main__":
    unittest.main()
