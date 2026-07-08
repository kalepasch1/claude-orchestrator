import os
import sys
import json
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import learn_from_merges as lfm

GOOD_CONVENTIONS = """**CONVENTIONS**
- Use module-level singletons for shared state
- Fail-soft error handling everywhere

**DO/AVOID RULES**
- DO prefix config keys with ORCH_
- AVOID hardcoding secrets"""

GOOD_MINIMAL = "- Use dependency injection for testability\n- Avoid global mutable state"


def _no_grader(*a, **kw):
    return None  # simulate grading unavailable -> falls back to structural checks


class QualityGateFailurePatternsTest(unittest.TestCase):
    """Content that must always be rejected regardless of structure."""

    def setUp(self):
        self._patch = patch.object(lfm, "_grade_with_cheap_model", side_effect=_no_grader)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_rejects_weekly_limit_banner(self):
        ok, reason = lfm.quality_gate("You've hit your weekly limit · resets Jul 8 at 6am (America/New_York)")
        self.assertFalse(ok)

    def test_rejects_rate_limited_message(self):
        ok, _ = lfm.quality_gate("- item one\n- Error: rate limited, please try again later")
        self.assertFalse(ok)

    def test_rejects_quota_exceeded(self):
        ok, _ = lfm.quality_gate("- a\n- b\nAPI quota exceeded for this billing period")
        self.assertFalse(ok)

    def test_rejects_http_404(self):
        ok, _ = lfm.quality_gate("- a\n- b\nHTTP Error 404: Not Found while fetching resource")
        self.assertFalse(ok)

    def test_rejects_http_500(self):
        ok, _ = lfm.quality_gate("- a\n- b\nInternal Server Error: HTTP 500")
        self.assertFalse(ok)

    def test_rejects_bad_gateway(self):
        ok, _ = lfm.quality_gate("- a\n- b\nBad Gateway from upstream proxy")
        self.assertFalse(ok)

    def test_rejects_too_many_requests(self):
        ok, _ = lfm.quality_gate("- a\n- b\n429 Too Many Requests")
        self.assertFalse(ok)

    def test_rejects_as_an_ai_preamble(self):
        ok, _ = lfm.quality_gate("As an AI, I can summarize:\n- a\n- b")
        self.assertFalse(ok)

    def test_rejects_language_model_preamble(self):
        ok, _ = lfm.quality_gate("As a language model, I don't have opinions.\n- a\n- b")
        self.assertFalse(ok)

    def test_rejects_apology_prefix(self):
        ok, _ = lfm.quality_gate("I apologize, but I cannot complete this request.\n- a\n- b")
        self.assertFalse(ok)

    def test_rejects_i_cannot_help(self):
        ok, _ = lfm.quality_gate("- a\n- b\nI cannot help with that particular request.")
        self.assertFalse(ok)

    def test_rejects_reset_banner_style(self):
        ok, _ = lfm.quality_gate("- a\n- b\nLimits resets Jul 8 at 6am")
        self.assertFalse(ok)


class QualityGateStructuralChecksTest(unittest.TestCase):
    def setUp(self):
        self._patch = patch.object(lfm, "_grade_with_cheap_model", side_effect=_no_grader)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_rejects_empty_string(self):
        ok, reason = lfm.quality_gate("")
        self.assertFalse(ok)
        self.assertEqual(reason, "empty")

    def test_rejects_none(self):
        ok, reason = lfm.quality_gate(None)
        self.assertFalse(ok)

    def test_rejects_whitespace_only(self):
        ok, _ = lfm.quality_gate("   \n\t  ")
        self.assertFalse(ok)

    def test_rejects_too_short(self):
        ok, _ = lfm.quality_gate("- ok")
        self.assertFalse(ok)

    def test_rejects_too_long(self):
        ok, _ = lfm.quality_gate("- " + ("x " * 3000))
        self.assertFalse(ok)

    def test_rejects_prose_with_no_bullets(self):
        ok, _ = lfm.quality_gate("This codebase generally follows good practices and clean code "
                                  "principles throughout the entire implementation surface area.")
        self.assertFalse(ok)

    def test_rejects_single_bullet(self):
        ok, _ = lfm.quality_gate("- only one bullet point here, nothing else follows at all")
        self.assertFalse(ok)

    def test_accepts_two_dash_bullets(self):
        ok, reason = lfm.quality_gate(GOOD_MINIMAL)
        self.assertTrue(ok)

    def test_accepts_asterisk_bullets(self):
        ok, _ = lfm.quality_gate("* Use fail-soft error handling\n* Prefix config keys with ORCH_")
        self.assertTrue(ok)

    def test_accepts_numbered_bullets(self):
        ok, _ = lfm.quality_gate("1. Use fail-soft error handling everywhere in this module\n"
                                  "2. Prefix all config keys with ORCH_ for fleet-wide reach")
        self.assertTrue(ok)

    def test_accepts_full_conventions_block(self):
        ok, reason = lfm.quality_gate(GOOD_CONVENTIONS)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")


