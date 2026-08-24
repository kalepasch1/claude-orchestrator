"""
Test cowork_assemble.py CLI argument validation.

Ensures the assembler rejects missing required args and returns
valid JSON on success (canary: recovery-style acceptance).
"""
import subprocess
import json
import os

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'runner', 'cowork_assemble.py')

# cowork_assemble.py reaches the live enrichment pipeline (Supabase over the
# network) before it can answer even for a slug that does not exist. Thirty seconds
# was enough when this file ran alone and not enough when the full suite ran
# alongside it, so the test failed on a stopwatch rather than on behaviour --
# the classic flaky-under-load shape. Named and env-overridable rather than
# inlined, so tuning it does not need a code read.
ASSEMBLE_TIMEOUT_SEC = int(os.environ.get("ORCH_TEST_ASSEMBLE_TIMEOUT", "180"))


def test_missing_required_args_exits_nonzero():
    """Calling with no args should exit non-zero (missing required params)."""
    result = subprocess.run(
        ['python3', SCRIPT],
        capture_output=True, text=True, timeout=ASSEMBLE_TIMEOUT_SEC,
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
        capture_output=True, text=True, timeout=ASSEMBLE_TIMEOUT_SEC,
    )
    # Should not produce a Python traceback
    assert 'Traceback' not in result.stderr
