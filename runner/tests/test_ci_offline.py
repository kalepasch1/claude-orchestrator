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


class TestRepoRootCanaryEntryPoint(unittest.TestCase):
    """`canary.py` at the repo root is what the scheduled canary workflow shells out to, and its
    exit code is the entire pass/fail signal. Until now nothing verified it: CI's compileall runs
    inside runner/ only, so the repo-root modules were never even syntax-checked, and a typo in
    main() would have surfaced as a green schedule that silently validated nothing.

    Pure logic, no network, no credentials — belongs in the blocking beachhead."""

    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(self.ROOT, "canary.py"), *args],
            capture_output=True, text=True,
        )

    def test_marker_present_exits_zero(self):
        self.assertEqual(self._run("this response is a canary").returncode, 0)

    def test_marker_absent_exits_nonzero(self):
        # The workflow gates on this. A zero here would report a passing canary on a dead key.
        self.assertEqual(self._run("gemini returned nothing useful").returncode, 1)

    def test_no_arguments_exits_nonzero(self):
        # Empty stdout from the provider must fail, not pass by vacuous truth.
        self.assertEqual(self._run().returncode, 1)

    def test_match_is_case_insensitive_and_word_bounded(self):
        sys.path.insert(0, self.ROOT)
        import canary
        self.assertTrue(canary.validate_canary("CANARY"))
        self.assertFalse(canary.validate_canary("canarybird"))
        self.assertFalse(canary.validate_canary(None))

    def test_every_repo_root_module_compiles(self):
        # CI compiled runner/ only, so a half-landed refactor in a repo-root module shipped
        # unnoticed. Mirrors the runner-wide compileall guard at the root level.
        import compileall
        roots = [os.path.join(self.ROOT, f) for f in os.listdir(self.ROOT) if f.endswith(".py")]
        self.assertTrue(roots, "expected repo-root python modules to exist")
        for path in roots:
            with self.subTest(module=os.path.basename(path)):
                self.assertTrue(compileall.compile_file(path, quiet=2, force=True))


class TestGateBudget(unittest.TestCase):
    """The four anti-loss gates are the fleet's overwrite protection AND were where every train
    pass was dying: zero merges in 24h while the watchdog fired 56 times at the 900s cap, every
    dump inside _verify_merge. One slow branch consumed the whole cycle."""

    def setUp(self):
        os.environ["ORCH_MERGE_GATE_TIMEOUT_S"] = "2"
        import auto_conflict_resolver
        self.acr = auto_conflict_resolver
        self._saved = {n: getattr(auto_conflict_resolver, n) for n in
                       ("_regression_check", "_divergent_check", "_stub_check", "_discard_check")}
        for n in self._saved:
            setattr(auto_conflict_resolver, n, lambda *a, **k: "")

    def tearDown(self):
        for n, fn in self._saved.items():
            setattr(self.acr, n, fn)
        os.environ.pop("ORCH_MERGE_GATE_TIMEOUT_S", None)

    def test_a_hung_gate_refuses_rather_than_hanging(self):
        import time
        self.acr._regression_check = lambda *a, **k: time.sleep(60)
        t = time.time()
        out = self.acr._verify_merge("/tmp", "abc", "main", "agent/x")
        self.assertLess(time.time() - t, 10)
        self.assertTrue(out, "a timed-out gate must refuse the merge, never return clean")

    def test_clean_gates_still_permit_the_merge(self):
        # The budget must not become a merge blocker in the normal case.
        self.assertEqual(self.acr._verify_merge("/tmp", "abc", "main", "agent/x"), "")

    def test_a_real_finding_is_returned_unchanged(self):
        self.acr._stub_check = lambda *a, **k: "SILENT STUB in foo.ts"
        self.assertEqual(self.acr._verify_merge("/tmp", "abc", "main", "agent/x"),
                         "SILENT STUB in foo.ts")

    def test_a_crashing_gate_is_still_fail_closed(self):
        def boom(*a, **k):
            raise RuntimeError("kaboom")
        self.acr._divergent_check = boom
        out = self.acr._verify_merge("/tmp", "abc", "main", "agent/x")
        self.assertIn("fail-closed", out)

    def test_the_budget_can_be_disabled(self):
        os.environ["ORCH_MERGE_GATE_TIMEOUT_S"] = "0"
        self.assertEqual(self.acr._bounded("off", lambda: "ran"), "ran")


