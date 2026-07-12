"""Tests for branch_naming.deduplicate_slug and validate_slug."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import branch_naming


def test_no_collision():
    assert branch_naming.deduplicate_slug("foo", set()) == "foo"
    assert branch_naming.deduplicate_slug("foo", {"bar", "baz"}) == "foo"


def test_simple_collision():
    assert branch_naming.deduplicate_slug("foo", {"foo"}) == "foo-2"


def test_chained_collision():
    assert branch_naming.deduplicate_slug("foo", {"foo", "foo-2"}) == "foo-3"
    assert branch_naming.deduplicate_slug("foo", {"foo", "foo-2", "foo-3"}) == "foo-4"


def test_empty_slug():
    assert branch_naming.deduplicate_slug("", set()) == ""
    assert branch_naming.deduplicate_slug("", {"foo"}) == ""


def test_none_existing():
    assert branch_naming.deduplicate_slug("bar", None) == "bar"


def test_validate_valid():
    ok, reason = branch_naming.validate_slug("improve-foo-bar")
    assert ok is True and reason == ""


def test_validate_empty():
    ok, reason = branch_naming.validate_slug("")
    assert ok is False


def test_validate_too_long():
    ok, reason = branch_naming.validate_slug("a" * 121)
    assert ok is False


def test_agent_branch_name():
    assert branch_naming.get_agent_branch_name("my-slug") == "agent/my-slug"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("All tests passed.")
