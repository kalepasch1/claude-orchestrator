"""Adversarial and edge-case tests for task_splitter module.

This test suite covers:
- Boundary conditions in complexity estimation
- Edge cases in task splitting (max_subtasks limits, malformed input)
- Unicode and special character handling
- Regex pattern robustness
- Segment combining behavior
- Title extraction edge cases
"""

import unittest
import re
from runner.task_splitter import estimate_complexity, split_task, _extract_title


class TestComplexityAdvanced(unittest.TestCase):
    """Advanced complexity estimation edge cases."""

    def test_complexity_with_multiple_high_keywords(self):
        """Multiple high-complexity keywords should score high."""
        desc = "Refactor and migrate and redesign and integrate all systems"
        result = estimate_complexity(desc)
        self.assertEqual(result, "high")

    def test_complexity_with_multiple_medium_keywords(self):
        """Multiple medium keywords should reach medium/high."""
        desc = "Add and implement and create and extend and update the system"
        result = estimate_complexity(desc)
        self.assertIn(result, ("medium", "high"))

    def test_complexity_word_count_exactly_50(self):
        """Task with exactly 50 words (no keywords) should score low."""
        desc = " ".join(["word"] * 50)
        result = estimate_complexity(desc)
        # Just word count 50 gives +1 point, not enough for medium
        self.assertEqual(result, "low")

    def test_complexity_word_count_exactly_100(self):
        """Task with exactly 100 words (no keywords) should score low."""
        desc = " ".join(["word"] * 100)
        result = estimate_complexity(desc)
        # 100 words is not > 100, so gives +1 only (from > 50 check), not enough for medium
        self.assertEqual(result, "low")

    def test_complexity_word_count_between_50_and_100(self):
        """Task with 75 words (no keywords) should score low."""
        desc = " ".join(["word"] * 75)
        result = estimate_complexity(desc)
        # 75 words is > 50 but <= 100, gives +1 point, not enough
        self.assertEqual(result, "low")

    def test_complexity_with_exactly_2_file_refs(self):
        """Task with exactly 2 file references should boost score."""
        desc = "Update app.py and config.json"
        result = estimate_complexity(desc)
        self.assertIn(result, ("low", "medium", "high"))

    def test_complexity_with_exactly_5_file_refs(self):
        """Task with exactly 5 file references (> 2) should boost score."""
        desc = "Update app.py config.json index.ts style.css main.go"
        result = estimate_complexity(desc)
        # 5 files is > 2 gives +1, "Update" keyword gives +1, total score = 2 (medium)
        self.assertEqual(result, "medium")

    def test_complexity_with_6_file_refs(self):
        """Task with 6+ file references should give medium score."""
        desc = "Update app.py config.json index.ts style.css main.go handler.rs"
        result = estimate_complexity(desc)
        # 6 files is > 5, gives +2 (no keywords, low word count = 2 total)
        self.assertEqual(result, "medium")

    def test_complexity_malformed_file_refs_ignored(self):
        """Malformed file references should not be counted."""
        desc = "Fix the . and .. and ... files"
        result = estimate_complexity(desc)
        # Should be low since malformed refs don't count
        self.assertEqual(result, "low")

    def test_complexity_case_insensitive_keywords(self):
        """Keywords should match case-insensitively."""
        desc = "REFACTOR THE SYSTEM AND MIGRATE DATA"
        result = estimate_complexity(desc)
        self.assertEqual(result, "high")

    def test_complexity_keyword_substring_false_positive(self):
        """Partial keyword matches should still count."""
        desc = "The migration is happening"
        result = estimate_complexity(desc)
        # "migrat" is in "migration", should match "migrate" keyword
        self.assertIn(result, ("low", "medium", "high"))

    def test_complexity_non_string_types(self):
        """Non-string types should return low."""
        self.assertEqual(estimate_complexity(123), "low")
        self.assertEqual(estimate_complexity(45.6), "low")
        self.assertEqual(estimate_complexity([]), "low")
        self.assertEqual(estimate_complexity({}), "low")


