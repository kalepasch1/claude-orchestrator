"""Tests for runner/output_distiller.py"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_OUTPUT_DISTILLER_ENABLED"] = "true"
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_DB_ENABLED"] = "false"

import output_distiller


def test_distill_returns_dict_with_expected_keys():
    """distill() extracts recipe from agent output and returns structured dict."""
    task = {"slug": "fix-login-form"}
    agent_output = (
        "I'll fix the login validation.\n"
        "Read 'src/auth.py'\n"
        "The issue is that the password check was inverted.\n"
        "Error: ValueError on empty input\n"
        "Fixed by adding a guard clause.\n"
    )
    diff_text = (
        "diff --git a/src/auth.py b/src/auth.py\n"
        "+++ b/src/auth.py\n"
        "@@ -10,3 +10,5 @@\n"
        "+    if not password:\n"
        "+        raise ValueError('empty')\n"
    )
    result = output_distiller.distill(task, agent_output, diff_text, "claude-sonnet", 0.05)
    assert isinstance(result, dict)
    for key in ("recipe", "steps", "key_decisions", "files_pattern", "files_read", "model", "cost_usd"):
        assert key in result, f"Missing key: {key}"
    assert "src/auth.py" in result["files_read"]
    assert "src/auth.py" in result["files_pattern"]
    assert result["model"] == "claude-sonnet"


def test_slug_prefix_extracts_first_two_segments():
    """_slug_prefix returns first 2 hyphen-delimited segments."""
    assert output_distiller._slug_prefix("fix-login-form-v2") == "fix-login"
    assert output_distiller._slug_prefix("add-tests") == "add-tests"
    assert output_distiller._slug_prefix("x") == "x"
    assert output_distiller._slug_prefix("") == "unknown"
    assert output_distiller._slug_prefix(None) == "unknown"


def test_inject_recipe_adds_content():
    """inject_recipe appends a recipe block to the prompt."""
    prompt = "Please fix the bug."
    recipe = {"recipe": "RECIPE: fix-login\nREAD: src/auth.py\nAPPROACH: add guard clause"}
    result = output_distiller.inject_recipe(prompt, recipe)
    assert isinstance(result, str)
    assert result.startswith(prompt)
    assert "Proven Recipe" in result
    assert "fix-login" in result
    assert len(result) > len(prompt)


def test_inject_recipe_no_recipe():
    """inject_recipe returns prompt unchanged when recipe is None or empty."""
    prompt = "Do something."
    assert output_distiller.inject_recipe(prompt, None) == prompt
    assert output_distiller.inject_recipe(prompt, {}) == prompt
    assert output_distiller.inject_recipe(prompt, {"recipe": ""}) == prompt
