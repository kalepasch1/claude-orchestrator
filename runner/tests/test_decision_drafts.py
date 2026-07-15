#!/usr/bin/env python3
"""
test_decision_drafts.py - unit tests for decision_drafts.py

Tests:
  1. Directive validation (valid/invalid)
  2. Prompt template substitution
  3. Artifact type inference
  4. Draft generation (with mock claude_cli)
  5. Decision storage
  6. Poll pending decisions

Run: cd runner && python3 -m pytest tests/test_decision_drafts.py -v
"""
import os, sys, json, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decision_drafts as decision_engine


class TestDecisionEngine(unittest.TestCase):
    """Unit tests for decision_engine module."""

    def test_valid_directives(self):
        """Test that all expected directives exist."""
        expected = {"negotiate", "file", "draft", "review", "escalate"}
        actual = set(decision_engine.DIRECTIVE_PROMPTS.keys())
        self.assertEqual(actual, expected)

    def test_all_prompts_have_context_placeholder(self):
        """Test that all directive prompts contain {context} placeholder."""
        for directive, prompt in decision_engine.DIRECTIVE_PROMPTS.items():
            self.assertIn("{context}", prompt,
                         f"Directive '{directive}' prompt missing {{context}} placeholder")

    def test_infer_artifact_type_negotiate(self):
        """Test artifact type inference for negotiate directive."""
        result = decision_engine._infer_artifact_type("negotiate", "")
        self.assertEqual(result, "counter-email")

    def test_infer_artifact_type_file_legal(self):
        """Test artifact type inference for file directive with legal context."""
        result = decision_engine._infer_artifact_type("file", "legal agreement")
        self.assertEqual(result, "legal-filing")

    def test_infer_artifact_type_file_generic(self):
        """Test artifact type inference for file directive without legal context."""
        result = decision_engine._infer_artifact_type("file", "project docs")
        self.assertEqual(result, "filing-memo")

    def test_infer_artifact_type_file_permit(self):
        """Test artifact type inference for file directive with permit context."""
        result = decision_engine._infer_artifact_type("file", "permit application")
        self.assertEqual(result, "legal-filing")

    def test_infer_artifact_type_escalate(self):
        """Test artifact type inference for escalate directive."""
        result = decision_engine._infer_artifact_type("escalate", "")
        self.assertEqual(result, "escalation-notice")

    def test_infer_artifact_type_review(self):
        """Test artifact type inference for review directive."""
        result = decision_engine._infer_artifact_type("review", "")
        self.assertEqual(result, "review-memo")

    def test_infer_artifact_type_default(self):
        """Test artifact type inference defaults to document."""
        result = decision_engine._infer_artifact_type("unknown", "")
        self.assertEqual(result, "document")

    def test_generate_draft_invalid_directive(self):
        """Test that invalid directive raises ValueError."""
        with self.assertRaises(ValueError):
            decision_engine.generate_draft("invalid_directive", "context")

    @patch('decision_drafts.claude_cli.run')
    def test_generate_draft_negotiate(self, mock_run):
        """Test draft generation for negotiate directive."""
        mock_run.return_value = {
            "text": "Dear Mr. Smith,\n\nWe propose...",
            "input_tokens": 100,
            "output_tokens": 250,
            "cost_usd": 0.002,
            "raw": {"total_cost_usd": 0.002}
        }

        result = decision_engine.generate_draft(
            "negotiate",
            {"parties": "Acme Corp", "terms": "pricing"},
            approval_id="test-id"
        )

        self.assertEqual(result["artifact_type"], "counter-email")
        self.assertEqual(result["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(result["input_tokens"], 100)
        self.assertEqual(result["output_tokens"], 250)
        self.assertAlmostEqual(result["cost_usd"], 0.002, places=4)
        self.assertIn("Dear Mr. Smith", result["draft"])

    @patch('decision_drafts.claude_cli.run')
    def test_generate_draft_file_with_dict_context(self, mock_run):
        """Test draft generation for file directive with dict context."""
        mock_run.return_value = {
            "text": "TO: City of San Francisco\nFROM: Acme Inc.\n\nFiling memo...",
            "input_tokens": 150,
            "output_tokens": 300,
            "cost_usd": 0.0025,
            "raw": None
        }

        context = {
            "filing_type": "business_license",
            "entity": "Acme Inc",
            "jurisdiction": "San Francisco"
        }

        result = decision_engine.generate_draft("file", context)

        self.assertEqual(result["artifact_type"], "filing-memo")
        self.assertIn("TO:", result["draft"])
        # Verify the prompt was called with JSON-encoded context
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        prompt = call_args[0][0]
        self.assertIn("business_license", prompt)

    @patch('decision_drafts.claude_cli.run')
    def test_generate_draft_with_string_context(self, mock_run):
        """Test draft generation with plain string context."""
        mock_run.return_value = {
            "text": "Draft content here.",
            "input_tokens": 50,
            "output_tokens": 100,
            "cost_usd": 0.001,
            "raw": None
        }

        result = decision_engine.generate_draft("review", "We need to review the proposal")

        self.assertEqual(result["artifact_type"], "review-memo")
        self.assertIn("Draft content", result["draft"])

    @patch('decision_drafts.claude_cli.run')
    def test_generate_draft_empty_context(self, mock_run):
        """Test draft generation handles empty context gracefully."""
        mock_run.return_value = {
            "text": "Generic draft.",
            "input_tokens": 30,
            "output_tokens": 80,
            "cost_usd": 0.0008,
            "raw": None
        }

        result = decision_engine.generate_draft("draft", None)

        self.assertIn("Generic draft", result["draft"])
        # Verify prompt includes the "(no context provided)" fallback
        mock_run.assert_called_once()
        prompt = mock_run.call_args[0][0]
        self.assertIn("(no context provided)", prompt)

    @patch('decision_drafts.db.insert')
    @patch('decision_drafts.generate_draft')
    def test_store_decision_with_autogenerated_draft(self, mock_gen, mock_insert):
        """Test storing a decision with auto-generated draft."""
        mock_gen.return_value = {
            "draft": "Generated draft text.",
            "model": "claude-haiku-4-5-20251001",
            "input_tokens": 100,
            "output_tokens": 200,
            "cost_usd": 0.002,
            "artifact_type": "counter-email"
        }
        mock_insert.return_value = [{"id": "dec-123", "project": "acme"}]

        result = decision_engine.store_decision(
            project="acme",
            directive="negotiate",
            context={"parties": "Partner Inc", "terms": "pricing"},
            approval_id="app-456"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "dec-123")

        # Verify insert was called with correct shape
        mock_insert.assert_called_once()
        call_args = mock_insert.call_args
        self.assertEqual(call_args[0][0], "decision_processes")
        inserted_row = call_args[0][1]
        self.assertEqual(inserted_row["project"], "acme")
        self.assertEqual(inserted_row["directive"], "negotiate")
        self.assertEqual(inserted_row["approval_id"], "app-456")
        self.assertEqual(inserted_row["draft"], "Generated draft text.")
        self.assertEqual(inserted_row["status"], "draft")

    @patch('decision_drafts.db.insert')
    def test_store_decision_with_provided_draft(self, mock_insert):
        """Test storing a decision with pre-generated draft data."""
        mock_insert.return_value = [{"id": "dec-789"}]

        draft_data = {
            "draft": "Pre-drafted content",
            "model": "claude-haiku-4-5-20251001",
            "input_tokens": 80,
            "output_tokens": 150,
            "cost_usd": 0.0015,
            "artifact_type": "memo"
        }

        result = decision_engine.store_decision(
            project="test_proj",
            directive="file",
            context="Simple context",
            draft_data=draft_data
        )

        self.assertIsNotNone(result)

        # Verify the provided draft was used
        call_args = mock_insert.call_args
        inserted_row = call_args[0][1]
        self.assertEqual(inserted_row["draft"], "Pre-drafted content")
        self.assertEqual(inserted_row["draft_tokens_in"], 80)
        self.assertEqual(inserted_row["draft_tokens_out"], 150)

    @patch('decision_drafts.db.insert')
    def test_store_decision_with_dict_context(self, mock_insert):
        """Test storing a decision with dict context."""
        mock_insert.return_value = [{"id": "dec-dict"}]

        context_dict = {
            "title": "Partner Agreement",
            "parties": "Company A and Company B",
            "terms": "revenue sharing"
        }

        draft = {"draft": "Negotiation draft", "model": "test-model",
                 "input_tokens": 1, "output_tokens": 1, "cost_usd": 0}
        with patch.object(decision_engine, "generate_draft", return_value=draft):
            decision_engine.store_decision(
                project="test",
                directive="negotiate",
                context=context_dict
            )

        call_args = mock_insert.call_args
        inserted_row = call_args[0][1]

        # Verify context is JSON-encoded
        self.assertIsInstance(inserted_row["context"], str)
        parsed_context = json.loads(inserted_row["context"])
        self.assertEqual(parsed_context["title"], "Partner Agreement")

    @patch('decision_drafts.db.select')
    @patch('decision_drafts.db.insert')
    def test_poll_pending_no_approvals(self, mock_insert, mock_select):
        """Test poll_pending with no approvals."""
        mock_select.side_effect = [
            [],  # No approved approvals
        ]

        result = decision_engine.poll_pending()

        self.assertEqual(result, [])
        mock_insert.assert_not_called()

    @patch('decision_drafts.db.select')
    @patch('decision_drafts.db.insert')
    def test_poll_pending_with_directive(self, mock_insert, mock_select):
        """Test poll_pending finds and processes directives."""
        approval = {
            "id": "app-1",
            "project": "acme",
            "title": "Counter-offer negotiation",
            "command": "negotiate --with partner",
            "detail": "Terms: $50k annual, 20% equity",
            "status": "approved"
        }

        def select_side_effect(*args, **kwargs):
            if "approvals" in args[0]:
                return [approval]
            elif "decision_processes" in args[0]:
                return []
            return []

        mock_select.side_effect = select_side_effect
        mock_insert.return_value = [{"id": "dec-123"}]

        draft = {"draft": "Negotiation draft", "model": "test-model",
                 "input_tokens": 1, "output_tokens": 1, "cost_usd": 0}
        with patch.object(decision_engine, "generate_draft", return_value=draft):
            result = decision_engine.poll_pending()

        self.assertEqual(len(result), 1)
        # Note: mock_insert is called multiple times (usage_meter, then decision_processes)
        # Verify that at least one call is to decision_processes table
        calls = mock_insert.call_args_list
        decision_calls = [c for c in calls if c[0][0] == "decision_processes"]
        self.assertEqual(len(decision_calls), 1)

        # Verify the decision was created with the right directive
        inserted_row = decision_calls[0][0][1]
        self.assertEqual(inserted_row["directive"], "negotiate")

    @patch('decision_drafts.db.select')
    def test_poll_pending_skips_already_processed(self, mock_select):
        """Test poll_pending skips approvals already in decision_processes."""
        approval = {
            "id": "app-2",
            "project": "acme",
            "command": "file --legal",
            "detail": "Filing memo"
        }

        def select_side_effect(*args, **kwargs):
            if "approvals" in args[0]:
                return [approval]
            elif "decision_processes" in args[0]:
                return [{"id": "dec-existing"}]  # Already processed
            return []

        mock_select.side_effect = select_side_effect

        with patch('decision_drafts.db.insert') as mock_insert:
            result = decision_engine.poll_pending()
            self.assertEqual(len(result), 0)
            mock_insert.assert_not_called()

    @patch('decision_drafts.db.select')
    def test_poll_pending_no_directive_in_command(self, mock_select):
        """Test poll_pending ignores approvals without recognizable directives."""
        approval = {
            "id": "app-3",
            "project": "acme",
            "title": "Regular approval",
            "command": "approve --standard",
            "detail": "Some detail"
        }

        def select_side_effect(*args, **kwargs):
            if "approvals" in args[0]:
                return [approval]
            elif "decision_processes" in args[0]:
                return []
            return []

        mock_select.side_effect = select_side_effect

        with patch('decision_drafts.db.insert') as mock_insert:
            result = decision_engine.poll_pending()
            self.assertEqual(len(result), 0)
            mock_insert.assert_not_called()


class TestDecisionEngineIntegration(unittest.TestCase):
    """Integration tests (require live DB)."""

    def test_generate_draft_needs_api(self):
        """Verify generate_draft needs API access (integration test)."""
        # This test documents that generate_draft requires a live API call.
        # In CI/test environments without ANTHROPIC_API_KEY, it will fail gracefully.
        # To run this: export ANTHROPIC_API_KEY=sk-... and run with --integration
        self.skipTest("Requires live Claude API (set ANTHROPIC_API_KEY to run)")


class TestParallelProvider(unittest.TestCase):
    """Unit tests for parallel_provider module."""

    @patch('parallel_provider.mg.complete')
    def test_parallel_complete_basic(self, mock_complete):
        """Test parallel_complete with mocked provider calls."""
        import parallel_provider

        # Mock two providers returning results
        mock_complete.side_effect = [
            {"text": '{"verdict":"pass","score":8}', "cost_usd": 0.01, "provider": "claude", "model": "haiku"},
            {"text": '{"verdict":"pass","score":7}', "cost_usd": 0.005, "provider": "google", "model": "gemini"},
        ]

        result = parallel_provider.parallel_complete(
            ["claude", "google"],
            ["claude-haiku-4-5-20251001", "gemini-2.0-flash"],
            "Test prompt"
        )

        self.assertIn("text", result)
        self.assertIn("provider", result)
        self.assertIn("model", result)
        self.assertIn("cost_usd", result)
        self.assertIn("all_results", result)
        self.assertIsNotNone(result["text"])

    @patch('parallel_provider.mg.complete')
    def test_parallel_complete_scoring(self, mock_complete):
        """Test result scoring logic."""
        import parallel_provider

        # Provider 1: longer, detailed response
        detailed = '{"verdict":"pass","score":8,"confidence":85,"notes":"very detailed analysis"}'
        # Provider 2: shorter response
        short = '{"verdict":"pass","score":6}'

        mock_complete.side_effect = [
            {"text": detailed, "cost_usd": 0.01, "provider": "claude", "model": "haiku"},
            {"text": short, "cost_usd": 0.005, "provider": "google", "model": "gemini"},
        ]

        result = parallel_provider.parallel_complete(
            ["claude", "google"],
            ["claude-haiku-4-5-20251001", "gemini-2.0-flash"],
            "Test prompt"
        )

        # More detailed result should win
        self.assertEqual(result["provider"], "claude")
        self.assertGreater(result["score"], 5)

    @patch('parallel_provider.mg.complete')
    def test_parallel_complete_provider_error(self, mock_complete):
        """Test graceful handling when one provider fails."""
        import parallel_provider

        mock_complete.side_effect = [
            {"text": '{"verdict":"pass","score":8}', "cost_usd": 0.01, "provider": "claude", "model": "haiku"},
            {"text": "", "cost_usd": 0, "provider": "google", "model": "gemini", "error": "timeout"},
        ]

        result = parallel_provider.parallel_complete(
            ["claude", "google"],
            ["claude-haiku-4-5-20251001", "gemini-2.0-flash"],
            "Test prompt"
        )

        # Should use the successful result
        self.assertEqual(result["provider"], "claude")
        self.assertIn("text", result)
        self.assertEqual(len(result["all_results"]), 2)

    def test_parallel_complete_empty_providers(self):
        """Test parallel_complete with no providers."""
        import parallel_provider

        result = parallel_provider.parallel_complete([], [], "prompt")
        self.assertEqual(result["provider"], "none")
        self.assertIn("error", result)

    def test_parallel_complete_mismatched_lengths(self):
        """Test parallel_complete with mismatched provider/model lists."""
        import parallel_provider

        result = parallel_provider.parallel_complete(
            ["claude"],
            ["model1", "model2"],
            "prompt"
        )
        self.assertEqual(result["provider"], "none")
        self.assertIn("error", result)
        self.assertIn("mismatch", result["error"])

    @patch('parallel_provider.mg.complete')
    def test_score_result_heuristics(self, mock_complete):
        """Test scoring heuristics for result quality."""
        import parallel_provider

        # Test the internal _score_result function
        result1 = {"text": '{"confidence": 85, "detailed": "very long analysis"}' + " " * 400}
        score1 = parallel_provider._score_result(result1)

        result2 = {"text": "short"}
        score2 = parallel_provider._score_result(result2)

        # Longer, more detailed result should score higher
        self.assertGreater(score1, score2)

    @patch('parallel_provider.mg.complete')
    def test_parallel_complete_cost_aggregation(self, mock_complete):
        """Test that costs are properly aggregated."""
        import parallel_provider

        mock_complete.side_effect = [
            {"text": '{"verdict":"pass"}', "cost_usd": 0.01, "provider": "claude", "model": "haiku"},
            {"text": '{"verdict":"pass"}', "cost_usd": 0.005, "provider": "google", "model": "gemini"},
            {"text": '{"verdict":"pass"}', "cost_usd": 0.002, "provider": "deepseek", "model": "chat"},
        ]

        result = parallel_provider.parallel_complete(
            ["claude", "google", "deepseek"],
            ["haiku", "gemini", "deepseek-chat"],
            "Test prompt"
        )

        # Total cost should be sum of all
        self.assertAlmostEqual(result["cost_usd"], 0.017, places=3)


class TestJudgeParallel(unittest.TestCase):
    """Unit tests for judge.py parallel mode."""

    @patch('parallel_provider.parallel_complete')
    def test_review_parallel_basic(self, mock_parallel):
        """Test review with parallel enabled."""
        import judge

        mock_parallel.return_value = {
            "text": '{"verdict":"pass","score":8,"notes":"good","legal_counsel_required":false,"legal_risk":""}',
            "provider": "claude",
            "model": "haiku",
            "score": 8.0,
            "cost_usd": 0.01,
            "all_results": [
                {
                    "provider": "claude",
                    "model": "haiku",
                    "text": '{"verdict":"pass","score":8,"notes":"good","legal_counsel_required":false,"legal_risk":""}',
                    "cost_usd": 0.01,
                    "score": 8.0,
                    "winner": True
                }
            ]
        }

        result = judge.review("Test task", "diff content", use_parallel=True)

        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result.get("parallel"))
        self.assertIn("synthesis_score", result)

    @patch('model_gateway.complete')
    def test_review_sequential_fallback(self, mock_complete):
        """Test that sequential mode still works (default behavior)."""
        import judge

        mock_complete.return_value = {
            "text": '{"verdict":"pass","score":8,"notes":"ok","legal_counsel_required":false,"legal_risk":""}',
            "cost_usd": 0.01
        }

        result = judge.review("Test task", "diff content", use_parallel=False)

        self.assertEqual(result["verdict"], "pass")
        self.assertNotIn("parallel", result)  # sequential doesn't set this

    @patch('parallel_provider.parallel_complete')
    @patch('model_gateway.complete')
    def test_review_parallel_fallback_on_error(self, mock_seq, mock_parallel):
        """Test that review falls back to sequential if parallel fails."""
        import judge

        mock_parallel.side_effect = Exception("parallel failed")
        mock_seq.return_value = {
            "text": '{"verdict":"pass","score":7,"notes":"ok","legal_counsel_required":false,"legal_risk":""}',
            "cost_usd": 0.01
        }

        result = judge.review("Test task", "diff content", use_parallel=True)

        # Should fall back to sequential
        self.assertEqual(result["verdict"], "pass")
        # Verify sequential was called as fallback
        mock_seq.assert_called()

    @patch('parallel_provider.parallel_complete')
    def test_review_parallel_with_legal_risk(self, mock_parallel):
        """Test parallel review with legal risk assessment."""
        import judge

        mock_parallel.return_value = {
            "text": '{"verdict":"fail","score":3,"notes":"legal risk","legal_counsel_required":true,"legal_risk":"money transmission"}',
            "provider": "google",
            "model": "gemini",
            "score": 7.0,
            "cost_usd": 0.015,
            "all_results": [
                {
                    "provider": "google",
                    "model": "gemini",
                    "text": '{"verdict":"fail","score":3,"notes":"risk","legal_counsel_required":true,"legal_risk":"money transmission"}',
                    "cost_usd": 0.015,
                    "score": 7.0,
                    "winner": True
                }
            ]
        }

        result = judge.review("Legal task", "diff", use_parallel=True)

        self.assertEqual(result["verdict"], "fail")
        self.assertTrue(result.get("legal_counsel_required"))
        self.assertIn("money transmission", result.get("legal_risk", ""))

    @patch('parallel_provider.parallel_complete')
    def test_review_parallel_panel_aggregation(self, mock_parallel):
        """Test that parallel results include all panel members."""
        import judge

        mock_parallel.return_value = {
            "text": '{"verdict":"pass","score":8,"notes":"good","legal_counsel_required":false,"legal_risk":""}',
            "provider": "claude",
            "model": "haiku",
            "score": 8.0,
            "cost_usd": 0.02,
            "all_results": [
                {
                    "provider": "claude",
                    "model": "haiku",
                    "text": '{"verdict":"pass","score":8,"notes":"good","legal_counsel_required":false,"legal_risk":""}',
                    "cost_usd": 0.01,
                    "score": 8.0,
                    "winner": True
                },
                {
                    "provider": "google",
                    "model": "gemini",
                    "text": '{"verdict":"pass","score":7,"notes":"ok","legal_counsel_required":false,"legal_risk":""}',
                    "cost_usd": 0.01,
                    "score": 6.5
                }
            ]
        }

        result = judge.review("Test task", "diff", use_parallel=True)

        self.assertEqual(len(result["panel"]), 2)
        # Verify winner is marked
        winners = [p for p in result["panel"] if p.get("winner")]
        self.assertEqual(len(winners), 1)


if __name__ == "__main__":
    unittest.main()