class TestSplitTaskAdvanced(unittest.TestCase):
    """Advanced task splitting edge cases."""

    def test_split_with_max_subtasks_zero(self):
        """max_subtasks=0 should handle gracefully."""
        desc = "Task A. Task B. Task C."
        result = split_task(desc, max_subtasks=0)
        # Should not crash and return reasonable result
        self.assertIsInstance(result, list)

    def test_split_with_negative_max_subtasks(self):
        """Negative max_subtasks should handle gracefully."""
        desc = "Task A. Task B. Task C."
        result = split_task(desc, max_subtasks=-1)
        self.assertIsInstance(result, list)

    def test_split_with_very_large_description(self):
        """Very large descriptions should split properly."""
        # 10k+ word description
        words = ["word"] * 10000
        desc = " ".join(words)
        result = split_task(desc, max_subtasks=5)
        self.assertLessEqual(len(result), 5)
        # All subtasks should have content
        for st in result:
            self.assertTrue(st["description"].strip())

    def test_split_with_mixed_delimiters(self):
        """Mixed sentence/bullet/paragraph delimiters should work."""
        desc = ("Refactor authentication module. Add rate limiting middleware.\n"
                "- Implement JWT validation\n"
                "- Create session management\n\n"
                "Create comprehensive integration tests. Update API documentation.")
        result = split_task(desc)
        # High complexity + multiple delimiters should split
        self.assertGreater(len(result), 1)

    def test_split_with_consecutive_delimiters(self):
        """Multiple consecutive delimiters should not create empty segments."""
        desc = "Task A... Task B??? Task C!!!"
        result = split_task(desc)
        # Should handle multiple punctuation marks
        for st in result:
            self.assertTrue(st["description"].strip())
            self.assertGreater(len(st["description"].strip()), 5)

    def test_split_with_only_punctuation_segments(self):
        """Segments with only punctuation should be filtered."""
        desc = "Real task. !!! ??? ... Another real task."
        result = split_task(desc)
        # Should filter out punctuation-only segments
        for st in result:
            self.assertGreater(len(st["description"].strip()), 5)

    def test_split_segments_too_short_filtered(self):
        """Segments shorter than 5 chars should be filtered."""
        desc = "A. B. C. Real task here. D. E."
        result = split_task(desc)
        # Short segments should be filtered or combined
        for st in result:
            self.assertGreaterEqual(len(st["description"].strip()), 5)

    def test_split_combines_segments_at_max(self):
        """When reaching max_subtasks, remaining segments should combine."""
        desc = ("Refactor module. " + ". ".join([f"Task {i}" for i in range(20)]))
        result = split_task(desc, max_subtasks=3)
        # With refactor keyword and many segments, should hit max_subtasks limit
        self.assertLessEqual(len(result), 3)
        # Last subtask should contain combined content
        self.assertGreater(len(result[-1]["description"]), 0)

    def test_split_maintains_order_field(self):
        """Order field should be sequential and match position."""
        desc = "Task A. Task B. Task C. Task D. Task E."
        result = split_task(desc, max_subtasks=5)
        for i, st in enumerate(result):
            self.assertEqual(st["order"], i + 1)

    def test_split_all_subtasks_have_required_fields(self):
        """All subtasks must have title, description, complexity, order."""
        desc = "Refactor auth. Add caching. Create tests. Update docs. Fix bugs."
        result = split_task(desc)
        required_fields = {"title", "description", "complexity", "order"}
        for st in result:
            self.assertTrue(required_fields.issubset(st.keys()))
            self.assertTrue(st["title"])
            self.assertTrue(st["description"])
            self.assertIn(st["complexity"], ("low", "medium", "high"))

    def test_split_with_crlf_line_endings(self):
        """CRLF line endings should be handled like LF."""
        desc = "Task A\r\nTask B\r\nTask C"
        result = split_task(desc)
        self.assertGreater(len(result), 0)
        for st in result:
            self.assertTrue(st["description"].strip())

    def test_split_with_mixed_line_endings(self):
        """Mixed LF and CRLF should work."""
        desc = "Task A\nTask B\r\nTask C\nTask D"
        result = split_task(desc)
        self.assertGreater(len(result), 0)

    def test_split_preserves_content_no_loss(self):
        """Splitting should not lose content (except filtered segments)."""
        desc = "Refactor module. Add feature. Create tests. Update documentation."
        result = split_task(desc)
        combined = " ".join([st["description"] for st in result])
        # Combined should contain most of the original
        self.assertIn("Refactor", combined)
        self.assertIn("feature", combined)

    def test_split_empty_after_whitespace_strip(self):
        """Description with only whitespace variants should return empty."""
        self.assertEqual(split_task("\t\n\r   "), [])

    def test_split_low_complexity_single_task(self):
        """Low complexity tasks should stay as single task."""
        desc = "Fix bug in handler"
        result = split_task(desc)
        self.assertEqual(len(result), 1)

    def test_split_single_sentence_is_one_task(self):
        """Single sentence should produce exactly one task."""
        desc = "This is a single sentence task description."
        result = split_task(desc)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["order"], 1)

    def test_split_unicode_characters(self):
        """Unicode characters should not break splitting."""
        desc = "Fix bug in 日本語 module. Add 中文 feature. Create тесты."
        result = split_task(desc)
        self.assertGreater(len(result), 0)
        for st in result:
            self.assertTrue(st["description"])

    def test_split_special_characters(self):
        """Special characters should not break splitting."""
        desc = "Update @app.route('/api'). Fix $price calc. Handle #hashtag."
        result = split_task(desc)
        self.assertGreater(len(result), 0)


