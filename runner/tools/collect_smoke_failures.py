#!/usr/bin/env python3
"""Run the smoke suite and record every failure as machine-readable JSON.

    python3 runner/tools/collect_smoke_failures.py --out smoke-failures.json

Writes an array of objects with exactly the keys `testName`, `file`, `error`.

WHY A PARSER AND NOT `pytest --json-report`: pytest-json-report is not in the
dependency manifest, and adding a plugin to make the failure list readable is a
bigger diff than reading the report pytest already prints. This parses the
`short test summary info` block, which is stable across pytest 7 and 8 and is
emitted with `-rf` even when the run aborts during collection — the case that
matters most here, since a collection abort is precisely when a human most needs
to know what broke and pytest reports zero test results.

Exit status is 0 whenever the report was written, including when tests failed:
the job of this tool is to produce the inventory, not to gate on it. Use
`--fail-on-failures` to invert that for CI.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_TARGETS = ["runner/tests", "tests"]

# "FAILED runner/tests/test_x.py::TestC::test_m - AssertionError: boom"
FAILED_RE = re.compile(
    r"^(?P<status>FAILED|ERROR)\s+(?P<loc>\S+?)(?:\s+-\s+(?P<err>.*))?$"
)


def parse_summary(stdout: str) -> list[dict]:
    """Extract failures from pytest's `short test summary info` section."""
    failures: list[dict] = []
    seen: set[tuple[str, str]] = set()
    in_summary = False
    for raw in stdout.splitlines():
        line = raw.strip()
        if "short test summary info" in line:
            in_summary = True
            continue
        if in_summary and line.startswith("=") and "summary" not in line:
            break
        if not in_summary:
            continue
        match = FAILED_RE.match(line)
        if not match:
            continue
        loc = match.group("loc")
        file_path, _, test_name = loc.partition("::")
        # A collection ERROR has no ::test part; the file itself is what failed.
        test_name = test_name or "<collection>"
        key = (file_path, test_name)
        if key in seen:
            continue
        seen.add(key)
        failures.append({
            "testName": test_name,
            "file": file_path,
            "error": (match.group("err") or match.group("status")).strip(),
        })
    return failures


def run(targets, timeout_s, extra_args):
    cmd = [
        sys.executable, "-m", "pytest", *targets,
        "-q", "-p", "no:randomly", f"--timeout={timeout_s}", "--tb=no", "-rfE",
    ] + list(extra_args)
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env={
            **__import__("os").environ, "COLUMNS": "500",
        },
    )
    return proc.stdout + proc.stderr, proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="smoke-failures.json")
    ap.add_argument("--targets", nargs="*", default=DEFAULT_TARGETS)
    ap.add_argument("--timeout", type=int, default=60,
                    help="per-test timeout in seconds")
    ap.add_argument("--fail-on-failures", action="store_true",
                    help="exit 1 if any failure was recorded (for CI gating)")
    ap.add_argument("pytest_args", nargs="*", default=[])
    args = ap.parse_args()

    output, _code = run(args.targets, args.timeout, args.pytest_args)
    failures = parse_summary(output)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")

    print(f"recorded {len(failures)} failing tests -> {out_path.name}")
    if failures:
        for item in failures[:10]:
            print(f"  {item['file']}::{item['testName']}: {item['error'][:110]}")
        if len(failures) > 10:
            print(f"  ... and {len(failures) - 10} more")
    return 1 if (failures and args.fail_on_failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
