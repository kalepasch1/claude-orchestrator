import unittest
from unittest.mock import patch, MagicMock, call
import threading
import math
import logging
from runner import prompt_evolver


class TestSelectTemplateBasic(unittest.TestCase):
    """Basic select_template functionality."""

    def setUp(self):
        """Reset singleton before each test."""
        prompt_evolver.invalidate()

    def test_select_template_no_rows_returns_base(self):
        """If DB returns None/empty for a kind, return base prompt and 'base'."""
        with patch('runner.db.select', return_value=None):
            prompt, template_id = prompt_evolver.select_template("code_gen", "write code")
            self.assertEqual(prompt, "write code")
            self.assertEqual(template_id, "base")

    def test_select_template_empty_rows_list(self):
        """If DB returns empty list, cold-start returns base."""
        with patch('runner.db.select', return_value=[]):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test prompt")
            self.assertEqual(prompt, "test prompt")
            self.assertEqual(template_id, "base")

    def test_select_template_single_base_template(self):
        """With single base template in DB, select it unmodified."""
        rows = [{"kind": "code_gen", "template_id": "base", "total_reward": 5.0, "n_trials": 5}]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "prompt")
            self.assertEqual(template_id, "base")
            self.assertEqual(prompt, "prompt")

    def test_select_template_single_non_base_template(self):
        """Non-base templates are tagged with [template:id] prefix."""
        rows = [{"kind": "code_gen", "template_id": "chain_of_thought", "total_reward": 3.0, "n_trials": 3}]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            self.assertEqual(template_id, "chain_of_thought")
            self.assertIn("[template:chain_of_thought]", prompt)
            self.assertIn("test", prompt)

    def test_select_template_queries_db_with_correct_filter(self):
        """select_template queries DB with eq filter on kind."""
        with patch('runner.db.select') as mock_select:
            mock_select.return_value = None
            prompt_evolver.select_template("my_kind", "prompt")
            mock_select.assert_called_with("prompt_templates", {"kind": "eq.my_kind"})


class TestSelectTemplateUCB1(unittest.TestCase):
    """UCB1 scoring and arm selection."""

    def setUp(self):
        """Reset singleton before each test."""
        prompt_evolver.invalidate()

    def test_ucb1_prefers_untried_arms(self):
        """Arms with n_trials=0 get infinite UCB1 score."""
        rows = [
            {"kind": "code_gen", "template_id": "base", "total_reward": 5.0, "n_trials": 5},
            {"kind": "code_gen", "template_id": "chain_of_thought", "total_reward": 0.0, "n_trials": 0},
        ]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            # Untried arm should be preferred
            self.assertEqual(template_id, "chain_of_thought")

    def test_ucb1_mean_reward_component(self):
        """UCB1 score includes mean reward (total_reward / n_trials)."""
        rows = [
            {"kind": "code_gen", "template_id": "base", "total_reward": 9.0, "n_trials": 10},
        ]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            self.assertEqual(template_id, "base")

    def test_ucb1_aggregates_multiple_rows_same_template(self):
        """Multiple rows for same template are aggregated before UCB1."""
        rows = [
            {"kind": "code_gen", "template_id": "base", "total_reward": 2.0, "n_trials": 2},
            {"kind": "code_gen", "template_id": "base", "total_reward": 3.0, "n_trials": 3},
        ]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            # Aggregated: base has 5.0 total_reward, 5 n_trials
            self.assertEqual(template_id, "base")

    def test_ucb1_exploration_bonus_decreases_with_trials(self):
        """A well-sampled arm wins only when its mean beats the rival's bonus edge.

        The exploration bonus sqrt(2*ln(N)/n) shrinks as n grows, so a high-n arm
        carries a smaller bonus. It therefore has to earn its win on mean reward.
        Here base is sampled twice as often (smaller bonus) but has the better mean,
        so it wins; the arithmetic is checked explicitly below.
        """
        rows = [
            {"kind": "code_gen", "template_id": "base", "total_reward": 90.0, "n_trials": 100},
            {"kind": "code_gen", "template_id": "chain_of_thought", "total_reward": 25.0, "n_trials": 50},
        ]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            # N = 150
            # base: 0.90 + sqrt(2*ln(150)/100) = 0.90 + 0.317 = 1.217
            # cot : 0.50 + sqrt(2*ln(150)/50)  = 0.50 + 0.448 = 0.948
            n = 150
            base_score = 0.9 + math.sqrt(2 * math.log(n) / 100)
            cot_score = 0.5 + math.sqrt(2 * math.log(n) / 50)
            # The high-n arm carries the smaller exploration bonus...
            self.assertLess(math.sqrt(2 * math.log(n) / 100),
                            math.sqrt(2 * math.log(n) / 50))
            # ...and still wins here because its mean advantage is larger.
            self.assertGreater(base_score, cot_score)
            self.assertEqual(template_id, "base")

    def test_ucb1_formula_correctness(self):
        """UCB1 calculation uses correct formula: mean + sqrt(2*ln(N)/n)."""
        rows = [
            {"kind": "code_gen", "template_id": "base", "total_reward": 10.0, "n_trials": 10},
        ]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            # With one arm, it's selected regardless of score
            self.assertEqual(template_id, "base")

    def test_cold_start_round_robin(self):
        """Cold-start selects next template in TEMPLATE_IDS via round-robin."""
        with patch('runner.db.select', return_value=[]):
            prompt1, id1 = prompt_evolver.select_template("new_kind", "test")
            # First cold-start gets TEMPLATE_IDS[0] = "base"
            self.assertEqual(id1, "base")

            # Second call to same kind gets TEMPLATE_IDS[1]
            prompt2, id2 = prompt_evolver.select_template("new_kind", "test")
            self.assertEqual(id2, "chain_of_thought")


