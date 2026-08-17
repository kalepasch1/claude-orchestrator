"""Order-independent imports for modules that live in `runner/`.

`runner/` is both a package (`runner/__init__.py`) and the directory holding
`runner.py`, `db.py`, `log.py`. A bare `import runner` therefore resolves to
whichever of the two got onto `sys.path` first — and because `sys.modules`
caches that decision, the FIRST test file in a session to import it decides for
every file after it.

That is why `tests/test_emit_task_log.py` passed on its own and failed in the
full suite: the hisanta tests put the repo root on `sys.path`, `import runner`
bound to the empty package, and `hasattr(runner, "emit_task_log")` went False.

Loading by explicit file location removes the ambiguity, so these tests give the
same answer whatever order pytest collects them in.
"""
import importlib.util
import os
import sys

RUNNER_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner")
)


def load(name):
    """Import `runner/<name>.py` by path, evicting a wrongly-bound cache entry."""
    path = os.path.join(RUNNER_DIR, name + ".py")
    if not os.path.exists(path):
        raise ImportError(f"no such runner module: {path}")

    cached = sys.modules.get(name)
    cached_file = getattr(cached, "__file__", None) if cached is not None else None
    if cached_file and os.path.realpath(cached_file) == os.path.realpath(path):
        return cached

    # runner.py does `import db` / `import log` relative to its own directory.
    if RUNNER_DIR not in sys.path:
        sys.path.insert(0, RUNNER_DIR)

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so a self-referential import resolves to this object.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_isolated(name, alias=None):
    """Load `runner/<name>.py` as a PRIVATE copy, leaving `sys.modules[name]` alone.

    Transport tests need to override module-level state such as db.URL and the
    pinned-endpoint cache. Doing that to the shared instance leaks: db pins the
    endpoint that last answered in module globals, so a placeholder host set here
    outlived the file and left later tests dialling a hostname that does not
    resolve until they timed out. A private copy cannot leak.
    """
    path = os.path.join(RUNNER_DIR, name + ".py")
    if not os.path.exists(path):
        raise ImportError(f"no such runner module: {path}")
    if RUNNER_DIR not in sys.path:
        sys.path.insert(0, RUNNER_DIR)

    alias = alias or f"_isolated_{name}"
    spec = importlib.util.spec_from_file_location(alias, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)          # deliberately NOT registered in sys.modules
    return module
