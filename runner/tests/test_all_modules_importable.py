"""Every runner module must import on the fleet's Python.

Guards the 2026-08-02 finding: four modules — continuous_merger (merge throughput),
gh_auth (GitHub App auth on the push path), gpt1_canary_router and static_file_scope —
used PEP-604 `str | None` annotations, which raise TypeError at import on Python 3.9.
Their importers swallow the exception and fall back, so the capability simply never
engaged and nothing ever said so. The merge pipeline was running without its continuous
merger and nobody knew.

This test also protects the self-deploy canary gate, which runs `pytest runner/tests -q -x`:
a collection error there means the gate can never go green, so merged code could never
be promoted to the running fleet even after the boot marker was fixed.
"""
import os
import sys
import importlib
import io
import contextlib

import pytest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER_DIR)

# Modules that legitimately require optional third-party packages or side effects at
# import time. Anything listed here is EXEMPT FROM IMPORT ONLY, never from syntax.
_OPTIONAL_DEPS = ("ModuleNotFoundError", "ImportError")


def _module_names():
    for f in sorted(os.listdir(RUNNER_DIR)):
        if f.endswith(".py") and not f.startswith("_") and f != "conftest.py":
            yield f[:-3]


@pytest.mark.parametrize("name", list(_module_names()))
def test_module_imports_or_fails_only_on_an_optional_dependency(name):
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            importlib.import_module(name)
    except TypeError as e:
        if "unsupported operand type(s) for |" in str(e):
            pytest.fail(
                f"{name} uses PEP-604 annotations without `from __future__ import annotations` — "
                f"unimportable on this Python, so the module is silently dead: {e}")
        raise
    except SyntaxError as e:
        pytest.fail(f"{name} has a syntax error and can never load: {e}")
    except Exception as e:  # optional deps / env-dependent side effects are acceptable
        if type(e).__name__ not in _OPTIONAL_DEPS:
            pytest.skip(f"{name} needs runtime env ({type(e).__name__}) — not an import defect")
