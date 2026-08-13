"""Tests for runner/frontier_council.py — the frontier planning council.

Proof command:
    python3 -m unittest runner.tests.test_frontier_planning_council -v

No network and no real models: every test injects a fake `ask` callable, so
the council's control flow, anonymization, signing, and fallback behaviour are
asserted deterministically. Git-backed tests build a real throwaway repo so
the dossier is pinned against actual SHAs rather than mocked ones.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import frontier_council as fc  # noqa: E402


BROAD = (
    "Extend the planner so that broad, material objectives build one pinned "
    "codebase dossier at an exact base SHA and run a multi-seat review before "
    "any code is written. This touches the release path, requires a schema "
    "migration with a rollback, and changes security-relevant credential "
    "handling across the fleet, so the plan must name its non-goals, its file "
    "ownership, and when to escalate to the owner rather than proceed. "
) * 2

CANDIDATES = [("openai", "gpt-x"), ("google", "gemini-x"),
              ("anthropic", "claude-x"), ("deepseek", "deepseek-x")]


class FakeAsk:
    """Records every call and replies per-operation. Deterministic."""

    def __init__(self, dead=(), replies=None, raises=()):
        self.dead = set(dead)          # providers that answer nothing
        self.raises = set(raises)      # providers that blow up
        self.replies = replies or {}
        self.calls = []

    def __call__(self, provider, model, prompt, operation="", timeout=None):
        self.calls.append({"provider": provider, "model": model,
                           "operation": operation, "prompt": prompt})
        if provider in self.raises:
            raise RuntimeError(f"{provider} exploded")
        if provider in self.dead:
            return {"text": ""}
        if operation == "capability_probe":
            return {"text": "ready"}
        return {"text": self.replies.get(operation,
                                         f"{operation} from {provider}")}


def _git(repo, *args):
    subprocess.run(["git"] + list(args), cwd=repo, check=True,
                   capture_output=True, text=True)


class GitRepoCase(unittest.TestCase):
    """A real throwaway git repo so dossiers pin against real SHAs."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="council-repo-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "test")
        with open(os.path.join(self.repo, "alpha.py"), "w") as fh:
            fh.write("import beta\n\n\ndef alpha_entry():\n    return 1\n\n"
                     "class Alpha:\n    pass\n")
        with open(os.path.join(self.repo, "beta.py"), "w") as fh:
            fh.write("def beta_helper():\n    return 2\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "first")
        with open(os.path.join(self.repo, "beta.py"), "a") as fh:
            fh.write("\n\ndef beta_second():\n    return 3\n")
        _git(self.repo, "commit", "-qam", "second")


class TestGate(unittest.TestCase):
    """Council overhead is only paid for broad/material work."""

    def test_broad_material_objective_convenes(self):
        self.assertTrue(fc.should_convene({"kind": "build"}, BROAD))

    def test_short_objective_is_skipped(self):
        self.assertFalse(fc.should_convene({"kind": "build"}, "fix the typo"))

    def test_long_but_mechanical_objective_is_skipped(self):
        """Length alone must not buy a council."""
        text = "Please fix the docstring formatting in every module. " * 30
        self.assertFalse(fc.should_convene({"kind": "build"}, text))

    def test_canary_kind_never_convenes(self):
        self.assertFalse(fc.should_convene({"kind": "canary"}, BROAD))

    def test_high_value_flag_convenes_without_a_marker(self):
        text = "Rework the onboarding copy end to end for the whole product. " * 12
        self.assertFalse(fc.should_convene({"kind": "build"}, text))
        self.assertTrue(fc.should_convene({"kind": "build", "high_value": True},
                                          text))

    def test_kill_switch_disables_the_council(self):
        os.environ["ORCH_FRONTIER_COUNCIL"] = "false"
        self.addCleanup(os.environ.pop, "ORCH_FRONTIER_COUNCIL", None)
        self.assertFalse(fc.should_convene({"kind": "build"}, BROAD))

    def test_gate_is_fail_soft_on_junk_input(self):
        self.assertFalse(fc.should_convene(None, None))
        self.assertFalse(fc.should_convene({}, ""))


class TestPinnedDossier(GitRepoCase):
    """One dossier, pinned at an exact SHA, identical for every seat."""

    def test_dossier_pins_to_an_exact_sha(self):
        sha = fc.resolve_base_sha(self.repo)
        self.assertEqual(len(sha), 40)
        d = fc.build_dossier(self.repo, paths=["alpha.py", "beta.py"])
        self.assertEqual(d["base_sha"], sha)
        self.assertTrue(all(f["present"] for f in d["files"]))

    def test_dossier_id_is_content_addressed_and_stable(self):
        a = fc.build_dossier(self.repo, paths=["alpha.py"])
        b = fc.build_dossier(self.repo, paths=["alpha.py"])
        self.assertEqual(a["dossier_id"], b["dossier_id"])
        c = fc.build_dossier(self.repo, paths=["alpha.py", "beta.py"])
        self.assertNotEqual(a["dossier_id"], c["dossier_id"])

    def test_older_sha_yields_different_evidence(self):
        """Pinning is real: the parent commit produces a different dossier."""
        head = fc.resolve_base_sha(self.repo)
        parent = fc.resolve_base_sha(self.repo, "HEAD~1")
        now = fc.build_dossier(self.repo, base_sha=head, paths=["beta.py"])
        then = fc.build_dossier(self.repo, base_sha=parent, paths=["beta.py"])
        self.assertNotEqual(now["dossier_id"], then["dossier_id"])
        self.assertGreater(now["files"][0]["lines"], then["files"][0]["lines"])

    def test_symbol_graph_captures_defs_and_import_edges(self):
        d = fc.build_dossier(self.repo, paths=["alpha.py", "beta.py"])
        nodes = d["symbol_graph"]["nodes"]
        self.assertIn("alpha_entry", nodes["alpha.py"])
        self.assertIn("Alpha", nodes["alpha.py"])
        self.assertIn("beta_helper", nodes["beta.py"])
        self.assertIn({"from": "alpha.py", "to": "beta.py"},
                      d["symbol_graph"]["edges"])

    def test_history_invariants_failures_and_release_evidence_are_carried(self):
        d = fc.build_dossier(self.repo, paths=["alpha.py"],
                             invariants=["fail-soft: never raise into runner"],
                             failures=["2026-08-02 plaintext credential purge"],
                             release_evidence=["v1.2 shipped clean"])
        self.assertEqual([h["subject"] for h in d["history"]],
                         ["second", "first"])
        self.assertEqual(d["invariants"], ["fail-soft: never raise into runner"])
        self.assertEqual(d["failures"],
                         ["2026-08-02 plaintext credential purge"])
        self.assertEqual(d["release_evidence"], ["v1.2 shipped clean"])

    def test_missing_file_degrades_instead_of_raising(self):
        d = fc.build_dossier(self.repo, paths=["alpha.py", "does-not-exist.py"])
        present = {f["path"]: f["present"] for f in d["files"]}
        self.assertTrue(present["alpha.py"])
        self.assertFalse(present["does-not-exist.py"])

    def test_non_repo_path_is_fail_soft(self):
        d = fc.build_dossier("/nonexistent/repo/xyz", paths=["a.py"])
        self.assertEqual(d["base_sha"], "")
        self.assertTrue(d["dossier_id"])


class TestCapabilityProbeAndSeating(unittest.TestCase):
    """Catalog strings are a claim; the probe is the evidence."""

    def test_probe_drops_unreachable_models(self):
        ask = FakeAsk(dead=["google"], raises=["deepseek"])
        live = fc.probe_capabilities(CANDIDATES, ask)
        self.assertEqual(live, [("openai", "gpt-x"), ("anthropic", "claude-x")])

    def test_probe_never_raises_when_every_provider_fails(self):
        ask = FakeAsk(raises=[p for p, _ in CANDIDATES])
        self.assertEqual(fc.probe_capabilities(CANDIDATES, ask), [])

    def test_probe_handles_empty_candidate_list(self):
        self.assertEqual(fc.probe_capabilities([], FakeAsk()), [])
        self.assertEqual(fc.probe_capabilities(None, FakeAsk()), [])

    def test_seats_are_one_per_vendor_family(self):
        """Two models from one family buy cost, not independence."""
        live = [("openai", "gpt-x"), ("openai", "gpt-y"), ("google", "gemini-x")]
        seats = fc.select_seats(live)
        self.assertEqual(len(seats), 2)
        self.assertEqual(len({s["family"] for s in seats}), 2)

    def test_seat_count_is_capped(self):
        live = [(f"vendor{i}", f"m{i}") for i in range(10)]
        self.assertLessEqual(len(fc.select_seats(live, max_seats=3)), 3)


class TestRounds(unittest.TestCase):
    """Proposals are independent; critiques are blind; the judge is separate."""

    def _seats(self):
        return fc.select_seats([("openai", "gpt-x"), ("google", "gemini-x"),
                                ("anthropic", "claude-x")])

    def test_each_seat_proposes_once_against_the_pinned_dossier(self):
        ask = FakeAsk()
        seats = self._seats()
        dossier = {"dossier_id": "abc123", "base_sha": "deadbeef"}
        proposals = fc.gather_proposals(seats, BROAD, dossier, ask)
        self.assertEqual(len(proposals), 3)
        self.assertTrue(all(p["ok"] for p in proposals))
        prompts = [c["prompt"] for c in ask.calls
                   if c["operation"] == "council_proposal"]
        self.assertEqual(len(prompts), 3)
        # Same pinned evidence in every seat's prompt.
        for p in prompts:
            self.assertIn("abc123", p)
            self.assertIn("deadbeef", p)

    def test_a_failed_seat_is_recorded_and_the_round_continues(self):
        ask = FakeAsk(raises=["google"])
        proposals = fc.gather_proposals(self._seats(), BROAD,
                                        {"dossier_id": "x"}, ask)
        failed = [p for p in proposals if not p["ok"]]
        self.assertEqual(len(failed), 1)
        self.assertIn("RuntimeError", failed[0]["error"])
        self.assertEqual(len([p for p in proposals if p["ok"]]), 2)

    def test_critique_input_is_anonymized(self):
        """No provider, model, or family name may reach a reviewing seat."""
        ask = FakeAsk()
        seats = self._seats()
        proposals = fc.gather_proposals(seats, BROAD, {"dossier_id": "x"}, ask)
        anon = fc.anonymize(proposals)
        self.assertEqual([a["label"] for a in anon],
                         ["Proposal A", "Proposal B", "Proposal C"])
        for a in anon:
            self.assertNotIn("provider", a)
            self.assertNotIn("model", a)
            self.assertNotIn("family", a)
        # Attribution survives for the evidence record.
        self.assertEqual({a["seat_id"] for a in anon},
                         {s["seat_id"] for s in seats})

    def test_no_seat_critiques_its_own_proposal(self):
        ask = FakeAsk()
        seats = self._seats()
        proposals = fc.gather_proposals(seats, BROAD, {"dossier_id": "x"}, ask)
        anon = fc.anonymize(proposals)
        crits = fc.cross_critique(seats, anon, ask)
        for c in crits:
            own = next(a["label"] for a in anon if a["seat_id"] == c["seat_id"])
            self.assertNotIn(own, c["reviewed"])
            self.assertEqual(len(c["reviewed"]), len(seats) - 1)

    def test_adversary_and_judge_are_distinct_operations(self):
        ask = FakeAsk()
        seats = self._seats()
        proposals = fc.gather_proposals(seats[:2], BROAD, {"dossier_id": "x"}, ask)
        anon = fc.anonymize(proposals)
        adv = fc.adversary_review(seats[0], BROAD, anon, ask)
        judgment = fc.synthesize(seats[2], BROAD, proposals, [], adv, ask)
        self.assertTrue(adv["ok"])
        self.assertTrue(judgment["ok"])
        ops = [c["operation"] for c in ask.calls]
        self.assertIn("council_adversary", ops)
        self.assertIn("council_judge", ops)

    def test_missing_adversary_or_judge_degrades_without_raising(self):
        self.assertFalse(fc.adversary_review(None, BROAD, [], FakeAsk())["ok"])
        self.assertFalse(fc.synthesize(None, BROAD, [], [], {}, FakeAsk())["ok"])


class TestSignedContract(unittest.TestCase):
    """One contract, fully specified, and tamper-evident."""

    def _signed(self):
        contract = fc.make_contract(
            "objective", {"base_sha": "abc", "dossier_id": "d1"},
            "the plan", [{"seat_id": "seat-1", "family": "openai"}])
        return fc.sign_contract(contract)

    def test_contract_carries_every_required_field(self):
        c = self._signed()["contract"]
        for field in fc.CONTRACT_FIELDS:
            self.assertIn(field, c, f"contract missing {field}")

    def test_signature_verifies(self):
        self.assertTrue(fc.verify_contract(self._signed()))

    def test_edited_contract_fails_verification(self):
        signed = self._signed()
        signed["contract"]["budgets"]["usd"] = 999999.0
        self.assertFalse(fc.verify_contract(signed))

    def test_forged_signature_fails_verification(self):
        signed = self._signed()
        signed["signature"] = "0" * 32
        self.assertFalse(fc.verify_contract(signed))

    def test_verify_is_fail_soft_on_garbage(self):
        for junk in (None, {}, {"contract": None}, "not-a-contract"):
            self.assertFalse(fc.verify_contract(junk))

    def test_contract_is_json_serializable(self):
        json.dumps(self._signed())


class TestConveneAndFallback(GitRepoCase):
    """End-to-end control flow, including every degradation path."""

    def _convene(self, ask, candidates=CANDIDATES, task=None, objective=BROAD,
                 **kw):
        return fc.convene(task or {"kind": "build"}, objective, self.repo, ask,
                          candidates, paths=["alpha.py", "beta.py"], **kw)

    def test_full_council_produces_one_signed_contract_with_evidence(self):
        ask = FakeAsk()
        out = self._convene(ask)
        self.assertTrue(out["convened"], out.get("reason"))
        self.assertTrue(fc.verify_contract(out))
        ev = out["evidence"]
        self.assertEqual(ev["candidates_offered"], 4)
        self.assertTrue(ev["proposals"])
        self.assertTrue(ev["critiques"])
        self.assertTrue(ev["adversary"]["ok"])
        self.assertTrue(ev["judge"]["ok"])
        self.assertEqual(out["contract"]["base_sha"],
                         fc.resolve_base_sha(self.repo))

    def test_judge_is_not_one_of_the_proposers(self):
        ask = FakeAsk()
        out = self._convene(ask)
        proposer_ids = {p["seat_id"] for p in out["evidence"]["proposals"]}
        self.assertNotIn(out["evidence"]["judge"]["seat_id"], proposer_ids)

    def test_mechanical_objective_returns_deterministic_fallback(self):
        out = self._convene(FakeAsk(), objective="fix a typo")
        self.assertFalse(out["convened"])
        self.assertTrue(fc.verify_contract(out))
        self.assertIn("mechanical", out["reason"])
        self.assertEqual(out["evidence"]["proposals"], [])

    def test_too_few_live_seats_falls_back(self):
        """Quorum is measured in reachable seats, not catalog entries."""
        ask = FakeAsk(dead=["google", "anthropic", "deepseek"])
        out = self._convene(ask)
        self.assertFalse(out["convened"])
        self.assertIn("insufficient live frontier seats", out["reason"])
        self.assertTrue(fc.verify_contract(out))

    def test_silent_proposal_round_falls_back(self):
        class ProbeOnly(FakeAsk):
            def __call__(self, provider, model, prompt, operation="",
                         timeout=None):
                if operation == "capability_probe":
                    return {"text": "ready"}
                return {"text": ""}

        out = self._convene(ProbeOnly())
        self.assertFalse(out["convened"])
        self.assertIn("no seat produced a proposal", out["reason"])

    def test_silent_judge_falls_back_rather_than_signing_an_unwritten_plan(self):
        class NoJudge(FakeAsk):
            def __call__(self, provider, model, prompt, operation="",
                         timeout=None):
                if operation == "council_judge":
                    return {"text": ""}
                return super().__call__(provider, model, prompt, operation,
                                        timeout)

        out = self._convene(NoJudge())
        self.assertFalse(out["convened"])
        self.assertIn("judge", out["reason"])

    def test_fallback_shape_matches_convened_shape(self):
        """Callers consume one contract type either way."""
        good = self._convene(FakeAsk())
        bad = self._convene(FakeAsk(dead=[p for p, _ in CANDIDATES]))
        self.assertEqual(set(good) - {"artifact_path"}, set(bad))
        self.assertEqual(set(good["contract"]), set(bad["contract"]))

    def test_convene_never_raises(self):
        exploding = FakeAsk(raises=[p for p, _ in CANDIDATES])
        out = self._convene(exploding)
        self.assertFalse(out["convened"])
        self.assertTrue(fc.verify_contract(out))


class TestPersistenceAndBrief(GitRepoCase):
    """Evidence is written next to the contract, fail-soft."""

    def test_evidence_is_persisted_to_disk_and_to_the_persister(self):
        outdir = tempfile.mkdtemp(prefix="council-art-")
        self.addCleanup(shutil.rmtree, outdir, ignore_errors=True)
        seen = []
        out = fc.convene({"kind": "build"}, BROAD, self.repo, FakeAsk(),
                         CANDIDATES, paths=["alpha.py"],
                         persister=seen.append, artifact_dir=outdir)
        self.assertTrue(out["convened"], out.get("reason"))
        self.assertEqual(len(seen), 1)
        self.assertTrue(os.path.isfile(out["artifact_path"]))
        with open(out["artifact_path"]) as fh:
            written = json.load(fh)
        self.assertEqual(written["contract_hash"], out["contract_hash"])
        self.assertTrue(written["evidence"]["proposals"])

    def test_a_failing_persister_does_not_break_the_council(self):
        def boom(_record):
            raise IOError("disk on fire")

        out = fc.convene({"kind": "build"}, BROAD, self.repo, FakeAsk(),
                         CANDIDATES, paths=["alpha.py"], persister=boom,
                         artifact_dir="/nonexistent/dir/xyz")
        self.assertTrue(out["convened"], out.get("reason"))
        self.assertEqual(out["artifact_path"], "")

    def test_contract_brief_renders_the_binding_parts(self):
        out = fc.convene({"kind": "build"}, BROAD, self.repo, FakeAsk(),
                         CANDIDATES, paths=["alpha.py"])
        brief = fc.contract_brief(out)
        self.assertIn(out["contract_hash"][:12], brief)
        self.assertIn("ESCALATE:", brief)
        self.assertIn(out["contract"]["plan"], brief)

    def test_contract_brief_is_fail_soft(self):
        self.assertEqual(fc.contract_brief(None), "")
        self.assertEqual(fc.contract_brief({}), "")


class TestPlanStageWiring(unittest.TestCase):
    """plan_stage exposes the council without importing it at module load."""

    def test_council_plan_is_exported_and_skips_small_work(self):
        import plan_stage
        self.assertTrue(callable(plan_stage.council_plan))
        self.assertEqual(
            plan_stage.council_plan({"kind": "build"}, "tiny", "/tmp"),
            (None, None))

    def test_council_plan_is_fail_soft_on_a_bad_repo_path(self):
        import plan_stage
        text, label = plan_stage.council_plan({"kind": "build"}, BROAD,
                                              "/nonexistent/repo",
                                              candidates=[])
        self.assertIsNone(text)
        self.assertIsNone(label)


if __name__ == "__main__":
    unittest.main()
