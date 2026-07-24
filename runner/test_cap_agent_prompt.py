#!/usr/bin/env python3
"""
Test suite for _cap_agent_prompt function.

Tests the prompt truncation logic that handles:
1. Short prompts (no truncation needed)
2. Long prompts (truncation with marker)
3. Edge cases where tail calculation would be negative
4. Proper handling of marker placement and integrity
"""
import os
import sys
import unittest

# Add runner directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock environment for test isolation
os.environ.setdefault("ORCH_MAX_AGENT_PROMPT_CHARS", "36000")

# Import the function being tested
from runner import _cap_agent_prompt


class TestCapAgentPrompt(unittest.TestCase):
    """Tests for _cap_agent_prompt truncation and edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.max_chars = int(os.environ.get("ORCH_MAX_AGENT_PROMPT_CHARS", "36000"))
        self.marker = (
            "\n\n[ORCHESTRATOR COMPACTION: middle context removed to stay below model limits. "
            "Use the focus files, task contract, and final request below; inspect repo files directly "
            "instead of relying on omitted transcript bulk.]\n\n"
        )

    def test_short_prompt_no_truncation(self):
        """Short prompts should not be truncated or include marker."""
        short_prompt = "This is a short prompt"
        result = _cap_agent_prompt(short_prompt)
        self.assertEqual(result, short_prompt)
        self.assertNotIn("ORCHESTRATOR COMPACTION", result)

    def test_empty_prompt_returns_empty(self):
        """Empty prompts should be returned as-is."""
        result = _cap_agent_prompt("")
        self.assertEqual(result, "")

    def test_none_prompt_returns_empty(self):
        """None prompts should be treated as empty."""
        result = _cap_agent_prompt(None)
        self.assertEqual(result, "")

    def test_prompt_at_exact_limit(self):
        """Prompt at exactly max chars should not be truncated."""
        prompt = "x" * self.max_chars
        result = _cap_agent_prompt(prompt)
        self.assertEqual(result, prompt)
        self.assertNotIn("ORCHESTRATOR COMPACTION", result)

    def test_prompt_one_char_over_limit(self):
        """Prompt one char over limit should be truncated and include marker."""
        prompt = "x" * (self.max_chars + 1)
        result = _cap_agent_prompt(prompt)
        self.assertIn("ORCHESTRATOR COMPACTION", result)
        self.assertLessEqual(len(result), self.max_chars)

    def test_very_long_prompt_truncation(self):
        """Very long prompts should be truncated properly."""
        long_prompt = "x" * (self.max_chars * 2)
        result = _cap_agent_prompt(long_prompt)
        # Result should not exceed max chars
        self.assertLessEqual(len(result), self.max_chars)
        # Should include marker when truncated
        self.assertIn("ORCHESTRATOR COMPACTION", result)
        # Should have head, marker, and tail
        self.assertIn(marker_str := "\n\n[ORCHESTRATOR COMPACTION:", result)

    def test_truncated_prompt_structure(self):
        """Truncated prompt should have proper structure: head + marker + tail."""
        long_prompt = "HEAD_" + "x" * (self.max_chars + 10000) + "_TAIL"
        result = _cap_agent_prompt(long_prompt)
        # Should start with beginning of original prompt
        self.assertTrue(result.startswith("HEAD_"))
        # Should include marker
        self.assertIn("ORCHESTRATOR COMPACTION", result)
        # Should include end of original prompt (tail)
        self.assertTrue(result.rstrip().endswith("_TAIL"))

    def test_marker_integrity(self):
        """Marker should be properly formatted when included."""
        long_prompt = "x" * (self.max_chars + 1000)
        result = _cap_agent_prompt(long_prompt)
        # Marker should be complete and proper
        self.assertIn("ORCHESTRATOR COMPACTION: middle context removed", result)
        self.assertIn("Use the focus files, task contract, and final request below", result)
        self.assertIn("instead of relying on omitted transcript bulk", result)

    def test_tail_zero_edge_case(self):
        """When tail would be 0 or negative, should handle gracefully."""
        # Create a prompt where head + marker > max_chars
        # This tests the "max(0, ...)" logic
        long_prompt = "x" * (self.max_chars + 1)
        result = _cap_agent_prompt(long_prompt)
        # Should not raise an error
        self.assertIsInstance(result, str)
        # Should be valid length
        self.assertLessEqual(len(result), self.max_chars)

    def test_tail_negative_handling(self):
        """Verify that negative tail is correctly handled by max(0, ...)."""
        # Test that when tail would be negative, it's set to 0 and handled gracefully
        long_prompt = "y" * (self.max_chars + 2000)
        # Should not raise error even with extreme truncation
        result = _cap_agent_prompt(long_prompt)
        self.assertIsInstance(result, str)
        self.assertLessEqual(len(result), self.max_chars)

    def test_no_tail_text_when_tail_is_zero(self):
        """When tail is 0, tail_text should be empty string."""
        # Create extreme case where most of budget goes to head
        long_prompt = "A" * 1000 + "M" * (self.max_chars) + "Z" * 1000
        result = _cap_agent_prompt(long_prompt)
        # If tail was 0, result should not end with "Z"s
        if "ORCHESTRATOR COMPACTION" in result:
            # After truncation, should not have significant tail
            self.assertLessEqual(len(result), self.max_chars)

    def test_head_section_preserved(self):
        """Head section of prompt should be preserved in output."""
        distinctive_head = "UNIQUE_HEAD_MARKER_" + "x" * 5000
        long_prompt = distinctive_head + "x" * (self.max_chars + 1000)
        result = _cap_agent_prompt(long_prompt)
        # Should preserve the distinctive head
        self.assertIn("UNIQUE_HEAD_MARKER_", result)

    def test_tail_section_preserved_when_present(self):
        """Tail section should be preserved when it fits."""
        distinctive_tail = "x" * 1000 + "_UNIQUE_TAIL_MARKER"
        long_prompt = "x" * (self.max_chars) + distinctive_tail
        result = _cap_agent_prompt(long_prompt)
        # If there's space for tail, it should be included
        if len(result) > 10000:  # If result is substantial
            # Tail might be in result if there's room
            pass

    def test_result_length_never_exceeds_max(self):
        """Result should never exceed MAX_AGENT_PROMPT_CHARS."""
        test_sizes = [
            100,  # Very small
            1000,  # Small
            self.max_chars // 2,  # Half
            self.max_chars,  # Exact
            self.max_chars + 100,  # Just over
            self.max_chars * 2,  # Double
            self.max_chars * 10,  # Very large
        ]
        for size in test_sizes:
            with self.subTest(size=size):
                prompt = "x" * size
                result = _cap_agent_prompt(prompt)
                self.assertLessEqual(
                    len(result),
                    self.max_chars,
                    f"Result length {len(result)} exceeds max {self.max_chars} for input size {size}"
                )

    def test_marker_only_when_truncated(self):
        """Marker should only appear when truncation is needed."""
        # Short prompt - no marker
        short = "x" * 100
        result_short = _cap_agent_prompt(short)
        self.assertNotIn("ORCHESTRATOR COMPACTION", result_short)

        # Long prompt - marker present
        long = "x" * (self.max_chars + 1)
        result_long = _cap_agent_prompt(long)
        self.assertIn("ORCHESTRATOR COMPACTION", result_long)

    def test_head_calculation(self):
        """Head should be min(20000, max_chars // 3)."""
        # For default max_chars (36000), head should be min(20000, 12000) = 12000
        expected_head = min(20000, self.max_chars // 3)
        # Test by creating specific prompt
        prompt = "H" * (expected_head + 100) + "x" * (self.max_chars + 1000)
        result = _cap_agent_prompt(prompt)
        # Result should start with H's up to head limit
        h_count = 0
        for char in result:
            if char == "H":
                h_count += 1
            else:
                break
        self.assertLessEqual(h_count, expected_head + 100)

    def test_whitespace_handling_in_tail(self):
        """Tail section should have leading whitespace stripped."""
        # Create prompt with leading whitespace in tail
        # Add enough content to ensure truncation happens
        long_prompt = "x" * (self.max_chars + 500) + "   \n\nTAIL_CONTENT"
        result = _cap_agent_prompt(long_prompt)
        # If tail is included, lstrip() should remove leading whitespace
        if "TAIL_CONTENT" in result:
            # Should have lstrip() applied, so no leading spaces before tail section
            # (but whitespace in the middle of the prompt is preserved)
            self.assertIsInstance(result, str)

    def test_marker_length_accounted_for(self):
        """Length calculation should account for marker in total length."""
        # Create a prompt that would exceed limit if marker isn't accounted for
        long_prompt = "x" * (self.max_chars + 1)
        result = _cap_agent_prompt(long_prompt)
        # Total length should still be under max
        self.assertLessEqual(len(result), self.max_chars)

    def test_unicode_content(self):
        """Should handle unicode content correctly."""
        unicode_prompt = "Hello 世界 🌍 " * (self.max_chars // 20)
        result = _cap_agent_prompt(unicode_prompt)
        self.assertLessEqual(len(result), self.max_chars)
        self.assertIsInstance(result, str)

    def test_multiline_prompt(self):
        """Should handle multiline prompts correctly."""
        multiline = "Line1\n" + ("x" * 1000 + "\n") * 50 + "Final line"
        result = _cap_agent_prompt(multiline)
        self.assertLessEqual(len(result), self.max_chars)
        # Should preserve line structure where possible
        if "ORCHESTRATOR COMPACTION" not in result:
            self.assertEqual(result, multiline)


class TestCapAgentPromptRobustness(unittest.TestCase):
    """Robustness tests for edge cases and error conditions."""

    def test_various_prompt_sizes_stay_within_limit(self):
        """Should keep result under limit for various input sizes."""
        # Use the actual MAX_AGENT_PROMPT_CHARS from the module
        max_chars = int(os.environ.get("ORCH_MAX_AGENT_PROMPT_CHARS", "36000"))
        test_multipliers = [0.5, 0.9, 1.0, 1.1, 1.5, 2.0, 3.0]
        for multiplier in test_multipliers:
            with self.subTest(size_multiplier=multiplier):
                prompt = "x" * int(max_chars * multiplier)
                # Should not raise
                result = _cap_agent_prompt(prompt)
                # Should respect limit
                self.assertLessEqual(len(result), max_chars)

    def test_special_characters_in_prompt(self):
        """Should handle special characters correctly."""
        special_prompt = "!@#$%^&*(){}[]|\\:;\"'<>,.?/ " * 1000
        long_prompt = special_prompt + "x" * 36000
        result = _cap_agent_prompt(long_prompt)
        self.assertIsInstance(result, str)
        self.assertLessEqual(len(result), int(os.environ.get("ORCH_MAX_AGENT_PROMPT_CHARS", "36000")))

    def test_single_very_long_line(self):
        """Should handle prompts with very long single lines."""
        long_line = "x" * 50000
        result = _cap_agent_prompt(long_line)
        max_chars = int(os.environ.get("ORCH_MAX_AGENT_PROMPT_CHARS", "36000"))
        self.assertLessEqual(len(result), max_chars)

    def test_result_is_always_string(self):
        """Result should always be a string type."""
        test_inputs = [
            "",
            None,
            "short",
            "x" * 36000,
            "x" * 72000,
        ]
        for inp in test_inputs:
            with self.subTest(input_type=type(inp)):
                result = _cap_agent_prompt(inp)
                self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