class QualityGateModelGradingTest(unittest.TestCase):
    def test_model_says_no_overrides_structural_pass(self):
        with patch.object(lfm, "_grade_with_cheap_model", return_value=False):
            ok, reason = lfm.quality_gate(GOOD_MINIMAL)
        self.assertFalse(ok)
        self.assertIn("grader", reason)

    def test_model_says_yes_confirms_pass(self):
        with patch.object(lfm, "_grade_with_cheap_model", return_value=True):
            ok, reason = lfm.quality_gate(GOOD_MINIMAL)
        self.assertTrue(ok)
        self.assertIn("model-graded", reason)

    def test_quality_gate_relies_on_graders_own_fail_soft_contract(self):
        # _grade_with_cheap_model is documented to swallow its own exceptions and return None
        # (see the two tests below) — quality_gate does not double-wrap it. If that contract is
        # ever violated by a future edit, this test making the raise visible is the tripwire.
        with patch.object(lfm, "_grade_with_cheap_model", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                lfm.quality_gate(GOOD_MINIMAL)

    def test_grade_with_cheap_model_swallows_import_error(self):
        with patch.dict(sys.modules, {"model_policy": None, "model_gateway": None}):
            result = lfm._grade_with_cheap_model(GOOD_MINIMAL)
        self.assertIsNone(result)

    def test_grade_with_cheap_model_swallows_network_error(self):
        model_policy = types.SimpleNamespace(choose=lambda *a, **kw: ("local", "x", "why"))
        model_gateway = types.SimpleNamespace(complete=lambda *a, **kw: (_ for _ in ()).throw(OSError("down")))
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}):
            result = lfm._grade_with_cheap_model(GOOD_MINIMAL)
        self.assertIsNone(result)

    def test_grade_with_cheap_model_parses_yes(self):
        model_policy = types.SimpleNamespace(choose=lambda *a, **kw: ("local", "x", "why"))
        model_gateway = types.SimpleNamespace(complete=lambda *a, **kw: {"text": "YES"})
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}):
            result = lfm._grade_with_cheap_model(GOOD_MINIMAL)
        self.assertTrue(result)

    def test_grade_with_cheap_model_parses_no(self):
        model_policy = types.SimpleNamespace(choose=lambda *a, **kw: ("local", "x", "why"))
        model_gateway = types.SimpleNamespace(complete=lambda *a, **kw: {"text": "NO, this is an error banner"})
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}):
            result = lfm._grade_with_cheap_model(GOOD_MINIMAL)
        self.assertFalse(result)

    def test_grade_with_cheap_model_ambiguous_answer_is_none(self):
        model_policy = types.SimpleNamespace(choose=lambda *a, **kw: ("local", "x", "why"))
        model_gateway = types.SimpleNamespace(complete=lambda *a, **kw: {"text": "maybe, hard to say"})
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}):
            result = lfm._grade_with_cheap_model(GOOD_MINIMAL)
        self.assertIsNone(result)


class QuarantineTest(unittest.TestCase):
    def test_quarantine_writes_jsonl_record(self):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.remove(path)
        with patch.object(lfm, "REJECTED_LOG", path):
            lfm._quarantine("bad text", "someproject", "matched failure pattern")
            with open(path) as f:
                row = json.loads(f.readline())
        self.assertEqual(row["source"], "someproject")
        self.assertEqual(row["reason"], "matched failure pattern")
        self.assertEqual(row["text"], "bad text")
        os.remove(path)

    def test_quarantine_never_raises_on_bad_path(self):
        with patch.object(lfm, "REJECTED_LOG", "/nonexistent/definitely/not/writable/x.jsonl"):
            lfm._quarantine("bad text", "proj", "reason")  # must not raise

    def test_quarantine_truncates_long_text(self):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.remove(path)
        with patch.object(lfm, "REJECTED_LOG", path):
            lfm._quarantine("x" * 5000, "proj", "too long")
            with open(path) as f:
                row = json.loads(f.readline())
        self.assertLessEqual(len(row["text"]), 2000)
        os.remove(path)


class RunWiringTest(unittest.TestCase):
    """run() must route rejected distillations to quarantine, not to CLAUDE.md/regression."""

    def test_rejected_text_never_reaches_claude_md(self):
        import tempfile
        repo = tempfile.mkdtemp()
        claude_md = os.path.join(repo, "CLAUDE.md")
        open(claude_md, "w").close()

        db_mock = types.SimpleNamespace(
            select=lambda table, params=None: (
                [{"id": "p1", "name": "proj", "repo_path": repo}] if table == "projects" else
                [{"slug": "s1", "base_branch": "main"}] if table == "tasks" else []
            )
        )
        model_policy = types.SimpleNamespace(choose=lambda *a, **kw: ("local", "x", "why"))
        model_gateway = types.SimpleNamespace(
            complete=lambda *a, **kw: {"text": "You've hit your weekly limit · resets Jul 8 at 6am"})
        with patch.object(lfm, "db", db_mock), \
             patch.object(lfm, "_merged_diff", return_value="diff content"), \
             patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}):
            lfm.run()

        content = open(claude_md).read()
        self.assertNotIn("weekly limit", content)


