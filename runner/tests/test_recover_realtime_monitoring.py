"""Recovery test: action_drafter SAFE_CMD + UNSAFE regex patterns."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from action_drafter import SAFE_CMD, UNSAFE


def test_safe_cmd_npm_build():
    assert SAFE_CMD.match("npm run build")

def test_safe_cmd_prisma_migrate():
    assert SAFE_CMD.match("npx prisma migrate deploy")

def test_safe_cmd_rejects_arbitrary():
    assert SAFE_CMD.match("rm -rf /") is None

def test_unsafe_catches_secret():
    assert UNSAFE.search("set API_KEY=abc123")

def test_unsafe_catches_delete():
    assert UNSAFE.search("delete all records")

def test_unsafe_misses_normal():
    assert UNSAFE.search("npm run build") is None
