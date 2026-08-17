"""
sibling_import.py — resolve a runner/ sibling module regardless of how the caller
was imported.

Why this exists (2026-08-12): the merge-train guards do a bare
``import regression_guard``. That only resolves while ``runner/`` itself is on
sys.path. Every guard module inserts its own directory at import time, but any
caller that later rebuilds sys.path — a subprocess started with isolated mode, an
embedder that imports ``runner.merge_train`` as a package and then trims the path,
a vendored copy loaded by file path — drops that entry. The bare import then raises
``ModuleNotFoundError: No module named 'regression_guard'`` and, because the merge
gates FAIL CLOSED, a purely additive branch is reported as a regression and blocked.
That is what happened to
``agent/dropbox-beethoven-fleet-immune-system-throughput-accelerators-operat-contracts-c``,
whose diff against base was 705 insertions and 0 deletions.

Resolution order: plain module name, then ``runner.<name>``, then a direct
file-path load out of this file's own directory. The last step needs no sys.path
at all, so it works even when the first two cannot.

Fail-soft: returns None when the module genuinely cannot be found. Callers keep
their own fail-closed policy — this module only removes the *false* unavailable.
"""

import importlib
import importlib.util
import os
import sys

__all__ = ["load_sibling", "sibling_dir"]


def sibling_dir():
    """Directory holding the runner/ sibling modules ('' if undeterminable)."""
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return ""


def _by_path(name):
    directory = sibling_dir()
    if not directory or not name:
        return None
    path = os.path.join(directory, "{0}.py".format(name))
    if not os.path.isfile(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        # Register before exec so a self-referential import inside the module
        # resolves to this same object instead of recursing.
        sys.modules.setdefault(name, module)
        spec.loader.exec_module(module)
        return sys.modules.get(name, module)
    except Exception:
        sys.modules.pop(name, None)
        return None


def load_sibling(name):
    """Import runner/<name>.py by any means available, or return None.

    Never raises: a missing module, a syntax error inside it, or an unreadable
    directory all yield None so the caller can apply its own policy.
    """
    if not name or not isinstance(name, str):
        return None
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    for candidate in (name, "runner.{0}".format(name)):
        try:
            return importlib.import_module(candidate)
        except Exception:
            continue
    return _by_path(name)
