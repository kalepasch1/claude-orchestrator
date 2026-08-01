#!/usr/bin/env python3
"""Re-export shim: the canonical module lives at runner/merged_diff_library.py.

Kept at repo root so any legacy `import merged_diff_library` from a root-level
script still resolves, without maintaining a second divergent copy.
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNNER_DIR = os.path.join(_HERE, "runner")
sys.path.insert(0, _RUNNER_DIR)  # the runner module does `import db` relative to its own dir

_spec = importlib.util.spec_from_file_location(
    "_canonical_merged_diff_library", os.path.join(_RUNNER_DIR, "merged_diff_library.py")
)
_canonical = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_canonical)

globals().update({k: v for k, v in vars(_canonical).items() if not k.startswith("__")})
