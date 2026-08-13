#!/usr/bin/env python3
"""Shared, cwd-independent syntax guard for runner modules.

Several suites asserted syntax validity with:

    py_compile.compile("runner/<module>.py", doraise=True)

That literal path only resolves when the test process happens to start at the repo
root. CI runs the runner suite with working-directory `runner`, where it raised
FileNotFoundError — so the guard failed for a reason that had nothing to do with
syntax, and a real syntax error would have been indistinguishable from a wrong cwd.

`compile_runner_module()` derives an absolute path from this file's location, so the
guard means the same thing from any working directory.
"""
import os
import py_compile

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def runner_module_path(module_filename):
    """Absolute path of a module inside runner/, e.g. "scoreboard.py"."""
    return os.path.join(RUNNER_DIR, os.path.basename(module_filename))


def compile_runner_module(module_filename):
    """Byte-compile a runner module, raising py_compile.PyCompileError on bad syntax.

    Raises FileNotFoundError if the module does not exist, so a typo'd module name is
    reported as a missing file rather than silently passing.
    """
    target = runner_module_path(module_filename)
    if not os.path.isfile(target):
        raise FileNotFoundError(target)
    py_compile.compile(target, doraise=True)
    return target