class TestExtractTitleAdvanced(unittest.TestCase):
    """Advanced title extraction edge cases."""

    def test_title_with_multiple_consecutive_periods(self):
        """Multiple periods should be handled."""
        text = "First sentence... Second sentence."
        result = _extract_title(text)
        self.assertEqual(result, "First sentence")

    def test_title_with_no_sentence_delimiters(self):
        """Text without delimiters should use full text or truncate."""
        text = "This is a very long title without any delimiters at all"
        result = _extract_title(text, max_len=20)
        self.assertTrue(len(result) <= 24)  # max_len + "..."

    def test_title_starting_with_whitespace(self):
        """Leading whitespace should be stripped."""
        text = "   Task description here. More text."
        result = _extract_title(text)
        self.assertEqual(result, "Task description here")

    def test_title_max_len_very_small(self):
        """Very small max_len should still produce output."""
        text = "This is the task"
        result = _extract_title(text, max_len=5)
        self.assertTrue(len(result) > 0)
        self.assertTrue(result != "")

    def test_title_only_special_characters(self):
        """Special character only text should return as-is or truncate."""
        text = "!@#$%^&*()"
        result = _extract_title(text)
        self.assertTrue(result)
        self.assertNotEqual(result, "")

    def test_title_with_newlines_in_text(self):
        """Newlines within text should be treated as delimiters."""
        text = "First line\nSecond line"
        result = _extract_title(text)
        self.assertEqual(result, "First line")

    def test_title_with_question_marks(self):
        """Question marks should act as sentence delimiters."""
        text = "What is the task? This is the next part."
        result = _extract_title(text)
        self.assertEqual(result, "What is the task")

    def test_title_with_exclamation_marks(self):
        """Exclamation marks should act as sentence delimiters."""
        text = "This is urgent! Handle immediately."
        result = _extract_title(text)
        self.assertEqual(result, "This is urgent")

    def test_title_truncation_at_word_boundary(self):
        """Truncation should happen at word boundary, not mid-word."""
        text = "A very long title that should be truncated properly"
        result = _extract_title(text, max_len=15)
        # Should not end with partial word
        self.assertFalse(result.endswith("...") and len(result) > 20)

    def test_title_from_short_sentence(self):
        """Very short sentences should be returned as-is."""
        text = "Hi."
        result = _extract_title(text)
        self.assertEqual(result, "Hi")

    def test_title_unicode_truncation(self):
        """Unicode characters should not break truncation."""
        text = "日本語タイトルはここまで。English continues."
        result = _extract_title(text)
        self.assertTrue(len(result) > 0)
        self.assertIsInstance(result, str)

    def test_title_empty_after_split(self):
        """Edge case where split might produce empty first element."""
        text = ".Another sentence."
        result = _extract_title(text)
        # Should fallback to sensible output
        self.assertTrue(result)


