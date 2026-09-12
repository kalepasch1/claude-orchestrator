"""FAIL_SOFT_ERROR must not fire on process-exit control flow.

`raise SystemExit(...)` is how a CLI entry point ends the process, and a bare
`raise` inside an except handler re-raises an error the handler already
observed. Neither is "raising on bad input". Before this fix the rule flagged
every main() in the repo, which is exactly how a lint rule gets ignored.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.convention_lint import check_file  # noqa: E402


def _violations(tmp_path, source, name="sample.py"):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return [v for v in check_file(path) if v.rule == "FAIL_SOFT_ERROR"]


def test_system_exit_in_main_is_not_flagged(tmp_path):
    source = (
        "import argparse\n\n\n"
        "def main():\n"
        "    args = argparse.ArgumentParser().parse_args()\n"
        "    if not args:\n"
        "        raise SystemExit('no args')\n"
        "    return 0\n"
    )
    assert _violations(tmp_path, source) == []


def test_dotted_system_exit_is_not_flagged(tmp_path):
    source = "import builtins\n\n\ndef main():\n    raise builtins.SystemExit(2)\n"
    assert _violations(tmp_path, source) == []


def test_bare_system_exit_name_is_not_flagged(tmp_path):
    source = "def main():\n    raise SystemExit\n"
    assert _violations(tmp_path, source) == []


def test_bare_reraise_in_handler_is_not_flagged(tmp_path):
    source = (
        "import logging\n\n\n"
        "def load(path):\n"
        "    try:\n"
        "        return open(path).read()\n"
        "    except OSError:\n"
        "        logging.warning('unreadable %s', path)\n"
        "        raise\n"
    )
    assert _violations(tmp_path, source) == []


@pytest.mark.parametrize(
    "raiser",
    ["raise ValueError('bad')", "raise RuntimeError()", "raise KeyError('k')"],
)
def test_real_raises_are_still_flagged(tmp_path, raiser):
    source = f"def handle(value):\n    if not value:\n        {raiser}\n    return value\n"
    assert len(_violations(tmp_path, source)) == 1


def test_system_exit_does_not_mask_a_real_raise(tmp_path):
    source = (
        "def main(value):\n"
        "    if value is None:\n"
        "        raise SystemExit(1)\n"
        "    if value < 0:\n"
        "        raise ValueError('negative')\n"
        "    return value\n"
    )
    assert len(_violations(tmp_path, source)) == 1


def test_private_and_nested_functions_are_still_exempt(tmp_path):
    source = (
        "def _private():\n"
        "    raise ValueError('x')\n\n\n"
        "def outer():\n"
        "    def inner():\n"
        "        raise ValueError('y')\n"
        "    return inner\n"
    )
    assert _violations(tmp_path, source) == []


def test_bare_except_pass_is_still_flagged(tmp_path):
    source = "def run():\n    try:\n        pass\n    except:\n        pass\n"
    assert len(_violations(tmp_path, source)) == 1
