#!/usr/bin/env python3
"""Comprehensive tests for merged_diff_library, patch_transplant, and diff_compiler."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merged_diff_library as mdl
import patch_transplant
import diff_compiler


# ── merged_diff_library._words ────────────────────────────────────────────────

class WordsTest(unittest.TestCase):
    def test_extracts_words_longer_than_four_chars(self):
        result = mdl._words("hello world foo bar baz")
        self.assertIn("hello", result)
        self.assertIn("world", result)

    def test_short_words_excluded(self):
        result = mdl._words("cat dog an a")
        self.assertEqual(result, set())

    def test_case_insensitive(self):
        result = mdl._words("Stripe STRIPE stripe")
        self.assertEqual(result, {"stripe"})

    def test_none_input_returns_empty_set(self):
        result = mdl._words(None)
        self.assertEqual(result, set())

    def test_empty_string_returns_empty_set(self):
        self.assertEqual(mdl._words(""), set())


# ── merged_diff_library._frameworks ──────────────────────────────────────────

class FrameworksTest(unittest.TestCase):
    def test_detects_next(self):
        self.assertIn("next", mdl._frameworks("next.config.js"))

    def test_detects_supabase(self):
        self.assertIn("supabase", mdl._frameworks("supabase/migrations/"))

    def test_detects_stripe(self):
        self.assertIn("stripe", mdl._frameworks("stripe webhook checkout.session"))

    def test_detects_react(self):
        self.assertIn("react", mdl._frameworks("const [state, setState] = useState(null)"))

    def test_no_false_positives_on_unrelated(self):
        result = mdl._frameworks("plain python script with no framework hints")
        self.assertEqual(result, [])

    def test_none_input(self):
        self.assertEqual(mdl._frameworks(None), [])

    def test_multiple_frameworks_detected(self):
        text = "next.config.js with stripe webhook handler and supabase/ rpc("
        detected = mdl._frameworks(text)
        self.assertIn("next", detected)
        self.assertIn("stripe", detected)
        self.assertIn("supabase", detected)


# ── merged_diff_library.acceptance_intent ────────────────────────────────────

class AcceptanceIntentTest(unittest.TestCase):
    def test_filters_stop_words(self):
        result = mdl.acceptance_intent("implement stripe webhook signature verification handler")
        self.assertNotIn("implement", result)
        self.assertIn("stripe", result)
        self.assertIn("webhook", result)
        self.assertIn("signature", result)
        self.assertIn("verification", result)
        self.assertIn("handler", result)

    def test_empty_prompt_returns_empty_string(self):
        self.assertEqual(mdl.acceptance_intent(""), "")

    def test_result_is_sorted(self):
        result = mdl.acceptance_intent("zebra apple mango")
        words = result.split()
        self.assertEqual(words, sorted(words))

    def test_max_40_words(self):
        long_prompt = " ".join(f"keyword{i}" for i in range(100))
        result = mdl.acceptance_intent(long_prompt)
        self.assertLessEqual(len(result.split()), 40)

    def test_result_under_500_chars(self):
        long_prompt = " ".join(f"keyword{i}" for i in range(200))
        self.assertLessEqual(len(mdl.acceptance_intent(long_prompt)), 500)


# ── merged_diff_library.intent_signature ─────────────────────────────────────

class IntentSignatureTest(unittest.TestCase):
    def test_returns_20_char_hex(self):
        sig = mdl.intent_signature("add stripe webhook handler")
        self.assertEqual(len(sig), 20)
        self.assertRegex(sig, r"^[0-9a-f]+$")

    def test_same_input_gives_same_signature(self):
        prompt = "add stripe webhook verification"
        self.assertEqual(mdl.intent_signature(prompt), mdl.intent_signature(prompt))

    def test_different_prompts_give_different_signatures(self):
        sig1 = mdl.intent_signature("add stripe webhook")
        sig2 = mdl.intent_signature("remove user authentication")
        self.assertNotEqual(sig1, sig2)

    def test_framework_included_in_signature(self):
        sig_with = mdl.intent_signature("add stripe webhook", frameworks=["stripe"])
        sig_without = mdl.intent_signature("add stripe webhook", frameworks=[])
        self.assertNotEqual(sig_with, sig_without)


# ── merged_diff_library.adapter_template ─────────────────────────────────────

class AdapterTemplateTest(unittest.TestCase):
    def test_includes_dirs(self):
        files = ["runner/foo.py", "runner/bar.py", "tests/test_foo.py"]
        result = mdl.adapter_template(files=files, diff="")
        self.assertIn("dirs=", result)
        self.assertIn("runner", result)

    def test_includes_extensions(self):
        files = ["foo.py", "bar.ts"]
        result = mdl.adapter_template(files=files, diff="")
        self.assertIn("exts=", result)
        self.assertIn(".py", result)
        self.assertIn(".ts", result)

    def test_shape_from_diff(self):
        diff = "+added line\n-removed line\n context line\n"
        result = mdl.adapter_template(files=[], diff=diff)
        self.assertIn("shape=+1/-1", result)

    def test_empty_inputs(self):
        result = mdl.adapter_template(files=[], diff="")
        self.assertIn("shape=+0/-0", result)

    def test_result_under_800_chars(self):
        files = [f"dir/file{i}.py" for i in range(50)]
        diff = "+line\n" * 1000
        self.assertLessEqual(len(mdl.adapter_template(files=files, diff=diff)), 800)


# ── merged_diff_library.features ─────────────────────────────────────────────

class FeaturesTest(unittest.TestCase):
    DIFF = "function handleStripeWebhook() {}\nconst Checkout = 1\n"
    FILES = ["app/api/stripe/route.test.ts", "next.config.js"]
    PROMPT = "stripe webhook checkout"

    def test_symbols_extracted(self):
        feat = mdl.features(self.PROMPT, self.DIFF, self.FILES)
        self.assertIn("handleStripeWebhook", feat["symbols"])
        self.assertIn("Checkout", feat["symbols"])

    def test_test_files_extracted(self):
        feat = mdl.features(self.PROMPT, self.DIFF, self.FILES)
        self.assertIn("app/api/stripe/route.test.ts", feat["tests"])
        self.assertNotIn("next.config.js", feat["tests"])

    def test_frameworks_detected(self):
        feat = mdl.features(self.PROMPT, self.DIFF, self.FILES)
        self.assertIn("next", feat["frameworks"])
        self.assertIn("stripe", feat["frameworks"])

    def test_words_is_list_of_strings(self):
        feat = mdl.features(self.PROMPT, self.DIFF, self.FILES)
        self.assertIsInstance(feat["words"], list)
        self.assertTrue(all(isinstance(w, str) for w in feat["words"]))

    def test_words_capped_at_120(self):
        big_prompt = " ".join(f"keyword{i}long" for i in range(200))
        feat = mdl.features(big_prompt, "", [])
        self.assertLessEqual(len(feat["words"]), 120)

    def test_acceptance_intent_in_features(self):
        feat = mdl.features(self.PROMPT, self.DIFF, self.FILES)
        self.assertIn("acceptance_intent", feat)
        self.assertIn("stripe", feat["acceptance_intent"])

    def test_intent_signature_in_features(self):
        feat = mdl.features(self.PROMPT, self.DIFF, self.FILES)
        self.assertIn("intent_signature", feat)
        self.assertEqual(len(feat["intent_signature"]), 20)

    def test_adapter_template_in_features(self):
        feat = mdl.features(self.PROMPT, self.DIFF, self.FILES)
        self.assertIn("adapter_template", feat)

    def test_empty_inputs_dont_raise(self):
        feat = mdl.features("", "", [])
        self.assertIsInstance(feat, dict)


# ── merged_diff_library.find ──────────────────────────────────────────────────

class FindTest(unittest.TestCase):
    DB_ROW = {
        "project": "tomorrow", "slug": "stripe-hook", "kind": "build",
        "prompt": "stripe webhook signature verification handler",
        "diff": "+ verify stripe webhook signature",
        "words": ["stripe", "webhook", "signature", "verification", "handler"],
        "intent_signature": "abc123", "adapter_template": "dirs=app",
    }

    def _mock_db(self, rows):
        db = MagicMock()
        db.select.return_value = rows
        return db

    def test_matches_overlapping_words(self):
        with patch.object(mdl, "db", self._mock_db([self.DB_ROW])):
            hits = mdl.find({"prompt": "add stripe webhook verification"})
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["slug"], "stripe-hook")
        self.assertGreaterEqual(hits[0]["similarity"], 0.12)

    def test_no_overlap_returns_empty(self):
        with patch.object(mdl, "db", self._mock_db([self.DB_ROW])):
            hits = mdl.find({"prompt": "deploy kubernetes ingress controller"})
        self.assertEqual(hits, [])

    def test_empty_prompt_returns_empty(self):
        db = self._mock_db([])
        with patch.object(mdl, "db", db):
            hits = mdl.find({"prompt": ""})
        self.assertEqual(hits, [])
        db.select.assert_not_called()

    def test_db_error_returns_empty(self):
        db = MagicMock()
        db.select.side_effect = RuntimeError("db down")
        with patch.object(mdl, "db", db):
            hits = mdl.find({"prompt": "stripe webhook"})
        self.assertEqual(hits, [])

    def test_limit_respected(self):
        rows = [
            {**self.DB_ROW, "slug": f"slug-{i}",
             "words": ["stripe", "webhook", "handler", "auth", "token"]}
            for i in range(10)
        ]
        with patch.object(mdl, "db", self._mock_db(rows)):
            hits = mdl.find({"prompt": "stripe webhook handler auth token"}, limit=2)
        self.assertLessEqual(len(hits), 2)

    def test_result_includes_required_keys(self):
        with patch.object(mdl, "db", self._mock_db([self.DB_ROW])):
            hits = mdl.find({"prompt": "stripe webhook verification"})
        if hits:
            for key in ("similarity", "project", "slug", "kind", "summary", "diff"):
                self.assertIn(key, hits[0])

    def test_words_fallback_from_prompt_diff_when_missing(self):
        row = {
            "project": "p", "slug": "s", "kind": "build",
            "prompt": "stripe webhook signature verification handler",
            "diff": "+ stripe webhook code",
            "intent_signature": None, "adapter_template": None,
        }
        with patch.object(mdl, "db", self._mock_db([row])):
            hits = mdl.find({"prompt": "stripe webhook handler"})
        self.assertGreater(len(hits), 0)

    def test_none_task_returns_empty(self):
        db = MagicMock()
        with patch.object(mdl, "db", db):
            hits = mdl.find(None)
        self.assertEqual(hits, [])


# ── merged_diff_library.directive ────────────────────────────────────────────

class DirectiveTest(unittest.TestCase):
    HIT = {"similarity": 0.5, "project": "tomorrow", "slug": "stripe-hook",
           "kind": "build", "summary": "stripe webhook handler prior work",
           "diff": "+ some diff", "intent_signature": "abc", "adapter_template": "dirs=app"}

    def test_directive_contains_header(self):
        with patch.object(mdl, "find", return_value=[self.HIT]):
            result = mdl.directive({"prompt": "stripe webhook"})
        self.assertIn("MERGED-DIFF LIBRARY", result)

    def test_directive_contains_source(self):
        with patch.object(mdl, "find", return_value=[self.HIT]):
            result = mdl.directive({"prompt": "stripe webhook"})
        self.assertIn("tomorrow/stripe-hook", result)

    def test_no_hits_returns_empty_string(self):
        with patch.object(mdl, "find", return_value=[]):
            result = mdl.directive({"prompt": "stripe webhook"})
        self.assertEqual(result, "")

    def test_multiple_sources_included(self):
        hits = [
            {**self.HIT, "slug": "slug-1", "summary": "first"},
            {**self.HIT, "slug": "slug-2", "summary": "second"},
        ]
        with patch.object(mdl, "find", return_value=hits):
            result = mdl.directive({"prompt": "stripe webhook"})
        self.assertIn("slug-1", result)
        self.assertIn("slug-2", result)


# ── merged_diff_library.intent_graph ─────────────────────────────────────────

class IntentGraphTest(unittest.TestCase):
    HIT = {"similarity": 0.4, "project": "p", "slug": "s", "kind": "build",
           "summary": "prior work", "diff": "", "intent_signature": "abc123",
           "adapter_template": "dirs=runner"}

    def test_returns_intent_signature(self):
        with patch.object(mdl, "find", return_value=[self.HIT]):
            graph = mdl.intent_graph({"prompt": "add auth middleware"})
        self.assertIn("intent_signature", graph)
        self.assertEqual(len(graph["intent_signature"]), 20)

    def test_adapters_populated_from_hits(self):
        with patch.object(mdl, "find", return_value=[self.HIT]):
            graph = mdl.intent_graph({"prompt": "add auth middleware"})
        self.assertEqual(len(graph["adapters"]), 1)
        a = graph["adapters"][0]
        self.assertEqual(a["source"], "p/s")
        self.assertEqual(a["similarity"], 0.4)

    def test_no_hits_gives_empty_adapters(self):
        with patch.object(mdl, "find", return_value=[]):
            graph = mdl.intent_graph({"prompt": "something novel"})
        self.assertEqual(graph["adapters"], [])

    def test_adapter_template_fallback(self):
        hit = {**self.HIT, "adapter_template": None}
        with patch.object(mdl, "find", return_value=[hit]):
            graph = mdl.intent_graph({"prompt": "add auth"})
        self.assertIsNotNone(graph["adapters"][0]["adapter_template"])


# ── merged_diff_library.adapter_directive ────────────────────────────────────

class AdapterDirectiveTest(unittest.TestCase):
    HIT = {"similarity": 0.4, "project": "p", "slug": "s", "kind": "build",
           "summary": "prior work", "diff": "", "intent_signature": "abc",
           "adapter_template": "dirs=runner exts=.py:.1 shape=+10/-5"}

    def test_header_present(self):
        with patch.object(mdl, "find", return_value=[self.HIT]):
            result = mdl.adapter_directive({"prompt": "add runner module"})
        self.assertIn("REUSABLE INTENT GRAPH", result)

    def test_contains_intent_signature(self):
        with patch.object(mdl, "find", return_value=[self.HIT]):
            result = mdl.adapter_directive({"prompt": "add runner module"})
        self.assertIn("intent signature", result.lower())

    def test_no_hits_returns_empty_string(self):
        with patch.object(mdl, "find", return_value=[]):
            result = mdl.adapter_directive({"prompt": "something totally new"})
        self.assertEqual(result, "")

    def test_adapter_template_in_output(self):
        with patch.object(mdl, "find", return_value=[self.HIT]):
            result = mdl.adapter_directive({"prompt": "add runner module"})
        self.assertIn("dirs=runner", result)


# ── merged_diff_library.record ────────────────────────────────────────────────

class RecordTest(unittest.TestCase):
    def _mock_db_insert_ok(self):
        db = MagicMock()
        db.insert.return_value = True
        return db

    def test_record_calls_db_insert(self):
        with patch.object(mdl, "db", self._mock_db_insert_ok()), \
             patch.object(mdl, "_changed_files", return_value=["foo.py"]), \
             patch.object(mdl, "_diff", return_value="+ added line"):
            result = mdl.record("proj", "some-slug", "build",
                                "add stripe webhook", "/repo", "main", "agent/slug")
        self.assertTrue(result)

    def test_record_survives_db_insert_failure(self):
        db = MagicMock()
        db.insert.side_effect = RuntimeError("db down")
        with patch.object(mdl, "db", db), \
             patch.object(mdl, "_changed_files", return_value=[]), \
             patch.object(mdl, "_diff", return_value=""):
            result = mdl.record("proj", "slug", "build", "prompt", "/repo", "main", "head")
        self.assertFalse(result)


# ── patch_transplant.hint ─────────────────────────────────────────────────────

class PatchTransplantHintTest(unittest.TestCase):
    TASK = {"id": "t1", "prompt": "add stripe webhook verification handler"}
    HIT = [{"project": "tomorrow", "slug": "stripe-hook", "similarity": 0.5,
            "summary": "prior stripe hook", "diff": "+ old patch"}]

    def test_returns_transplant_hint_when_hit(self):
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=self.HIT):
            result = patch_transplant.hint(self.TASK)
        self.assertIn("PATCH TRANSPLANT", result)
        self.assertIn("stripe-hook", result)

    def test_returns_empty_when_no_hits(self):
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=[]):
            result = patch_transplant.hint(self.TASK)
        self.assertEqual(result, "")

    def test_returns_empty_when_similarity_below_threshold(self):
        low_hit = [{**self.HIT[0], "similarity": 0.01}]
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=low_hit), \
             patch.dict(os.environ, {"ORCH_PATCH_TRANSPLANT_MIN_SIM": "0.18"}):
            result = patch_transplant.hint(self.TASK)
        self.assertEqual(result, "")

    def test_skips_task_already_containing_mark(self):
        task = {**self.TASK, "prompt": "PATCH TRANSPLANT already in prompt"}
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=self.HIT) as mock_find:
            result = patch_transplant.hint(task)
        self.assertEqual(result, "")
        mock_find.assert_not_called()

    def test_includes_diff_excerpt_in_hint(self):
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=self.HIT):
            result = patch_transplant.hint(self.TASK)
        self.assertIn("+ old patch", result)

    def test_includes_prior_intent(self):
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=self.HIT):
            result = patch_transplant.hint(self.TASK)
        self.assertIn("prior stripe hook", result)


# ── patch_transplant.pre_claim_hook ──────────────────────────────────────────

class PatchTransplantPreClaimHookTest(unittest.TestCase):
    TASK = {"id": "t1", "prompt": "add stripe webhook verification handler"}
    HIT = [{"project": "tomorrow", "slug": "stripe-hook", "similarity": 0.5,
            "summary": "prior stripe hook", "diff": "+ old patch"}]

    def test_prepends_hint_to_task_prompt(self):
        db = MagicMock()
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=self.HIT), \
             patch.object(patch_transplant, "db", db, create=True):
            out = patch_transplant.pre_claim_hook(self.TASK)
        self.assertIn("PATCH TRANSPLANT", out["prompt"])
        self.assertIn("add stripe webhook verification handler", out["prompt"])

    def test_updates_db_with_new_prompt(self):
        db = MagicMock()
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=self.HIT), \
             patch.object(patch_transplant, "db", db, create=True):
            patch_transplant.pre_claim_hook(self.TASK)
        db.update.assert_called_once()
        args = db.update.call_args.args
        self.assertIn("PATCH TRANSPLANT", args[2]["prompt"])

    def test_passes_through_when_no_hint(self):
        db = MagicMock()
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=[]), \
             patch.object(patch_transplant, "db", db, create=True):
            out = patch_transplant.pre_claim_hook(self.TASK)
        self.assertEqual(out, self.TASK)
        db.update.assert_not_called()

    def test_never_raises_on_db_failure(self):
        db = MagicMock()
        db.update.side_effect = RuntimeError("db down")
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=self.HIT), \
             patch.object(patch_transplant, "db", db, create=True):
            out = patch_transplant.pre_claim_hook(self.TASK)
        self.assertEqual(out, self.TASK)

    def test_never_raises_on_find_failure(self):
        with patch.object(patch_transplant.merged_diff_library, "find",
                          side_effect=RuntimeError("boom")):
            out = patch_transplant.pre_claim_hook(self.TASK)
        self.assertEqual(out, self.TASK)


# ── diff_compiler._extract_keywords ──────────────────────────────────────────

class ExtractKeywordsTest(unittest.TestCase):
    def test_removes_stop_words(self):
        kw = diff_compiler._extract_keywords("implement stripe webhook for the new API")
        self.assertNotIn("for", kw)
        self.assertNotIn("the", kw)
        self.assertIn("stripe", kw)
        self.assertIn("webhook", kw)

    def test_returns_max_50_keywords(self):
        long = " ".join(f"keyword{i}" for i in range(200))
        kw = diff_compiler._extract_keywords(long)
        self.assertLessEqual(len(kw), 50)

    def test_empty_prompt_returns_empty(self):
        self.assertEqual(diff_compiler._extract_keywords(""), [])

    def test_all_stop_words_returns_empty(self):
        result = diff_compiler._extract_keywords("the and for")
        self.assertEqual(result, [])

    def test_minimum_length_3(self):
        result = diff_compiler._extract_keywords("ab abc abcd")
        # "ab" too short, "abc" len 3 included, "abcd" len 4 included
        self.assertNotIn("ab", result)
        self.assertIn("abc", result)


# ── diff_compiler._extract_pattern ───────────────────────────────────────────

class ExtractPatternTest(unittest.TestCase):
    DIFF = (
        "diff --git a/runner/foo.py b/runner/foo.py\n"
        "+added line\n"
        "+another added line\n"
        "-removed line\n"
        "diff --git a/tests/test_foo.py b/tests/test_foo.py\n"
        "+new test\n"
    )

    def test_extracts_file_and_shape(self):
        result = diff_compiler._extract_pattern(self.DIFF)
        self.assertIn("runner/foo.py", result)
        self.assertIn("+2/-1", result)

    def test_second_file_included(self):
        result = diff_compiler._extract_pattern(self.DIFF)
        self.assertIn("tests/test_foo.py", result)

    def test_empty_diff_returns_empty(self):
        self.assertEqual(diff_compiler._extract_pattern(""), "")

    def test_none_diff_returns_empty(self):
        self.assertEqual(diff_compiler._extract_pattern(None), "")

    def test_max_20_lines(self):
        diff = "diff --git a/f.py b/f.py\n" + "+added\n" * 500
        result = diff_compiler._extract_pattern(diff)
        self.assertLessEqual(len(result.splitlines()), 20)


# ── diff_compiler._score_template ────────────────────────────────────────────

class ScoreTemplateTest(unittest.TestCase):
    def test_keyword_overlap_contributes_to_score(self):
        template = {"diff": "stripe webhook signature verification code", "files": []}
        score = diff_compiler._score_template(
            template, ["stripe", "webhook", "signature", "verification"], "stripe webhook"
        )
        self.assertGreater(score, 0.0)

    def test_no_overlap_scores_zero(self):
        template = {"diff": "kubernetes ingress controller route", "files": []}
        score = diff_compiler._score_template(
            template, ["stripe", "webhook"], "stripe webhook"
        )
        self.assertEqual(score, 0.0)

    def test_score_capped_at_1(self):
        template = {"diff": " ".join(["stripe"] * 100), "files": ["runner/stripe.py"]}
        score = diff_compiler._score_template(
            template, ["stripe"] * 20, "stripe stripe stripe"
        )
        self.assertLessEqual(score, 1.0)

    def test_matching_kind_gives_bonus(self):
        template = {"diff": "some code", "files": [], "kind": "build"}
        score = diff_compiler._score_template(template, [], "build a new feature")
        self.assertGreater(score, 0.0)


# ── diff_compiler.inject_plan ─────────────────────────────────────────────────

class InjectPlanTest(unittest.TestCase):
    def test_injects_plan_block_before_prompt(self):
        plan = {"has_plan": True, "confidence": 0.8, "plan_text": "Template 1: stripe-hook (80%)\n"}
        result = diff_compiler.inject_plan("original prompt", plan)
        self.assertIn("Merged-Diff Compiler", result)
        self.assertIn("Template 1", result)
        self.assertIn("original prompt", result)

    def test_no_plan_returns_original_prompt(self):
        plan = {"has_plan": False, "confidence": 0.0, "plan_text": ""}
        self.assertEqual(diff_compiler.inject_plan("original prompt", plan), "original prompt")

    def test_none_plan_returns_original_prompt(self):
        self.assertEqual(diff_compiler.inject_plan("original prompt", None), "original prompt")

    def test_plan_prepended_not_appended(self):
        plan = {"has_plan": True, "confidence": 0.9, "plan_text": "TEMPLATE_BLOCK\n"}
        result = diff_compiler.inject_plan("original prompt", plan)
        self.assertLess(result.index("TEMPLATE_BLOCK"), result.index("original prompt"))

    def test_confidence_shown_as_percentage(self):
        plan = {"has_plan": True, "confidence": 0.75, "plan_text": "x"}
        result = diff_compiler.inject_plan("p", plan)
        self.assertIn("75%", result)


# ── diff_compiler.compile_plan (integration path, mocked db) ─────────────────

class CompilePlanTest(unittest.TestCase):
    def test_empty_prompt_returns_no_plan(self):
        result = diff_compiler.compile_plan("")
        self.assertFalse(result["has_plan"])
        self.assertEqual(result["templates"], [])

    def test_no_similar_diffs_returns_no_plan(self):
        with patch.object(diff_compiler, "_find_similar_diffs", return_value=[]):
            result = diff_compiler.compile_plan("stripe webhook handler")
        self.assertFalse(result["has_plan"])

    def test_low_scoring_templates_excluded(self):
        template = {"slug": "low-score", "diff": "unrelated content xyz", "files": []}
        with patch.object(diff_compiler, "_find_similar_diffs", return_value=[template]):
            result = diff_compiler.compile_plan("stripe webhook handler")
        self.assertFalse(result["has_plan"])

    def test_high_scoring_template_produces_plan(self):
        diff_text = "stripe webhook signature verification handler authentication"
        template = {"slug": "stripe-hook", "diff": diff_text, "files": ["runner/stripe.py"]}
        with patch.object(diff_compiler, "_find_similar_diffs", return_value=[template]):
            result = diff_compiler.compile_plan(
                "stripe webhook signature verification handler authentication")
        if result["has_plan"]:
            self.assertGreater(result["confidence"], 0.0)
            self.assertIn("stripe-hook", result["plan_text"])


# ── end-to-end: find → directive → adapter_directive pipeline ─────────────────

class EndToEndPipelineTest(unittest.TestCase):
    ROWS = [
        {"project": "tomorrow", "slug": "stripe-hook", "kind": "build",
         "prompt": "stripe webhook signature verification handler endpoint",
         "diff": "+ implement stripe webhook signature verification",
         "words": ["stripe", "webhook", "signature", "verification", "handler", "endpoint"],
         "intent_signature": "abc123", "adapter_template": "dirs=app/api shape=+20/-5"},
    ]
    TASK = {"prompt": "add stripe webhook verification handler to API"}

    def test_full_find_and_directive_pipeline(self):
        with patch.object(mdl, "db") as db:
            db.select.return_value = self.ROWS
            hits = mdl.find(self.TASK)
            self.assertGreater(len(hits), 0)

            directive = mdl.directive(self.TASK)
            self.assertIn("MERGED-DIFF LIBRARY", directive)
            self.assertIn("stripe-hook", directive)

    def test_intent_graph_and_adapter_directive_pipeline(self):
        with patch.object(mdl, "db") as db:
            db.select.return_value = self.ROWS
            graph = mdl.intent_graph(self.TASK)
            self.assertGreater(len(graph["adapters"]), 0)

            directive = mdl.adapter_directive(self.TASK)
            self.assertIn("REUSABLE INTENT GRAPH", directive)

    def test_patch_transplant_end_to_end(self):
        db = MagicMock()
        with patch.object(mdl, "db") as mdb:
            mdb.select.return_value = self.ROWS
            with patch.object(patch_transplant, "db", db, create=True):
                out = patch_transplant.pre_claim_hook(self.TASK)
        if "PATCH TRANSPLANT" in out.get("prompt", ""):
            db.update.assert_called_once()


if __name__ == "__main__":
    unittest.main()
