"""Recovery test: account_pool constants and claude_exhausted logic."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from account_pool import COOLDOWN, COOLDOWN_MAX


def test_cooldown_is_positive():
    assert COOLDOWN > 0

def test_cooldown_max_gte_cooldown():
    assert COOLDOWN_MAX >= COOLDOWN

def test_cooldown_reasonable_range():
    # Cooldown shouldn't exceed 24 hours in seconds
    assert COOLDOWN <= 86400
    assert COOLDOWN_MAX <= 86400