GOOD_EXTRACTION_JSON = json.dumps({
    "pattern": "Module-level singleton with a threading.Lock-protected pool",
    "files": "runner/db.py, runner/pool.py",
    "why": "avoids threading state through every call chain in a multi-threaded runner",
    "proof": "python3 -m unittest tests.test_pool",
})


class ExtractKnowledgeTest(unittest.TestCase):
    def _mocked_gateway(self, text):
        model_policy = types.SimpleNamespace(choose=lambda *a, **kw: ("local", "x", "why"))
        model_gateway = types.SimpleNamespace(complete=lambda *a, **kw: {"text": text})
        return model_policy, model_gateway

    def test_none_response_stores_nothing(self):
        model_policy, model_gateway = self._mocked_gateway("NONE")
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}):
            result = lfm.extract_knowledge("proj", "slug1", "diff content")
        self.assertFalse(result)

    def test_empty_response_stores_nothing(self):
        model_policy, model_gateway = self._mocked_gateway("")
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}):
            result = lfm.extract_knowledge("proj", "slug1", "diff content")
        self.assertFalse(result)

    def test_non_json_response_is_quarantined_not_stored(self):
        model_policy, model_gateway = self._mocked_gateway("this is not json at all")
        ke = types.SimpleNamespace(extract=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not store")))
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway,
                                       "knowledge_embed": ke}), \
             patch.object(lfm, "_quarantine") as q:
            result = lfm.extract_knowledge("proj", "slug1", "diff content")
        self.assertFalse(result)
        q.assert_called_once()

    def test_missing_required_fields_is_quarantined(self):
        bad = json.dumps({"pattern": "", "files": "a.py", "why": "", "proof": ""})
        model_policy, model_gateway = self._mocked_gateway(bad)
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}), \
             patch.object(lfm, "_quarantine") as q:
            result = lfm.extract_knowledge("proj", "slug1", "diff content")
        self.assertFalse(result)
        q.assert_called_once()

    def test_extraction_matching_failure_pattern_is_rejected(self):
        banner = json.dumps({"pattern": "You've hit your weekly limit, resets Jul 8",
                             "files": "", "why": "rate limited", "proof": ""})
        model_policy, model_gateway = self._mocked_gateway(banner)
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}):
            result = lfm.extract_knowledge("proj", "slug1", "diff content")
        self.assertFalse(result)

    def test_good_extraction_calls_knowledge_embed_extract(self):
        model_policy, model_gateway = self._mocked_gateway(GOOD_EXTRACTION_JSON)
        captured = {}

        def fake_extract(project, title, tags, body):
            captured.update(project=project, title=title, tags=tags, body=body)

        ke = types.SimpleNamespace(extract=fake_extract)
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway,
                                       "knowledge_embed": ke}):
            result = lfm.extract_knowledge("proj", "slug1", "diff content")
        self.assertTrue(result)
        self.assertEqual(captured["project"], "proj")
        self.assertIn("singleton", captured["title"])
        self.assertIn("slug1", captured["tags"])

    def test_gateway_exception_returns_false_without_raising(self):
        model_policy = types.SimpleNamespace(choose=lambda *a, **kw: ("local", "x", "why"))
        model_gateway = types.SimpleNamespace(complete=lambda *a, **kw: (_ for _ in ()).throw(OSError("down")))
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}):
            result = lfm.extract_knowledge("proj", "slug1", "diff content")
        self.assertFalse(result)

    def test_knowledge_embed_extract_failure_returns_false_without_raising(self):
        model_policy, model_gateway = self._mocked_gateway(GOOD_EXTRACTION_JSON)
        ke = types.SimpleNamespace(extract=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db down")))
        with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway,
                                       "knowledge_embed": ke}):
            result = lfm.extract_knowledge("proj", "slug1", "diff content")
        self.assertFalse(result)

    def test_run_calls_extract_knowledge_per_merged_diff_without_blocking_on_failure(self):
        import tempfile
        repo = tempfile.mkdtemp()
        open(os.path.join(repo, "CLAUDE.md"), "w").close()
        db_mock = types.SimpleNamespace(
            select=lambda table, params=None: (
                [{"id": "p1", "name": "proj", "repo_path": repo}] if table == "projects" else
                [{"slug": "s1", "base_branch": "main"}] if table == "tasks" else []
            )
        )
        calls = []
        with patch.object(lfm, "db", db_mock), \
             patch.object(lfm, "_merged_diff", return_value="diff content"), \
             patch.object(lfm, "extract_knowledge", side_effect=RuntimeError("boom"),
                          wraps=None) as ek:
            model_policy = types.SimpleNamespace(choose=lambda *a, **kw: ("local", "x", "why"))
            model_gateway = types.SimpleNamespace(complete=lambda *a, **kw: {"text": ""})
            with patch.dict(sys.modules, {"model_policy": model_policy, "model_gateway": model_gateway}):
                learned = lfm.run()  # must not raise even though extract_knowledge always throws
        ek.assert_called_once()
        self.assertEqual(learned, 0)  # empty distillation text -> nothing learned, but no crash


if __name__ == "__main__":
    unittest.main()