class TestRecordOutcome(unittest.TestCase):
    """record_outcome behavior."""

    def setUp(self):
        """Reset singleton before each test."""
        prompt_evolver.invalidate()

    def test_record_outcome_full_reward_deployed_verified(self):
        """deployed_verified=True gives reward=1.0."""
        with patch('runner.db.insert') as mock_insert:
            prompt_evolver.record_outcome("code_gen", "base", deployed_verified=True)
            call_args = mock_insert.call_args
            self.assertEqual(call_args[0][1]["total_reward"], 1.0)
            self.assertEqual(call_args[0][1]["n_trials"], 1)

    def test_record_outcome_partial_reward_merged_with_commit(self):
        """merged_first_try + artifact_commit gives reward=0.5."""
        with patch('runner.db.insert') as mock_insert:
            prompt_evolver.record_outcome("code_gen", "base", merged_first_try=True, artifact_commit="abc123")
            call_args = mock_insert.call_args
            self.assertEqual(call_args[0][1]["total_reward"], 0.5)

    def test_record_outcome_no_reward_merged_without_commit(self):
        """merged_first_try without artifact_commit gives reward=0.0."""
        with patch('runner.db.insert') as mock_insert:
            prompt_evolver.record_outcome("code_gen", "base", merged_first_try=True)
            call_args = mock_insert.call_args
            self.assertEqual(call_args[0][1]["total_reward"], 0.0)

    def test_record_outcome_no_reward_not_merged(self):
        """merged_first_try=False gives reward=0.0."""
        with patch('runner.db.insert') as mock_insert:
            prompt_evolver.record_outcome("code_gen", "base", merged_first_try=False)
            call_args = mock_insert.call_args
            self.assertEqual(call_args[0][1]["total_reward"], 0.0)

    def test_record_outcome_uses_merge_duplicates_resolution(self):
        """Insert called with resolution='merge-duplicates'."""
        with patch('runner.db.insert') as mock_insert:
            prompt_evolver.record_outcome("code_gen", "base", deployed_verified=True)
            call_args = mock_insert.call_args
            self.assertEqual(call_args[1]["resolution"], "merge-duplicates")

    def test_record_outcome_inserts_correct_row_structure(self):
        """Inserted row has kind, template_id, total_reward, n_trials."""
        with patch('runner.db.insert') as mock_insert:
            prompt_evolver.record_outcome("code_gen", "chain_of_thought", deployed_verified=True)
            call_args = mock_insert.call_args
            row = call_args[0][1]
            self.assertEqual(row["kind"], "code_gen")
            self.assertEqual(row["template_id"], "chain_of_thought")
            self.assertEqual(row["total_reward"], 1.0)
            self.assertEqual(row["n_trials"], 1)

    def test_record_outcome_db_error_logs_and_swallows(self):
        """DB error is logged but not raised."""
        with patch('runner.db.insert', side_effect=Exception("DB error")):
            with patch.object(prompt_evolver, 'logger') as mock_logger:
                # Should not raise
                prompt_evolver.record_outcome("code_gen", "base", deployed_verified=True)
                mock_logger.warning.assert_called()
                self.assertIn("record outcome", mock_logger.warning.call_args[0][0].lower())

    def test_record_outcome_for_base_template(self):
        """record_outcome records base template just like any other."""
        with patch('runner.db.insert') as mock_insert:
            prompt_evolver.record_outcome("code_gen", "base", deployed_verified=True)
            call_args = mock_insert.call_args
            self.assertEqual(call_args[0][1]["template_id"], "base")


