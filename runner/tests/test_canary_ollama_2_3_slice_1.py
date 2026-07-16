"""Canary test: action_drafter PROMPT template structure (ollama-2-3-slice-1)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from action_drafter import PROMPT, SAFE_CMD, UNSAFE


def test_prompt_has_placeholders():
    assert "{title}" in PROMPT
    assert "{why}" in PROMPT

def test_prompt_mentions_json():
    assert "JSON" in PROMPT

def test_prompt_forbids_secrets():
    assert "secret" in PROMPT.lower() or "token" in PROMPT.lower()

def test_safe_cmd_git_pull():
    assert SAFE_CMD.match("git pull --ff-only")

def test_unsafe_catches_force():
    assert UNSAFE.search("force delete the database")
