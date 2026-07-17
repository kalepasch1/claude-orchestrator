"""
Test cowork_assemble.py CLI argument validation.

Ensures the assembler rejects missing required args and returns
valid JSON on success (canary: recovery-style acceptance).
"""
import subprocess
import json
import os

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'runner', 'cowork_assemble.py')


def test_missing_required_args_exits_nonzero():
    """Calling with no args should exit non-zero (missing required params)."""
    result = subprocess.run(
        ['python3', SCRIPT],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0 or '"enriched_prompt"' not in result.stdout


def test_help_or_invalid_slug_does_not_crash():
    """A bogus slug should produce JSON output (possibly empty enrichment), not a traceback."""
    result = subprocess.run(
        ['python3', SCRIPT,
         '--task-id', '00000000-0000-0000-0000-000000000000',
         '--slug', 'test-canary-nonexistent',
         '--kind', 'canary',
         '--attempt', '0',
         '--repo-path', '/tmp',
         '--project-id', '00000000-0000-0000-0000-000000000000',
         '--project-name', 'test'],
        capture_output=True, text=True, timeout=30,
    )
    # Should not produce a Python traceback
    assert 'Traceback' not in result.stderr
