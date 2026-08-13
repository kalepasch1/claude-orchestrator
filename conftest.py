"""Root pytest conftest — pin `runner` to the package, not runner/runner.py.

Why this file exists
--------------------
Many modules under runner/ (and the tests that exercise them) do

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

so that flat sibling imports like `import merged_diff_memory` resolve. That is
fine on its own, but it also puts the runner/ DIRECTORY on sys.path — which
makes runner/runner.py importable as a *top-level module* named `runner`.

Under `pytest tests/` everything is collected in one process, so whichever test
imports first wins the name. When a test that pushed runner/ onto sys.path went
first, `sys.modules["runner"]` became the runner.py MODULE, and every later
`from runner.<x> import ...` died with:

    ModuleNotFoundError: No module named 'runner.enqueue'; 'runner' is not a package
    ImportError: cannot import name 'prompt_evolver' from 'runner' (.../runner/runner.py)

That was 12 collection errors on master — an ordering artefact, not a real
breakage: every one of those modules imports cleanly on its own.

conftest.py is imported by pytest before any test module, so binding the real
package here settles the name once, up front. Later sys.path pushes are then
harmless: sys.modules["runner"] already holds the package.

Deliberately non-invasive
-------------------------
The package is loaded from its known file location rather than by reordering
sys.path. An earlier draft removed and re-inserted the repo root at position 0;
that shifted import order for unrelated suites and perturbed order-sensitive
tests (tests/test_core_retry_rpcs.py). Binding by file location fixes the
shadowing without changing how anything else resolves.

Fail-soft on purpose — if the package cannot be loaded we stay silent and let
each test report its own error, rather than breaking collection for the suite.
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
_PKG_INIT = os.path.join(ROOT, "runner", "__init__.py")


def _bind_runner_package():
    """Put the real runner/ package in sys.modules['runner'], once."""
    existing = sys.modules.get("runner")
    if existing is not None and getattr(existing, "__path__", None):
        return  # already the package — nothing to do
    if not os.path.isfile(_PKG_INIT):
        return
    spec = importlib.util.spec_from_file_location(
        "runner", _PKG_INIT, submodule_search_locations=[os.path.join(ROOT, "runner")]
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules["runner"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("runner", None)
        raise


try:
    _bind_runner_package()
except Exception:  # pragma: no cover - diagnostics only, never break collection
    pass
