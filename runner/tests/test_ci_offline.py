"""The guards that hold this fleet together, tested with NO network and NO credentials.

WHY A SEPARATE FILE
-------------------
There are 611 test_*.py files under runner/ and nothing in CI has ever run any of them
(.github/workflows/ci.yml covered packages/darwin-kernel only). That is how 22 tests in
test_economic_scheduler*.py stayed red long enough for their contract to drift out from under
them without anyone noticing.

Turning all 611 on at once is not available: most need SUPABASE_URL + SUPABASE_SERVICE_KEY, and
an unknown number are red today. A CI job that is red on arrival teaches people to ignore CI.

So this file is the blocking beachhead — every check here is pure logic over fixtures, runs in
seconds on a bare container, and covers the guards whose failure modes actually cost days this
month: dirt classification, dangling imports, canonical-mutation detection, and the legacy
kill-switch clamp. The rest of the suite gets fixed and folded in behind it.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRegenerableArtifacts(unittest.TestCase):
    """A merge refuses to run against a dirty checkout. Getting 'dirty' wrong in one direction
    destroys uncommitted work; getting it wrong in the other deadlocked the train for five
    hours on 2026-08-05 (24 merges/hour -> 0, for five straight hours)."""

    def setUp(self):
        import regenerable_artifacts
        self.ra = regenerable_artifacts

    def test_real_source_edit_blocks(self):
        blocking, _ = self.ra.partition_dirt(" M lib/commerce/coppa.ts")
        self.assertEqual(len(blocking), 1)

    def test_lockfile_blocks(self):
        # A lockfile diff changes what ships. Never exempt.
        self.assertTrue(self.ra.partition_dirt(" M package-lock.json")[0])

    def test_fleet_artifacts_are_regenerable(self):
        blocking, regen = self.ra.partition_dirt(" M .runner_boot_commit\n M reports/cost_intelligence_internal.md")
        self.assertEqual(blocking, [])
        self.assertEqual(len(regen), 2)

    def test_build_caches_are_regenerable(self):
        # These condemned three integration worktree slots for life (2.4GB of leak).
        blocking, regen = self.ra.partition_dirt(
            " D pkg/node_modules/.vite/vitest/abc/results.json\n D server/__pycache__/x.cpython-310.pyc")
        self.assertEqual(blocking, [])
        self.assertEqual(len(regen), 2)

    def test_leading_space_is_not_stripped(self):
        # `.strip()` on whole porcelain output ate the first line's leading space, shifting the
        # fixed-width XY parse and dropping the path's first character.
        blocking, regen = self.ra.partition_dirt(" M .runner_boot_commit\n M reports/x.md")
        self.assertEqual(regen, [" M .runner_boot_commit"])
        self.assertEqual(blocking, [" M reports/x.md"])

    def test_dotfiles_still_match(self):
        # lstrip("./") would eat the leading dot of every dotfile.
        self.assertTrue(self.ra.is_regenerable(".orch-context-cache.json"))


class TestCanonicalMutation(unittest.TestCase):
    """The guard that catches a merge pass mutating the canonical checkout. It used to compare
    full --untracked-files=all snapshots and fired 57 times on ordinary fleet noise, leaking a
    worktree every time because it raised before cleanup."""

    def setUp(self):
        import integration_runtime
        self.ir = integration_runtime
        self.base = {"top": "/r", "branch": "master", "head": "abc", "status": " M src/a.ts\n"}

    def _after(self, **kw):
        return {**self.base, **kw}

    def test_identical_is_not_a_mutation(self):
        self.assertFalse(self.ir._canonical_mutation(self.base, dict(self.base)))

    def test_untracked_appearing_is_not_a_mutation(self):
        self.assertFalse(self.ir._canonical_mutation(
            self.base, self._after(status=" M src/a.ts\n?? docs/ADR-x.md\n")))

    def test_regenerable_tracked_dirt_is_not_a_mutation(self):
        self.assertFalse(self.ir._canonical_mutation(
            self.base, self._after(status=" M src/a.ts\n M .runner_boot_commit\n")))

    def test_head_move_is_a_mutation(self):
        self.assertIn("head:", self.ir._canonical_mutation(self.base, self._after(head="def")))

    def test_branch_switch_is_a_mutation(self):
        self.assertIn("branch:", self.ir._canonical_mutation(self.base, self._after(branch="dev")))

    def test_new_tracked_edit_is_a_mutation(self):
        self.assertIn("src/b.ts", self.ir._canonical_mutation(
            self.base, self._after(status=" M src/a.ts\n M src/b.ts\n")))

    def test_tracked_deletion_is_a_mutation(self):
        self.assertTrue(self.ir._canonical_mutation(self.base, self._after(status=" D src/a.ts\n")))


class TestOrphanImports(unittest.TestCase):
    """apparently shipped a committed governance.ts importing an uncommitted kv.ts. Production
    was red five hours; every local build was green, because the file was on the author's disk."""

    @classmethod
    def setUpClass(cls):
        import orphan_imports
        cls.oi = orphan_imports
        cls.repo = tempfile.mkdtemp(prefix="orphan-import-test-")
        def git(*a):
            subprocess.run(["git", *a], cwd=cls.repo, check=True,
                           capture_output=True, encoding="utf-8")
        git("init", "-q")
        git("config", "user.email", "t@t"); git("config", "user.name", "t")
        os.makedirs(os.path.join(cls.repo, "server", "utils"))
        w = lambda p, s: open(os.path.join(cls.repo, p), "w", encoding="utf-8").write(s)
        w("server/utils/governance.ts", "import { hydrate } from './kv'\nexport const x = 1\n")
        w("server/utils/present.ts", "import { hydrate } from './kv'\nexport const y = 2\n")
        w("server/utils/kv.ts", "export const hydrate = () => null\n")
        git("add", "server/utils/governance.ts", "server/utils/present.ts")
        git("commit", "-qm", "commit the importer but NOT the module it needs")

    def test_import_of_an_untracked_module_is_dangling(self):
        found = self.oi.dangling_imports(self.repo)
        self.assertTrue(any(f.endswith("governance.ts") for f, _, _ in found))

    def test_the_reason_distinguishes_untracked_from_absent(self):
        found = self.oi.dangling_imports(self.repo)
        self.assertTrue(any("not tracked" in why for _, _, why in found))

    def test_scoping_to_changed_files_limits_the_verdict(self):
        self.assertFalse(self.oi.dangling_imports(self.repo, only_files={"server/utils/nope.ts"}))
        self.assertTrue(self.oi.dangling_imports(
            self.repo, only_files={"server/utils/governance.ts"}))

    def test_alias_specifiers_are_ignored(self):
        # Resolving "~/" needs srcDir and tsconfig paths; guessing gave 281 findings across four
        # repos whose builds were all green.
        self.assertNotIn("~/", self.oi._IMPORT.pattern)

    def test_tracked_module_resolves_cleanly(self):
        subprocess.run(["git", "add", "server/utils/kv.ts"], cwd=self.repo, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", "add the module"], cwd=self.repo, check=True,
                       capture_output=True)
        self.assertFalse(self.oi.dangling_imports(self.repo))


