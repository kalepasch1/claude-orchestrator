"""Recovery stub. Env gate: ORCH_STUB_ENABLED (default OFF)."""
import os
ENABLED = os.environ.get('ORCH_STUB_ENABLED', '').lower() == 'true'
def check(): return ENABLED