class TestGateLivenessIsOffTheCriticalPath(unittest.TestCase):
    """record() swallowed exceptions but never bounded TIME. Each db.insert can spend 15s per
    attempt across retries and fallback relays, and there are 23 call sites, several inside
    per-branch merge gates. 11 of the 56 watchdog dumps were stopped exactly here."""

    def test_record_does_not_wait_for_the_control_plane(self):
        import importlib, time
        import db
        saved = db.insert
        try:
            db.insert = lambda table, row, **kw: time.sleep(3)
            import gate_liveness
            importlib.reload(gate_liveness)
            t = time.time()
            for i in range(10):
                self.assertIs(gate_liveness.record("probe", True, f"s{i}"), True)
            self.assertLess(time.time() - t, 1.0,
                            "record() must not block on a slow backend")
        finally:
            db.insert = saved

    def test_verdict_passes_through_unchanged(self):
        import gate_liveness
        self.assertEqual(gate_liveness.record("probe", "green", "x"), "green")
        self.assertIs(gate_liveness.record("probe", False, "x"), False)


class TestShadowMode(unittest.TestCase):
    """One switch that stops every shared-ref write and records what would have happened.

    The alternative was four switches (ORCH_PUSH_ON_MERGE, ORCH_PUSH_ON_DEV_MERGE,
    ORCH_AUTO_MERGE_APPROVALS, ORCH_DISABLED_JOBS) that must all be right across two hosts, a
    .env and a fleet_config table that outranks it. This codebase has already been bitten by a
    pin that silently did not apply because the runner inherited a stale value from its parent
    shell — four coupled switches is not a safety property anyone can verify at a glance."""

    def setUp(self):
        import shadow_mode
        self.sm = shadow_mode
        os.environ.pop("ORCH_SHADOW_MODE", None)

    def tearDown(self):
        os.environ.pop("ORCH_SHADOW_MODE", None)

    def test_off_by_default(self):
        # Adding a kill switch must not change behaviour until someone turns it on.
        self.assertFalse(self.sm.active())
        self.assertFalse(self.sm.refuse("push", "p", "s", "d"))

    def test_refuses_when_on(self):
        os.environ["ORCH_SHADOW_MODE"] = "true"
        self.assertTrue(self.sm.active())
        self.assertTrue(self.sm.refuse("push-integration-branch", "tomorrow", "main", "x"))

    def test_accepts_the_usual_truthy_spellings(self):
        for v in ("1", "true", "TRUE", "yes", "on"):
            os.environ["ORCH_SHADOW_MODE"] = v
            self.assertTrue(self.sm.active(), v)
        for v in ("0", "false", "no", "off", ""):
            os.environ["ORCH_SHADOW_MODE"] = v
            self.assertFalse(self.sm.active(), v)

    def test_the_intent_is_recorded_not_just_blocked(self):
        # A shadow run that blocks without recording teaches nothing about trustworthiness.
        os.environ["ORCH_SHADOW_MODE"] = "true"
        before = len(self.sm.intents())
        self.sm.refuse("merge-branch", "apparently", "agent/x", "--no-ff into master")
        self.assertEqual(len(self.sm.intents()), before + 1)
        self.assertIn("merge-branch", self.sm.intents()[-1])

    def test_bookkeeping_failure_never_blocks_the_pass(self):
        os.environ["ORCH_SHADOW_MODE"] = "true"
        import db
        saved = db.insert
        try:
            db.insert = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("control plane down"))
            self.assertTrue(self.sm.refuse("push", "p", "s", "d"))
        finally:
            db.insert = saved

    def test_the_write_paths_actually_consult_it(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for mod, call in (("merge_train.py", "push-integration-branch"),
                          ("approval_merge.py", "merge-branch")):
            src = open(os.path.join(base, mod)).read()
            self.assertIn("import shadow_mode", src, mod)
            self.assertIn(call, src, mod)



class TestPreflightDoesNotDiscardRealSpecs(unittest.TestCase):
    """preflight quarantined anything that had failed 4 times. Audited 2026-08-15: 139 tasks
    were destroyed by that rule, every one in the cowork lane, every one carrying a real
    specification (1,311 to 25,230 characters, median 5,985). Not one was a garbage stub.

    An attempt is consumed by ANY failure, and this fleet spent months failing for reasons that
    had nothing to do with the task — an orphaned merge-train lock, gates hanging inside their
    own telemetry, hidden scan windows, cross-host push races."""

    SPEC = "## OBJECTIVE\n" + "Detail line explaining the required behaviour.\n" * 60
    THIN = "fix it"

    def setUp(self):
        import preflight_filter
        self.pf = preflight_filter
        for k in ("ORCH_PREFLIGHT_MAX_ATTEMPTS", "ORCH_PREFLIGHT_HARD_CEILING",
                  "ORCH_PREFLIGHT_SUBSTANTIAL_CHARS"):
            os.environ.pop(k, None)

    def _check(self, prompt, attempt, note=""):
        return self.pf.preflight_check(
            {"slug": "t", "prompt": prompt, "attempt": attempt, "note": note})

    def test_a_detailed_spec_survives_repeated_failure(self):
        self.assertEqual(self._check(self.SPEC, 5), "")

    def test_a_thin_prompt_that_keeps_failing_is_still_rejected(self):
        self.assertIn("exhausted", self._check(self.THIN, 5))

    def test_nothing_retries_forever(self):
        self.assertIn("hard ceiling", self._check(self.SPEC, 12))

    def test_garbage_stubs_are_still_caught(self):
        self.assertIn("PATCH TEMPLATE", self._check("PATCH TEMPLATE deadbeef", 0))

    def test_both_signals_are_required_not_either(self):
        self.assertEqual(self._check(self.SPEC, 3), "")
        self.assertEqual(self._check("x" * 600, 5), "")



class TestSelfMaintenanceQuota(unittest.TestCase):
    """Lifetime audit 2026-08-15: 57.2% of every merge this system ever made was the fleet
    working on its own plumbing, and across the owner's four priority apps the split was
    tomorrow 586, apparently 344, apparently-law 38, PMA/PMI 5.

    The cause is structural: in claim_task's 24-key sort, _portfolio_project_rank — the owner's
    own project order — is the ELEVENTH key, underneath recovery-reserve, release-fix and
    blocker ranks, all of which are self-generated classes. The machine's upkeep outranked the
    products it exists to build."""

    def setUp(self):
        import db
        self.db = db
        os.environ.pop("ORCH_SELF_WORK_MAX_SHARE", None)

    def tearDown(self):
        os.environ.pop("ORCH_SELF_WORK_MAX_SHARE", None)

    def test_the_classifier_knows_upkeep_from_product_work(self):
        for slug in ("canary-x", "recover-missing-branch-y", "backlog-batch-z", "rework-a",
                     "relfix-b", "qafix-c", "gc-d", "dedup-e"):
            self.assertTrue(self.db._is_self_maintenance({"slug": slug}), slug)
        for slug in ("dropbox-apparently-licensing", "improve-landing-page", "v15-30-fleet",
                     "trust-ratchet-per-user-state-tracking"):
            self.assertFalse(self.db._is_self_maintenance({"slug": slug}), slug)

    def test_an_empty_or_missing_slug_is_not_upkeep(self):
        # Misclassifying unknown work as upkeep would quietly starve it.
        self.assertFalse(self.db._is_self_maintenance({}))
        self.assertFalse(self.db._is_self_maintenance({"slug": None}))
        self.assertFalse(self.db._is_self_maintenance(None))

    def test_the_quota_is_wired_into_claim_ordering(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "db.py")).read()
        self.assertIn("ORCH_SELF_WORK_MAX_SHARE", src)
        # It must filter BEFORE the sort, leaving the 24-key ordering untouched.
        self.assertLess(src.index("ORCH_SELF_WORK_MAX_SHARE"),
                        src.index("queued.sort(key=lambda t: (_pinned_rank(t),"))

    def test_a_lane_is_never_idled_just_to_hold_a_ratio(self):
        # If only upkeep is available, it must still be claimable — an idle machine helps no one.
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "db.py")).read()
        self.assertIn("never idle a lane just to enforce a ratio", src)



