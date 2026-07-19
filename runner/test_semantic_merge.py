"""Tests for runner/semantic_merge.py"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable semantic merge to avoid side effects; tests call internals directly
os.environ["ORCH_SEMANTIC_MERGE"] = "false"
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_DB_ENABLED"] = "false"

import semantic_merge


# ---- test _extract_regions (internal) ----

def test_extract_regions_basic():
    """_extract_regions splits a Python file into import, function, class regions."""
    source = (
        "import os\n"
        "import sys\n"
        "\n"
        "def foo():\n"
        "    return 1\n"
        "\n"
        "class Bar:\n"
        "    pass\n"
    )
    regions = semantic_merge._extract_regions(source)
    assert len(regions) >= 3, f"Expected at least 3 regions, got {len(regions)}"
    kinds = [r.kind for r in regions]
    assert "import" in kinds
    assert "function" in kinds
    assert "class" in kinds
    # Check that the function region has the right name
    func_regions = [r for r in regions if r.kind == "function"]
    assert func_regions[0].name == "foo"


# ---- test can_auto_merge returns expected dict shape ----

def test_can_auto_merge_disabled():
    """When disabled, can_auto_merge returns mergeable=False with strategy=disabled."""
    result = semantic_merge.can_auto_merge("base", "a", "b", "test.py")
    assert isinstance(result, dict)
    assert "mergeable" in result
    assert result["mergeable"] is False
    assert result["strategy"] == "disabled"


def test_can_auto_merge_enabled_disjoint():
    """With ENABLED forced True, disjoint function edits should be mergeable."""
    # Temporarily override the module-level flag
    old = semantic_merge._ENABLED
    semantic_merge._ENABLED = True
    try:
        base = "import os\n\ndef foo():\n    return 1\n\ndef bar():\n    return 2\n"
        a = "import os\n\ndef foo():\n    return 42\n\ndef bar():\n    return 2\n"
        b = "import os\n\ndef foo():\n    return 1\n\ndef bar():\n    return 99\n"
        result = semantic_merge.can_auto_merge(base, a, b, "test.py")
        assert isinstance(result, dict)
        assert "mergeable" in result
        assert "confidence" in result
        assert "strategy" in result
        # Disjoint regions should be mergeable
        assert result["mergeable"] is True
        assert result["strategy"] == "ast_disjoint_regions"
    finally:
        semantic_merge._ENABLED = old


def test_can_auto_merge_null_input():
    """Null input returns mergeable=False gracefully."""
    old = semantic_merge._ENABLED
    semantic_merge._ENABLED = True
    try:
        result = semantic_merge.can_auto_merge(None, "a", "b")
        assert result["mergeable"] is False
        assert result["strategy"] == "null_input"
    finally:
        semantic_merge._ENABLED = old


# ---- test semantic_merge end-to-end ----

def test_semantic_merge_disabled():
    """semantic_merge returns merged=None when disabled."""
    result = semantic_merge.semantic_merge("base", "a", "b", "test.py")
    assert isinstance(result, dict)
    assert result["merged"] is None
    assert "disabled" in result["conflicts"]