class TestLegacyKillSwitchClamp(unittest.TestCase):
    """fleet_config MERGE_TRAIN_SCAN_LIMIT=0 starves the merge train on hosts too old to honour
    integration_owner. Current code must decline it — a pin that depends on a restart landing in
    the right order is not a safety interlock, and this host silently took the switch once."""

    def test_non_positive_limit_is_declined(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "merge_train.py"), encoding="utf-8").read()
        self.assertIn('if int(str(limit).strip().strip(\'"\')) <= 0:', src)
        self.assertIn('limit = "3000"', src)


class TestCaseCollisions(unittest.TestCase):
    """An auto-resolved merge left racefeed tracking both OPPORTUNITIES.json and
    opportunities.json. macOS APFS is case-insensitive, so only one can exist on disk and git
    reports the other as modified in every checkout — that integration worktree was condemned
    from the moment the merge landed. Additive damage, so no deletion or stub guard sees it."""

    @classmethod
    def setUpClass(cls):
        import orphan_imports
        cls.oi = orphan_imports
        cls.repo = tempfile.mkdtemp(prefix="case-collision-test-")
        def git(*a):
            subprocess.run(["git", *a], cwd=cls.repo, check=True, capture_output=True)
        git("init", "-q")
        git("config", "user.email", "t@t"); git("config", "user.name", "t")
        git("config", "core.ignorecase", "false")  # force both entries into the index
        open(os.path.join(cls.repo, "a.json"), "w").write("{}")
        open(os.path.join(cls.repo, "with space.txt"), "w").write("x")
        git("add", "a.json", "with space.txt")
        # Stage the second casing directly; a case-insensitive checkout cannot create both.
        h = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=cls.repo,
                           input=b"{}", capture_output=True).stdout.decode().strip()
        subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"100644,{h},A.json"],
                       cwd=cls.repo, check=True, capture_output=True)
        git("commit", "-qm", "two spellings of the same path")

    def test_collision_is_reported(self):
        found = self.oi.case_collisions(self.repo)
        self.assertEqual([p for _, p in found], [["A.json", "a.json"]])

    def test_filenames_with_spaces_are_not_shattered(self):
        # ls-files split on whitespace turned "assets/images/The Machine B_W.png" into
        # fragments and invented eight collisions in a repo that had none.
        self.assertIn("with space.txt", self.oi._ls(self.repo))
        self.assertNotIn("with", self.oi._ls(self.repo))

    def test_scoping_limits_the_verdict(self):
        self.assertTrue(self.oi.case_collisions(self.repo, only_files={"a.json"}))
        self.assertFalse(self.oi.case_collisions(self.repo, only_files={"unrelated.txt"}))


class TestAbandonedTemporaryWorktrees(unittest.TestCase):
    """A temporary slot is removed in the `finally` of the pass that made it — so a pass that is
    killed leaves one nothing will ever collect. Observed after killing a wedged train: a
    registered, clean, 83MB slot that the orphan sweep declined because git still tracked it."""

    def setUp(self):
        import integration_runtime
        self.ir = integration_runtime

    def test_dead_creator_is_detected_from_the_path(self):
        self.assertFalse(self.ir._temp_owner_alive("/x/slot-run-999999-123"))

    def test_live_creator_is_left_alone(self):
        self.assertTrue(self.ir._temp_owner_alive(f"/x/slot-run-{os.getpid()}-123"))

    def test_unparseable_name_is_assumed_live(self):
        # Guessing wrong in this direction costs disk; the other direction deletes a live pass.
        self.assertTrue(self.ir._temp_owner_alive("/x/slot"))
        self.assertTrue(self.ir._temp_owner_alive("/x/slot-run-notapid-123"))

    def test_sweep_only_targets_temporaries_by_name(self):
        import inspect
        src = inspect.getsource(self.ir.sweep_orphaned_temporaries)
        self.assertIn("-run-*", src)
        # Must refuse a slot holding uncommitted content, whatever its name.
        self.assertIn("status.returncode or status.stdout", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