class TestShadowModeDefersRatherThanCompletes(unittest.TestCase):
    """The first version of this wiring had two bugs, and both are the kind that make a safety
    feature actively dangerous rather than merely useless.

    It sat below the ORCH_PUSH_ON_MERGE guard, which returns early and is false in this fleet —
    so the check was unreachable and recorded nothing, while looking installed.

    And it returned "". _push_base returns "" for SUCCESS, so a refusal would have told the
    caller the push worked and let the task go MERGED with nothing sent to origin: a database
    that says shipped while GitHub never moved. That is the exact desync the push-verification
    gate exists to stop."""

    def setUp(self):
        import merge_train
        self.mt = merge_train
        os.environ.pop("ORCH_SHADOW_MODE", None)

    def tearDown(self):
        os.environ.pop("ORCH_SHADOW_MODE", None)

    def test_a_refusal_is_never_mistaken_for_a_successful_push(self):
        os.environ["ORCH_SHADOW_MODE"] = "true"
        out = self.mt._push_base("/tmp", "main", project="probe")
        self.assertTrue(out, "empty return means SUCCESS to the caller; a refusal must not")
        self.assertIn("withheld", out)

    def test_the_check_runs_before_every_other_early_return(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "merge_train.py")).read()
        body = src[src.index("def _push_base("):]
        # Anchored on the STATEMENT, not a name that also appears in prose. This test has now
        # caught two things: a guard placed after an early return, and its own weakness when
        # the early return was rewritten to call _push_enabled_for_base instead.
        self.assertLess(body.index("shadow_mode.refuse"),
                        body.index("if not _push_enabled_for_base(base):"),
                        "a guard placed after an early return is a guard that never runs")

    def test_off_by_default_changes_nothing(self):
        self.assertEqual(self.mt._push_base("/tmp", "main", project="probe"), "")