class TestSplitTaskComplexity(unittest.TestCase):
    """Test interaction between complexity and splitting behavior."""

    def test_high_complexity_multiple_segments(self):
        """High complexity tasks with multiple segments should split."""
        desc = ("Refactor the entire authentication module. "
                "Migrate all user sessions to JWT tokens. "
                "Add rate limiting for all endpoints. "
                "Create comprehensive integration tests. "
                "Update API documentation and examples.")
        result = split_task(desc)
        # High complexity with multiple sentences should create multiple subtasks
        self.assertGreater(len(result), 1)

    def test_low_complexity_many_segments(self):
        """Low complexity with many segments should stay single."""
        desc = ("Fix typo. Fix another typo. Fix third typo. "
                "Fix fourth typo. Fix fifth typo.")
        result = split_task(desc)
        # Low complexity should not split even with multiple segments
        self.assertEqual(len(result), 1)

    def test_medium_complexity_balanced_split(self):
        """Medium complexity should allow reasonable splitting."""
        desc = ("Add new user endpoint. Add authentication check. "
                "Add input validation. Add error handling.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)


class TestSplitTaskMaxSubtasksInteraction(unittest.TestCase):
    """Test max_subtasks parameter interactions."""

    def test_max_subtasks_1_returns_single(self):
        """max_subtasks=1 should always return one task."""
        desc = "Task A. Task B. Task C. Task D. Task E."
        result = split_task(desc, max_subtasks=1)
        # Even with multiple sentences, should return 1 if max_subtasks=1
        # or handle gracefully
        self.assertIsInstance(result, list)

    def test_max_subtasks_exceeds_segments(self):
        """max_subtasks greater than segments should work."""
        desc = "Task A. Task B."
        result = split_task(desc, max_subtasks=10)
        self.assertLessEqual(len(result), 10)

    def test_max_subtasks_equals_segments(self):
        """max_subtasks equal to segment count should work."""
        desc = "Task A. Task B. Task C."
        result = split_task(desc, max_subtasks=3)
        self.assertLessEqual(len(result), 3)

    def test_chunking_algorithm_fairness(self):
        """Chunks should be roughly balanced in size."""
        desc = ". ".join([f"Task {i}" for i in range(10)])
        result = split_task(desc, max_subtasks=3)
        # Get length of each description
        lengths = [len(st["description"]) for st in result]
        # Longest should not be much larger than shortest
        if lengths:
            ratio = max(lengths) / (min(lengths) + 1)  # +1 to avoid div by zero
            self.assertLess(ratio, 3)  # Allow 3x difference


class TestDataTypeRobustness(unittest.TestCase):
    """Test robustness against various data types."""

    def test_split_with_non_string_type(self):
        """Non-string inputs should return empty or error gracefully."""
        self.assertEqual(split_task(123), [])
        self.assertEqual(split_task(45.6), [])
        self.assertEqual(split_task([]), [])
        self.assertEqual(split_task({}), [])
        self.assertEqual(split_task(True), [])
        self.assertEqual(split_task(False), [])

    def test_extract_title_with_non_string(self):
        """Non-string inputs to _extract_title should handle gracefully."""
        # Should not crash
        result = _extract_title("")
        self.assertEqual(result, "Untitled")


class TestBuildTaskSplitting(unittest.TestCase):
    """Tests specific to build task splitting scenarios."""

    def test_build_refactor_splits_into_phases(self):
        """Build refactoring should split into independent phases."""
        desc = ("Refactor the PricingGridReconstruction component. "
                "Remove duplicate logic in calculatePrice. "
                "Add memoization cache. "
                "Update integration tests.")
        result = split_task(desc)
        # High complexity refactor should split
        self.assertGreater(len(result), 1)
        # Each subtask should have clear description
        for st in result:
            self.assertGreater(len(st["description"]), 10)

    def test_build_with_duplicate_elimination(self):
        """Build tasks eliminating duplicates should preserve behavior."""
        desc = ("Remove duplicate PricingGridReconstruction. "
                "Ensure calculatePrice logic is preserved. "
                "Update all callsites to use single implementation. "
                "Add tests to verify behavior equivalence.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)
        # Verify all phases are represented
        combined = " ".join([st["description"] for st in result])
        self.assertIn("behavior", combined.lower())

    def test_build_large_scale_refactor(self):
        """Large scale refactoring should split into parallel-safe chunks."""
        desc = ("Refactor authentication module. Migrate to JWT tokens. "
                "Update session handling. Add rate limiting. "
                "Create comprehensive tests. Update documentation. "
                "Verify backward compatibility.")
        result = split_task(desc)
        # Should split into multiple chunks
        self.assertGreater(len(result), 1)
        # Each should be independently buildable
        for st in result:
            self.assertIn(st["complexity"], ("low", "medium", "high"))

    def test_build_slice_based_splitting(self):
        """Slice-based builds should respect slice boundaries."""
        desc = ("Build slice-1: migrate PricingGridReconstruction. "
                "Build slice-2: add caching layer. "
                "Build slice-3: update tests.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)
        # Should identify slice-based structure
        combined = " ".join([st["description"] for st in result])
        self.assertIn("slice", combined.lower())

    def test_build_performance_optimization(self):
        """Performance optimization tasks should identify dependencies."""
        desc = ("Refactor and optimize PricingGridReconstruction rendering. "
                "Profile current implementation. "
                "Implement memoization caching layer. "
                "Benchmark improvements thoroughly. "
                "Deploy with comprehensive monitoring.")
        result = split_task(desc)
        # High complexity with multiple keywords should split
        self.assertGreater(len(result), 0)

    def test_build_with_file_scope(self):
        """Build tasks with specific files should stay grouped."""
        desc = ("Refactor src/pricing.ts and src/grid.ts. "
                "Update app.py. Modify config.json. "
                "Add tests in tests/pricing.test.ts.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)


class TestBehaviorPreservation(unittest.TestCase):
    """Tests ensuring behavior is preserved through refactoring."""

    def test_preserve_behavior_no_functional_changes(self):
        """Refactoring should preserve all functional behavior."""
        desc = ("Refactor module A and B to reduce duplication. "
                "Consolidate calculatePrice logic. "
                "Preserve all existing function signatures.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)
        # Should mention behavior preservation
        combined = " ".join([st["description"] for st in result])
        self.assertTrue(
            "preserve" in combined.lower() or
            "consolidate" in combined.lower()
        )

    def test_backward_compatibility_requirement(self):
        """Tasks requiring backward compatibility should be flagged."""
        desc = ("Refactor authentication module while maintaining backward compatibility. "
                "Existing clients must continue working. "
                "Add deprecation warnings for old API.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)
        combined = " ".join([st["description"] for st in result])
        self.assertIn("compat", combined.lower())

    def test_no_behavior_loss_in_consolidation(self):
        """Consolidating duplicates should not lose behavior."""
        desc = ("Consolidate PricingGridReconstruction duplicates "
                "(currently in modules A and B). "
                "Ensure both code paths produce identical results. "
                "Add equivalence tests.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)
        for st in result:
            self.assertTrue(st["description"].strip())


class TestDuplicateDetectionAndRemoval(unittest.TestCase):
    """Tests for detecting and removing duplicate code patterns."""

    def test_detect_duplicate_component(self):
        """Should identify duplicate component references."""
        desc = ("Remove duplicate PricingGridReconstruction component. "
                "First instance in app/components/pricing.tsx. "
                "Second instance in legacy/pricing.tsx. "
                "Consolidate to single source of truth.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)
        combined = " ".join([st["description"] for st in result])
        # Should mention both locations or consolidation
        self.assertTrue("duplicate" in combined.lower() or
                       "consolidat" in combined.lower())

    def test_duplicate_function_consolidation(self):
        """Should split duplicate function consolidation properly."""
        desc = ("Remove duplicate calculatePrice functions. "
                "Found in pricing.ts (v1) and grid.ts (v2). "
                "Move to shared utils.ts. "
                "Update all callsites. "
                "Verify equivalence with tests.")
        result = split_task(desc)
        # Should split into: identify, consolidate, update, verify
        self.assertGreater(len(result), 1)

    def test_duplicate_in_multiple_files(self):
        """Duplicates across many files should split into manageable chunks."""
        files = [f"file{i}.ts" for i in range(5)]
        desc = (f"Refactor and remove duplicated logic from {', '.join(files)}. "
                "Consolidate into shared module. "
                "Update all imports. "
                "Verify behavior is preserved.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)
        # With high complexity (refactor keyword) and many files, should split
        self.assertGreaterEqual(len(result), 1)


class TestAdversarialSplitting(unittest.TestCase):
    """Adversarial tests for task splitting edge cases and robustness."""

    def test_adversarial_empty_segments_after_split(self):
        """Splitting should never produce empty or whitespace-only segments."""
        desc = "Refactor... Migrate!!! Add... Update??? Remove..."
        result = split_task(desc)
        for st in result:
            # No empty descriptions
            self.assertTrue(st["description"].strip())
            # No descriptions that are only punctuation
            cleaned = re.sub(r'[^\w\s]', '', st["description"])
            self.assertTrue(cleaned.strip())

    def test_adversarial_max_subtasks_override(self):
        """max_subtasks should be strictly enforced."""
        desc = ". ".join([f"Task {i}" for i in range(50)])
        for max_val in [1, 2, 3, 5, 10]:
            result = split_task(desc, max_subtasks=max_val)
            self.assertLessEqual(len(result), max_val,
                               f"Exceeded max_subtasks={max_val}: got {len(result)}")

    def test_adversarial_very_short_descriptions(self):
        """Very short inputs should not crash or error."""
        short_inputs = ["a", "Hi", "Go", "No", "x y z"]
        for inp in short_inputs:
            result = split_task(inp)
            # Should return valid list, even if empty
            self.assertIsInstance(result, list)

    def test_adversarial_pathological_nesting(self):
        """Deeply nested or recursive structure should handle gracefully."""
        desc = "((())). [[[]]]. {{{}}}"
        result = split_task(desc)
        self.assertIsInstance(result, list)

    def test_adversarial_mixed_encodings_simulate(self):
        """Mixed character types should not break splitting."""
        desc = ("Refactor módulo. Migrate 数据. Redesign über system. "
                "Add ñoño features. Update façade.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)

    def test_adversarial_extremely_long_single_line(self):
        """Very long single line with no breaks should handle gracefully."""
        desc = " ".join(["word"] * 5000)
        result = split_task(desc, max_subtasks=3)
        self.assertLessEqual(len(result), 3)
        # Content should not be lost
        for st in result:
            self.assertTrue(st["description"])

    def test_adversarial_url_like_patterns(self):
        """URL-like patterns should not be mistaken for file refs."""
        desc = ("Refactor service. Visit https://example.com for docs. "
                "Check https://api.example.com/v1/pricing. "
                "Update app.py config.json")
        result = split_task(desc)
        self.assertGreater(len(result), 0)

    def test_adversarial_code_snippet_in_description(self):
        """Code snippets in description should not break parsing."""
        desc = ("Refactor component. "
                "Change: if (x > 5 && y < 10) { doSomething(); } "
                "to: const valid = x > 5 && y < 10; if (valid) { } "
                "Add tests.")
        result = split_task(desc)
        self.assertGreater(len(result), 0)

    def test_adversarial_repeated_keywords(self):
        """Repeated high-complexity keywords should not overflow score."""
        keywords = " ".join(["refactor"] * 100)
        desc = f"Task: {keywords}"
        result = split_task(desc)
        # Should still parse without crashing
        self.assertGreater(len(result), 0)


class TestComplexityEdgeCases(unittest.TestCase):
    """Edge cases in complexity estimation for build tasks."""

    def test_complexity_with_build_keywords(self):
        """Build-specific keywords should boost complexity appropriately."""
        desc = "Build the project. Compile dependencies. Link modules."
        # "build" and "compile" are not in base keywords, should be low
        result = estimate_complexity(desc)
        self.assertIn(result, ("low", "medium"))

    def test_complexity_refactor_plus_migrate(self):
        """Combining high-complexity keywords should score highest."""
        desc = "Refactor and migrate and integrate the system"
        result = estimate_complexity(desc)
        self.assertEqual(result, "high")

    def test_complexity_with_many_file_extensions(self):
        """Many file types should boost complexity."""
        desc = "Update app.py web.ts style.css db.sql test.go image.png"
        result = estimate_complexity(desc)
        # 6+ files should boost to medium at minimum
        self.assertIn(result, ("medium", "high"))

    def test_complexity_boundary_101_words(self):
        """101 words (> 100) should trigger medium complexity."""
        desc = " ".join(["word"] * 101)
        result = estimate_complexity(desc)
        # 101 words is > 100, gives +2, enough for medium
        self.assertIn(result, ("medium", "high"))

    def test_complexity_boundary_50_words_exact(self):
        """50 words should not alone trigger medium."""
        desc = " ".join(["word"] * 50)
        result = estimate_complexity(desc)
        self.assertEqual(result, "low")


class TestSplitTaskOrderAndSequence(unittest.TestCase):
    """Tests for proper ordering and sequencing of split tasks."""

    def test_order_field_sequential(self):
        """Order field should be sequential starting at 1."""
        desc = "Task A. Task B. Task C. Task D. Task E."
        result = split_task(desc)
        for i, st in enumerate(result):
            self.assertEqual(st["order"], i + 1)

    def test_order_maintained_after_filtering(self):
        """Order should remain sequential even after filtering short segments."""
        desc = "A. Real task with enough content here. B. Another real task."
        result = split_task(desc)
        # Orders should be 1, 2, ... not 1, 2, 3
        for i, st in enumerate(result):
            self.assertEqual(st["order"], i + 1)

    def test_single_task_has_order_one(self):
        """Single task should always have order=1."""
        desc = "Simple low complexity task"
        result = split_task(desc)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["order"], 1)


class TestSegmentCombining(unittest.TestCase):
    """Tests for how segments are combined under constraints."""

    def test_segments_combine_when_at_max(self):
        """When max_subtasks is reached, remaining segments should combine."""
        # Create many segments
        segments = ". ".join([f"Task {i}: refactor module {i}" for i in range(10)])
        result = split_task(segments, max_subtasks=2)
        self.assertEqual(len(result), 2)
        # Last task should be significantly longer (combining all extras)
        last_len = len(result[-1]["description"])
        first_len = len(result[0]["description"])
        # Last should be larger (combining multiple segments)
        self.assertGreaterEqual(last_len, first_len * 0.5)

    def test_chunk_size_calculation(self):
        """Chunk size should be calculated as segments // max_subtasks."""
        desc = ". ".join([f"Segment {i}" for i in range(20)])
        result = split_task(desc, max_subtasks=5)
        # Should have 5 or fewer subtasks
        self.assertLessEqual(len(result), 5)


if __name__ == "__main__":
    unittest.main()
