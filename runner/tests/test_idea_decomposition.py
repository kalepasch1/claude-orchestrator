#!/usr/bin/env python3
"""Tests for idea_decomposer.py — one-liner -> valid task graph."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import idea_decomposer as id_


SAMPLE_MODEL_RESPONSE = {
    "spec": "A Stripe payment checkout so users can pay for subscriptions directly on the site.",
    "tasks": [
        {
            "title": "add-stripe-sdk-dependency",
            "prompt": "Add stripe==7.x to requirements.txt and install it.",
            "deps": [],
            "acceptance_test": "pip show stripe exits 0 and the package version matches requirements.txt.",
        },
        {
            "title": "create-checkout-session-endpoint",
            "prompt": "Create POST /api/checkout in web/server/routes.py that calls stripe.checkout.Session.create and returns session.url.",
            "deps": ["add-stripe-sdk-dependency"],
            "acceptance_test": "POST /api/checkout returns 200 with a non-empty url field.",
        },
        {
            "title": "add-checkout-button-to-pricing-page",
            "prompt": "Add a 'Buy now' button in web/pages/pricing.tsx that POSTs to /api/checkout and redirects to session.url.",
            "deps": ["create-checkout-session-endpoint"],
            "acceptance_test": "Clicking 'Buy now' on /pricing redirects the browser to a stripe.com/pay/ URL.",
        },
    ],
}


def _model_ok(_prov, _model, _prompt):
    return {"text": __import__("json").dumps(SAMPLE_MODEL_RESPONSE), "cost_usd": 0.0}


def _model_garbage(_prov, _model, _prompt):
    return {"text": "Sure! Here is your plan: ```python print('hello') ```", "cost_usd": 0.0}


def _model_error(_prov, _model, _prompt):
    raise RuntimeError("provider offline")


class TestDecomposeHappyPath(unittest.TestCase):

    def _run(self, idea="add Stripe payment checkout to the app"):
        with patch.object(id_, "model_gateway") as mg, patch.object(id_, "db") as mdb:
            mg.complete.side_effect = _model_ok
            mdb.select.return_value = []
            mdb.insert.return_value = [{"id": "new"}]
            return id_.decompose(idea, project_id="proj-1", enqueue=False), mg, mdb

    def test_returns_spec(self):
        result, *_ = self._run()
        self.assertIn("Stripe", result["spec"])

    def test_returns_three_tasks(self):
        result, *_ = self._run()
        self.assertEqual(len(result["tasks"]), 3)

    def test_tasks_have_required_fields(self):
        result, *_ = self._run()
        for t in result["tasks"]:
            self.assertIn("title", t)
            self.assertIn("prompt", t)
            self.assertIn("deps", t)
            self.assertIn("acceptance_test", t)

    def test_dag_has_no_errors(self):
        result, *_ = self._run()
        self.assertEqual(result["errors"], [])

    def test_first_task_has_no_deps(self):
        result, *_ = self._run()
        self.assertEqual(result["tasks"][0]["deps"], [])

    def test_second_task_depends_on_first(self):
        result, *_ = self._run()
        self.assertIn("add-stripe-sdk-dependency", result["tasks"][1]["deps"])

    def test_third_task_depends_on_second(self):
        result, *_ = self._run()
        self.assertIn("create-checkout-session-endpoint", result["tasks"][2]["deps"])

    def test_titles_are_slugified(self):
        result, *_ = self._run()
        for t in result["tasks"]:
            self.assertRegex(t["title"], r"^[a-z0-9-]+$")

    def test_enqueued_zero_when_not_requested(self):
        result, *_ = self._run()
        self.assertEqual(result["enqueued"], 0)


class TestDecomposeEnqueue(unittest.TestCase):

    def test_inserts_tasks_when_project_id_given(self):
        inserts = []
        with patch.object(id_, "model_gateway") as mg, patch.object(id_, "db") as mdb:
            mg.complete.side_effect = _model_ok
            mdb.select.return_value = []
            mdb.insert.side_effect = lambda table, row: inserts.append((table, row)) or [{"id": "x"}]
            result = id_.decompose("add Stripe checkout", project_id="proj-1", enqueue=True)
        self.assertEqual(result["enqueued"], 3)
        self.assertTrue(all(t == "tasks" for t, _ in inserts))

    def test_skips_existing_tasks(self):
        with patch.object(id_, "model_gateway") as mg, patch.object(id_, "db") as mdb:
            mg.complete.side_effect = _model_ok
            mdb.select.return_value = [{"id": "existing"}]  # all slugs already exist
            result = id_.decompose("add Stripe checkout", project_id="proj-1", enqueue=True)
        self.assertEqual(result["enqueued"], 0)
        mdb.insert.assert_not_called()

    def test_no_enqueue_when_project_id_empty(self):
        with patch.object(id_, "model_gateway") as mg, patch.object(id_, "db") as mdb:
            mg.complete.side_effect = _model_ok
            mdb.select.return_value = []
            result = id_.decompose("add Stripe checkout", project_id="", enqueue=True)
        self.assertEqual(result["enqueued"], 0)
        mdb.insert.assert_not_called()

    def test_db_error_is_swallowed(self):
        with patch.object(id_, "model_gateway") as mg, patch.object(id_, "db") as mdb:
            mg.complete.side_effect = _model_ok
            mdb.select.return_value = []
            mdb.insert.side_effect = RuntimeError("db down")
            result = id_.decompose("add Stripe checkout", project_id="proj-1", enqueue=True)
        self.assertEqual(result["enqueued"], 0)
        self.assertEqual(result["errors"], [])  # DAG still valid


class TestDecomposeEdgeCases(unittest.TestCase):

    def test_empty_idea_returns_error(self):
        result = id_.decompose("")
        self.assertIn("empty", result["errors"][0])
        self.assertEqual(result["tasks"], [])

    def test_none_idea_returns_error(self):
        result = id_.decompose(None)
        self.assertIn("empty", result["errors"][0])

    def test_model_offline_returns_error(self):
        with patch.object(id_, "model_gateway") as mg, patch.object(id_, "model_policy") as mp:
            mg.complete.side_effect = _model_error
            mp.choose.return_value = ("claude", "claude-haiku-4-5-20251001", "fallback")
            result = id_.decompose("build something", enqueue=False)
        self.assertGreater(len(result["errors"]), 0)
        self.assertEqual(result["tasks"], [])

    def test_model_returns_garbage_json(self):
        with patch.object(id_, "model_gateway") as mg, patch.object(id_, "model_policy") as mp:
            mg.complete.side_effect = _model_garbage
            mp.choose.return_value = ("claude", "claude-haiku-4-5-20251001", "fallback")
            result = id_.decompose("build something", enqueue=False)
        self.assertGreater(len(result["errors"]), 0)

    def test_forward_dep_detected(self):
        bad_response = {
            "spec": "s",
            "tasks": [
                {"title": "task-a", "prompt": "do a", "deps": ["task-b"], "acceptance_test": "x"},
                {"title": "task-b", "prompt": "do b", "deps": [], "acceptance_test": "y"},
            ],
        }
        with patch.object(id_, "model_gateway") as mg, patch.object(id_, "model_policy") as mp:
            mg.complete.return_value = {"text": __import__("json").dumps(bad_response)}
            mp.choose.return_value = ("claude", "claude-haiku-4-5-20251001", "fallback")
            result = id_.decompose("build something", enqueue=False)
        self.assertTrue(any("dep" in e for e in result["errors"]))

    def test_too_many_tasks_are_capped(self):
        many = {
            "spec": "big idea",
            "tasks": [
                {"title": f"task-{i}", "prompt": f"do {i}", "deps": [], "acceptance_test": "ok"}
                for i in range(20)
            ],
        }
        with patch.object(id_, "model_gateway") as mg, patch.object(id_, "model_policy") as mp:
            mg.complete.return_value = {"text": __import__("json").dumps(many)}
            mp.choose.return_value = ("claude", "claude-haiku-4-5-20251001", "fallback")
            result = id_.decompose("build something", enqueue=False)
        self.assertLessEqual(len(result["tasks"]), id_.MAX_TASKS)

    def test_idea_long_enough_is_truncated_not_errored(self):
        long_idea = "x" * 5000
        with patch.object(id_, "model_gateway") as mg, patch.object(id_, "model_policy") as mp:
            mg.complete.side_effect = _model_ok
            mp.choose.return_value = ("claude", "claude-haiku-4-5-20251001", "fallback")
            result = id_.decompose(long_idea, enqueue=False)
        # model was called (truncation happened silently)
        mg.complete.assert_called_once()
        called_prompt = mg.complete.call_args[0][2]
        self.assertLessEqual(len(called_prompt), 10000)  # prompt was bounded


class TestValidateDag(unittest.TestCase):

    def test_valid_linear_chain(self):
        tasks = [
            {"title": "a", "prompt": "p", "deps": [], "acceptance_test": "t"},
            {"title": "b", "prompt": "p", "deps": ["a"], "acceptance_test": "t"},
            {"title": "c", "prompt": "p", "deps": ["b"], "acceptance_test": "t"},
        ]
        self.assertEqual(id_._validate_dag(tasks), [])

    def test_missing_title_flagged(self):
        tasks = [{"title": "", "prompt": "p", "deps": [], "acceptance_test": "t"}]
        errs = id_._validate_dag(tasks)
        self.assertTrue(any("missing title" in e for e in errs))

    def test_missing_prompt_flagged(self):
        tasks = [{"title": "a", "prompt": "", "deps": [], "acceptance_test": "t"}]
        errs = id_._validate_dag(tasks)
        self.assertTrue(any("missing prompt" in e for e in errs))

    def test_undefined_dep_flagged(self):
        tasks = [{"title": "a", "prompt": "p", "deps": ["ghost"], "acceptance_test": "t"}]
        errs = id_._validate_dag(tasks)
        self.assertTrue(any("ghost" in e for e in errs))

    def test_empty_tasks_valid(self):
        self.assertEqual(id_._validate_dag([]), [])


class TestSlugify(unittest.TestCase):

    def test_basic(self):
        self.assertEqual(id_._slugify("Add Stripe Checkout"), "add-stripe-checkout")

    def test_special_chars_removed(self):
        self.assertEqual(id_._slugify("foo!bar@baz"), "foo-bar-baz")

    def test_truncated_at_60(self):
        self.assertEqual(len(id_._slugify("a" * 100)), 60)

    def test_empty_returns_task(self):
        self.assertEqual(id_._slugify(""), "task")


if __name__ == "__main__":
    unittest.main()