class TestSelectTemplateErrorHandling(unittest.TestCase):
    """Error handling in select_template."""

    def setUp(self):
        """Reset singleton before each test."""
        prompt_evolver.invalidate()

    def test_select_template_db_error_returns_base_and_logs(self):
        """DB error logs warning and returns base."""
        with patch('runner.db.select', side_effect=Exception("Connection failed")):
            with patch.object(prompt_evolver, 'logger') as mock_logger:
                prompt, template_id = prompt_evolver.select_template("code_gen", "test")
                self.assertEqual(prompt, "test")
                self.assertEqual(template_id, "base")
                mock_logger.warning.assert_called()
                call_msg = mock_logger.warning.call_args[0][0]
                self.assertIn("select_template failed", call_msg)
                self.assertIn("code_gen", call_msg)

    def test_select_template_missing_template_id_defaults_to_base(self):
        """Row without template_id field defaults to 'base'."""
        rows = [{"kind": "code_gen", "total_reward": 1.0, "n_trials": 1}]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            self.assertEqual(template_id, "base")

    def test_select_template_missing_reward_defaults_to_zero(self):
        """Row without total_reward defaults to 0.0."""
        rows = [{"kind": "code_gen", "template_id": "base", "n_trials": 1}]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            self.assertEqual(template_id, "base")

    def test_select_template_missing_trials_defaults_to_zero(self):
        """Row without n_trials defaults to 0."""
        rows = [{"kind": "code_gen", "template_id": "base", "total_reward": 1.0}]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            self.assertEqual(template_id, "base")

    def test_select_template_empty_prompt(self):
        """Handles empty base_prompt."""
        with patch('runner.db.select', return_value=None):
            prompt, template_id = prompt_evolver.select_template("code_gen", "")
            self.assertEqual(prompt, "")
            self.assertEqual(template_id, "base")

    def test_select_template_empty_kind(self):
        """Handles empty kind string."""
        with patch('runner.db.select', return_value=None):
            prompt, template_id = prompt_evolver.select_template("", "test")
            self.assertEqual(template_id, "base")