class TestIntegrationBranchIsActuallyPushed(unittest.TestCase):
    """_push_base gated on ORCH_PUSH_ON_MERGE — the flag for pushing a PRODUCTION base, false in
    this fleet. The integration branch is orchestrator/dev, whose flag is ORCH_PUSH_ON_DEV_MERGE
    and is true. _push_enabled_for_base() encodes that distinction and had ZERO call sites: it
    was written and never wired.

    Every train pass therefore merged into the LOCAL integration branch, reported success, and
    the sha-verification below then found origin had not moved. That is the PUSH-VERIFY-FAILED
    count, and why local orchestrator/dev ran one to four days ahead of origin in every app."""

    def setUp(self):
        import merge_train
        self.mt = merge_train
        self._saved = {k: os.environ.get(k) for k in
                       ("ORCH_STAGING_BRANCH", "ORCH_PUSH_ON_DEV_MERGE", "ORCH_PUSH_ON_MERGE",
                        "ORCH_BATCH_DEV_RELEASE", "ORCH_SHADOW_MODE")}
        os.environ.update({"ORCH_STAGING_BRANCH": "orchestrator/dev",
                           "ORCH_PUSH_ON_DEV_MERGE": "true",
                           "ORCH_PUSH_ON_MERGE": "false",
                           "ORCH_BATCH_DEV_RELEASE": "true"})
        os.environ.pop("ORCH_SHADOW_MODE", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_the_integration_branch_is_push_enabled(self):
        self.assertTrue(self.mt._push_enabled_for_base("orchestrator/dev"))

    def test_a_production_base_stays_push_disabled(self):
        # The batch release train owns production; the merge train must not push there.
        self.assertFalse(self.mt._push_enabled_for_base("main"))
        self.assertFalse(self.mt._push_enabled_for_base("master"))

    def test_push_base_consults_the_policy_not_the_production_flag(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "merge_train.py")).read()
        body = src[src.index("def _push_base("):]
        body = body[:body.index("\ndef ", 10)]
        self.assertIn("_push_enabled_for_base(base)", body,
                      "the policy helper must actually be called")
        self.assertNotIn('os.environ.get("ORCH_PUSH_ON_MERGE"', body,
                         "gating the integration push on the production flag is the bug")

    def test_shadow_mode_still_outranks_the_policy(self):
        os.environ["ORCH_SHADOW_MODE"] = "true"
        self.assertIn("withheld", self.mt._push_base("/tmp", "orchestrator/dev", project="p"))



