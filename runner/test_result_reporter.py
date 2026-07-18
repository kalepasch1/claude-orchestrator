"""
Test result reporter — parses pytest/unittest output, produces structured
JSON reports of passed/failed/total/duration.  No secrets or credentials;
any external reporting endpoint is configured via environment variables.

Env vars (all optional, safe defaults):
    TEST_REPORT_DIR   — directory to write JSON summaries (default: ./test_reports)
    TEST_REPORT_WEBHOOK_URL — if set, POST the JSON summary here
    TEST_REPORT_TIMEOUT — HTTP timeout in seconds (default: 10)
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


@dataclass
class TestCaseResult:
    name: str
    status: str  # "passed", "failed", "error", "skipped"
    duration_s: float = 0.0
    message: str = ""


@dataclass
class TestReport:
    """Structured summary of a test run."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_s: float = 0.0
    timestamp: str = ""
    source: str = ""  # "pytest" or "unittest"
    raw_summary: str = ""
    cases: List[TestCaseResult] = field(default_factory=list)
    success: bool = True

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        self.success = self.failed == 0 and self.errors == 0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

# pytest summary line:  "=== 5 passed, 2 failed, 1 error in 3.45s ==="
_PYTEST_SUMMARY_RE = re.compile(
    r"=+\s*(.*?)\s+in\s+([\d.]+)s\s*=+",
)
_PYTEST_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|skipped|warnings?|deselected)")

# pytest per-test lines:  "PASSED tests/test_foo.py::test_bar"  or  "FAILED ..."
_PYTEST_CASE_RE = re.compile(
    r"^(PASSED|FAILED|ERROR|SKIPPED)\s+(.+?)(?:\s+-\s+(.*))?$",
    re.MULTILINE,
)

# unittest summary:  "Ran 12 tests in 0.003s"  +  "OK" / "FAILED (failures=2, errors=1)"
_UNITTEST_RAN_RE = re.compile(r"Ran\s+(\d+)\s+tests?\s+in\s+([\d.]+)s")
_UNITTEST_FAIL_RE = re.compile(r"FAILED\s*\(([^)]+)\)")
_UNITTEST_CASE_RE = re.compile(
    r"^(ok|FAIL|ERROR|skip)\s+(\S+)",
    re.MULTILINE,
)


def parse_pytest(output: str) -> TestReport:
    """Parse pytest stdout/stderr into a TestReport."""
    report = TestReport(source="pytest", raw_summary="")

    # Extract per-case results
    for m in _PYTEST_CASE_RE.finditer(output):
        status_raw = m.group(1).lower()
        status_map = {"passed": "passed", "failed": "failed", "error": "error", "skipped": "skipped"}
        report.cases.append(TestCaseResult(
            name=m.group(2).strip(),
            status=status_map.get(status_raw, status_raw),
            message=(m.group(3) or "").strip(),
        ))

    # Extract summary line
    sm = _PYTEST_SUMMARY_RE.search(output)
    if sm:
        report.raw_summary = sm.group(0)
        report.duration_s = float(sm.group(2))
        counts_str = sm.group(1)
        for cm in _PYTEST_COUNT_RE.finditer(counts_str):
            count = int(cm.group(1))
            label = cm.group(2)
            if label == "passed":
                report.passed = count
            elif label == "failed":
                report.failed = count
            elif label == "error":
                report.errors = count
            elif label == "skipped":
                report.skipped = count

    report.total = report.passed + report.failed + report.errors + report.skipped

    # If no summary line found, infer from cases
    if not sm and report.cases:
        for c in report.cases:
            if c.status == "passed":
                report.passed += 1
            elif c.status == "failed":
                report.failed += 1
            elif c.status == "error":
                report.errors += 1
            elif c.status == "skipped":
                report.skipped += 1
        report.total = len(report.cases)

    report.success = report.failed == 0 and report.errors == 0
    return report


def parse_unittest(output: str) -> TestReport:
    """Parse unittest stdout/stderr into a TestReport."""
    report = TestReport(source="unittest")

    rm = _UNITTEST_RAN_RE.search(output)
    if rm:
        report.total = int(rm.group(1))
        report.duration_s = float(rm.group(2))

    fm = _UNITTEST_FAIL_RE.search(output)
    if fm:
        parts = fm.group(1)
        for piece in parts.split(","):
            piece = piece.strip()
            if piece.startswith("failures="):
                report.failed = int(piece.split("=")[1])
            elif piece.startswith("errors="):
                report.errors = int(piece.split("=")[1])
            elif piece.startswith("skipped="):
                report.skipped = int(piece.split("=")[1])

    # Per-case results (verbose unittest output)
    for m in _UNITTEST_CASE_RE.finditer(output):
        status_raw = m.group(1).lower()
        status_map = {"ok": "passed", "fail": "failed", "error": "error", "skip": "skipped"}
        report.cases.append(TestCaseResult(
            name=m.group(2).strip(),
            status=status_map.get(status_raw, status_raw),
        ))

    report.passed = report.total - report.failed - report.errors - report.skipped
    if report.passed < 0:
        report.passed = 0
    report.raw_summary = output.strip().splitlines()[-1] if output.strip() else ""
    report.success = report.failed == 0 and report.errors == 0
    return report


def auto_parse(output: str) -> TestReport:
    """Auto-detect framework and parse output."""
    if not output or not output.strip():
        return TestReport(source="unknown", raw_summary="(empty output)")
    if _PYTEST_SUMMARY_RE.search(output) or "PASSED " in output or "FAILED " in output:
        return parse_pytest(output)
    if _UNITTEST_RAN_RE.search(output):
        return parse_unittest(output)
    # Fallback: try pytest then unittest
    rpt = parse_pytest(output)
    if rpt.total > 0:
        return rpt
    rpt = parse_unittest(output)
    if rpt.total > 0:
        return rpt
    return TestReport(source="unknown", raw_summary=output.strip().splitlines()[-1] if output.strip() else "")


# ---------------------------------------------------------------------------
# Writer / reporter
# ---------------------------------------------------------------------------

def write_report(report: TestReport, directory: Optional[str] = None) -> str:
    """Write JSON report to disk. Returns the file path."""
    out_dir = directory or os.environ.get("TEST_REPORT_DIR", "./test_reports")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"test_report_{ts}.json"
    filepath = os.path.join(out_dir, filename)
    with open(filepath, "w") as f:
        f.write(report.to_json())
    return filepath


def post_report(report: TestReport) -> Optional[dict]:
    """POST report JSON to TEST_REPORT_WEBHOOK_URL if configured.
    Returns the response dict or None if not configured / on error.
    No secrets are embedded — the URL comes from env only."""
    import urllib.request
    import urllib.error

    url = os.environ.get("TEST_REPORT_WEBHOOK_URL")
    if not url:
        return None
    timeout = int(os.environ.get("TEST_REPORT_TIMEOUT", "10"))
    data = report.to_json().encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"status": resp.status, "body": resp.read().decode("utf-8", errors="replace")}
    except (urllib.error.URLError, OSError) as exc:
        return {"status": 0, "error": str(exc)}


def report_and_save(output: str, directory: Optional[str] = None) -> TestReport:
    """One-call convenience: parse, write to disk, optionally POST."""
    report = auto_parse(output)
    write_report(report, directory)
    post_report(report)
    return report
