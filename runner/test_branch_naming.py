"""Tests for branch_naming module."""
import pytest
from branch_naming import get_expected_feature_branch_name, get_agent_branch_name


class TestGetExpectedFeatureBranchName:
    def test_basic(self):
        assert get_expected_feature_branch_name("project123", "task456") == "feature/project123-task456"

    def test_uuid_ids(self):
        result = get_expected_feature_branch_name("99f45988-68cc-430d", "7dd990c1-915e")
        assert result == "feature/99f45988-68cc-430d-7dd990c1-915e"

    def test_empty_strings(self):
        assert get_expected_feature_branch_name("", "") == "feature/-"

    def test_single_char(self):
        assert get_expected_feature_branch_name("a", "b") == "feature/a-b"


class TestGetAgentBranchName:
    def test_basic(self):
        assert get_agent_branch_name("my-task") == "agent/my-task"

    def test_empty(self):
        assert get_agent_branch_name("") == "agent/"