class TestShadowModeCoversProduction(unittest.TestCase):
    """Shadow mode was wired into merge_train and approval_merge but NOT release_train — the
    only line in the fleet that moves a PRODUCTION branch, and the one Vercel builds from.

    A kill switch that stops the harmless writes and permits the consequential one is not a kill
    switch. Bear would have discovered that the first time a release fired during a window he
    believed was observe-only."""

    def test_every_origin_moving_push_consults_shadow_mode(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for mod in ("merge_train.py", "approval_merge.py", "release_train.py"):
            src = open(os.path.join(base, mod)).read()
            self.assertIn("import shadow_mode", src, f"{mod} does not import it")
            self.assertIn("shadow_mode.refuse", src, f"{mod} never calls it")

    def test_the_production_promotion_is_guarded_before_the_push(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(base, "release_train.py")).read()
        guard = src.index('shadow_mode.refuse("promote-to-production"')
        push = src.index('_git(repo, "push", "origin", f"{STAGING}:{prod}"')
        self.assertLess(guard, push, "the guard must precede the push it guards")

    def test_a_withheld_promotion_is_not_reported_as_released(self):
        # The refusal must take the "did not promote" shape. Recording a promotion that never
        # happened is the same DB/GitHub desync the push-verification gate exists to prevent.
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(base, "release_train.py")).read()
        tail = src[src.index('shadow_mode.refuse("promote-to-production"'):][:400]
        self.assertIn("return False", tail)



class TestEveryIntegrationPathIsGuarded(unittest.TestCase):
    """Enumerating the write paths instead of remembering them turned up two more.

    runner.py integrates INLINE when a worker finishes, independently of merge_train, and pushes
    the shared branch itself — so the merge train never pushing (fixed separately) was only half
    the story; this path did push. improvement_verify pushes HEAD to the shared staging branch
    as a third route. Neither consulted shadow mode.

    runner.py also DISCARDED its push result and returned "MERGED" regardless, so a rejected
    push still counted as shipped — the same DB/GitHub desync the merge train's
    push-verification gate exists to prevent, living unnoticed in the other integrate path."""

    def _src(self, name):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(base, name)).read()

    def test_all_five_shared_ref_writers_consult_shadow_mode(self):
        for mod in ("merge_train.py", "approval_merge.py", "release_train.py",
                    "runner.py", "improvement_verify.py"):
            self.assertIn("shadow_mode.refuse", self._src(mod), f"{mod} never calls it")

    def test_the_inline_integrate_checks_its_push_result(self):
        src = self._src("runner.py")
        self.assertIn('print(f"[integrate] push {base} failed; NOT marking merged', src)
        guard = src.index("_pr = subprocess.run")
        verdict = src.index("_pr.returncode != 0")
        self.assertLess(guard, verdict)

    def test_a_withheld_inline_push_does_not_report_merged(self):
        src = self._src("runner.py")
        tail = src[src.index('shadow_mode.refuse("push-integration-branch", project=str(base)'):][:600]
        self.assertIn('return "PUSH-PENDING"', tail)
        self.assertNotIn('return "MERGED"', tail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