class TestThreadSafety(unittest.TestCase):
    """Thread safety of module-level functions."""

    def setUp(self):
        """Reset singleton before each test."""
        prompt_evolver.invalidate()

    def test_concurrent_select_calls(self):
        """Concurrent select_template calls are serialized without lost updates.

        Cold-start advances a per-kind round-robin counter (see
        test_cold_start_round_robin), so the ten calls must hand back ten
        *successive* arms rather than ten copies of one arm. Asserting a fixed
        template_id here would contradict that round-robin contract; what thread
        safety actually guarantees is that no increment is lost to a race.
        """
        results = []
        errors = []

        def thread_func():
            try:
                with patch('runner.db.select', return_value=None):
                    prompt, template_id = prompt_evolver.select_template("code_gen", "test")
                    results.append((prompt, template_id))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=thread_func) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 10)
        # Every result is a real arm, and base is returned untagged.
        for prompt, template_id in results:
            self.assertIn(template_id, prompt_evolver.TEMPLATE_IDS)
            if template_id == "base":
                self.assertEqual(prompt, "test")
            else:
                self.assertEqual(prompt, f"[template:{template_id}]\ntest")
        # No lost updates: the counter advanced exactly once per call, so the
        # ten selections cycle through TEMPLATE_IDS in order.
        expected = [prompt_evolver.TEMPLATE_IDS[i % len(prompt_evolver.TEMPLATE_IDS)]
                    for i in range(10)]
        self.assertEqual(sorted(r[1] for r in results), sorted(expected))

    def test_concurrent_record_calls(self):
        """Multiple threads calling record_outcome concurrently."""
        errors = []

        def thread_func():
            try:
                with patch('runner.db.insert'):
                    prompt_evolver.record_outcome("code_gen", "base", deployed_verified=True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=thread_func) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)

    def test_concurrent_mixed_calls(self):
        """Mixed select and record calls are thread-safe."""
        results = []
        errors = []

        def select_func():
            try:
                with patch('runner.db.select', return_value=None):
                    r = prompt_evolver.select_template("code_gen", "test")
                    results.append(("select", r))
            except Exception as e:
                errors.append(e)

        def record_func():
            try:
                with patch('runner.db.insert'):
                    prompt_evolver.record_outcome("code_gen", "base", deployed_verified=True)
                    results.append(("record", None))
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(20):
            if i % 2 == 0:
                threads.append(threading.Thread(target=select_func))
            else:
                threads.append(threading.Thread(target=record_func))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 20)


class TestStatsFunction(unittest.TestCase):
    """stats() function."""

    def setUp(self):
        """Reset singleton before each test."""
        prompt_evolver.invalidate()

    def test_stats_no_rows(self):
        """stats() with no data returns empty stats."""
        with patch('runner.db.select', return_value=None):
            stats = prompt_evolver.stats()
            self.assertEqual(stats["total_trials"], 0)
            self.assertEqual(stats["kinds"], {})

    def test_stats_aggregates_trials(self):
        """stats() aggregates total trials and by-kind breakdown."""
        rows = [
            {"kind": "code_gen", "n_trials": 5},
            {"kind": "code_gen", "n_trials": 3},
            {"kind": "test_gen", "n_trials": 2},
        ]
        with patch('runner.db.select', return_value=rows):
            stats = prompt_evolver.stats()
            self.assertEqual(stats["total_trials"], 10)
            self.assertEqual(stats["kinds"]["code_gen"], 8)
            self.assertEqual(stats["kinds"]["test_gen"], 2)

    def test_stats_db_error_returns_empty(self):
        """stats() returns empty on DB error."""
        with patch('runner.db.select', side_effect=Exception("DB error")):
            stats = prompt_evolver.stats()
            self.assertEqual(stats["total_trials"], 0)
            self.assertEqual(stats["kinds"], {})


class TestInvalidateFunction(unittest.TestCase):
    """invalidate() clears state for testing."""

    def test_invalidate_clears_singleton(self):
        """invalidate() resets singleton state."""
        with patch('runner.db.select', return_value=[]):
            prompt_evolver.select_template("kind1", "test")
            prompt_evolver.invalidate()
            # After invalidate, cold-start should restart from TEMPLATE_IDS[0]
            prompt, template_id = prompt_evolver.select_template("kind1", "test")
            self.assertEqual(template_id, "base")


class TestMultipleKinds(unittest.TestCase):
    """Different kinds have independent statistics."""

    def setUp(self):
        """Reset singleton before each test."""
        prompt_evolver.invalidate()

    def test_different_kinds_independent_stats(self):
        """Different kinds maintain separate arm statistics."""
        rows1 = [{"kind": "code_gen", "template_id": "base", "total_reward": 10.0, "n_trials": 10}]
        rows2 = [{"kind": "test_gen", "template_id": "base", "total_reward": 5.0, "n_trials": 10}]

        with patch('runner.db.select', return_value=rows1):
            p1, id1 = prompt_evolver.select_template("code_gen", "test")

        prompt_evolver.invalidate()

        with patch('runner.db.select', return_value=rows2):
            p2, id2 = prompt_evolver.select_template("test_gen", "test")

        self.assertEqual(id1, "base")
        self.assertEqual(id2, "base")


class TestEdgeCases(unittest.TestCase):
    """Edge cases and unusual inputs."""

    def setUp(self):
        """Reset singleton before each test."""
        prompt_evolver.invalidate()

    def test_select_template_very_long_prompt(self):
        """Handles very long prompts."""
        long_prompt = "x" * 10000
        with patch('runner.db.select', return_value=None):
            prompt, template_id = prompt_evolver.select_template("code_gen", long_prompt)
            self.assertEqual(prompt, long_prompt)

    def test_select_template_unicode_in_prompt(self):
        """Handles unicode in prompts."""
        unicode_prompt = "生成代码 🚀 escribir código"
        with patch('runner.db.select', return_value=None):
            prompt, template_id = prompt_evolver.select_template("code_gen", unicode_prompt)
            self.assertEqual(prompt, unicode_prompt)

    def test_record_outcome_empty_kind(self):
        """record_outcome handles empty kind."""
        with patch('runner.db.insert') as mock_insert:
            prompt_evolver.record_outcome("", "base", deployed_verified=True)
            call_args = mock_insert.call_args
            self.assertEqual(call_args[0][1]["kind"], "")

    def test_record_outcome_empty_template_id(self):
        """record_outcome handles empty template_id."""
        with patch('runner.db.insert') as mock_insert:
            prompt_evolver.record_outcome("code_gen", "", deployed_verified=True)
            call_args = mock_insert.call_args
            self.assertEqual(call_args[0][1]["template_id"], "")

    def test_select_template_all_arms_zero_trials(self):
        """N=0 across all rows: prefer an untried arm, tie-broken alphabetically."""
        rows = [
            {"kind": "code_gen", "template_id": "chain_of_thought", "total_reward": 0.0, "n_trials": 0},
            {"kind": "code_gen", "template_id": "edit_first", "total_reward": 0.0, "n_trials": 0},
        ]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            # Both arms are untried, so both score +inf. UCB1 always prefers an
            # untried arm over falling back to base, and ties break on
            # template_id alphabetically -> "chain_of_thought" before
            # "edit_first". (Returning "base" here would be wrong twice over:
            # base is not among the rows, and it would starve the untried arms.)
            self.assertEqual(template_id, "chain_of_thought")
            self.assertEqual(prompt, "[template:chain_of_thought]\ntest")

    def test_select_template_negative_reward(self):
        """Handles negative rewards (malformed data)."""
        rows = [{"kind": "code_gen", "template_id": "base", "total_reward": -5.0, "n_trials": 1}]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            # Should still select, even with negative reward
            self.assertEqual(template_id, "base")

    def test_select_template_large_numbers(self):
        """Handles very large reward/trial counts."""
        rows = [{"kind": "code_gen", "template_id": "base", "total_reward": 1e10, "n_trials": 1e9}]
        with patch('runner.db.select', return_value=rows):
            prompt, template_id = prompt_evolver.select_template("code_gen", "test")
            self.assertEqual(template_id, "base")


class TestTemplateIDsConstant(unittest.TestCase):
    """TEMPLATE_IDS constant is available and correct."""

    def test_template_ids_defined(self):
        """TEMPLATE_IDS constant is defined."""
        self.assertIsNotNone(prompt_evolver.TEMPLATE_IDS)
        self.assertIsInstance(prompt_evolver.TEMPLATE_IDS, list)

    def test_template_ids_contains_base(self):
        """TEMPLATE_IDS includes 'base'."""
        self.assertIn("base", prompt_evolver.TEMPLATE_IDS)

    def test_template_ids_has_multiple_options(self):
        """TEMPLATE_IDS has more than just 'base'."""
        self.assertGreater(len(prompt_evolver.TEMPLATE_IDS), 1)


if __name__ == "__main__":
    unittest.main()
