"""Unresolved conflict markers must never be committed.

Four tracked files (hisanta/__init__.py, hisanta/contracts/family.py,
hisanta/hisanta/contracts/family.py, hisanta/hisanta/mastery/engine.py) sat on the
default branch containing literal `<<<<<<< HEAD` / `>>>>>>> agent/...` blocks. They
were not merely ugly — they were syntactically invalid Python, so anything importing
the hisanta domain failed. Nothing asserted on it, so the state survived repeated
"fix broken tests" passes that each reported "still conflicts after N redos".

This test is the assertion that was missing. It scans every tracked text file.
"""
import os
import subprocess
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Markers are split so this file cannot match itself.
START = "<" * 7 + " "
MIDDLE = "=" * 7
END = ">" * 7 + " "

SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".tar",
                 ".ico", ".woff", ".woff2", ".ttf", ".mp3", ".mp4", ".patch", ".diff")


def _tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT,
                         capture_output=True, text=True, timeout=120)
    return [p for p in out.stdout.split("\0") if p]


class NoConflictMarkersTest(unittest.TestCase):

    def test_no_tracked_file_contains_conflict_markers(self):
        offenders = []
        for rel in _tracked_files():
            if rel.lower().endswith(SKIP_SUFFIXES):
                continue
            path = os.path.join(REPO_ROOT, rel)
            try:
                if os.path.getsize(path) > 2_000_000:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for num, line in enumerate(fh, 1):
                        if line.startswith(START) or line.startswith(END) \
                                or line.rstrip("\n") == MIDDLE:
                            offenders.append(f"{rel}:{num}")
                            break
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                continue
        self.assertEqual(offenders, [], "unresolved conflict markers committed: "
                                        + ", ".join(offenders))


class HisantaContractsIdentityTest(unittest.TestCase):
    """Both spellings of the family contracts must be the SAME objects."""

    def test_both_import_paths_yield_identical_types(self):
        import sys
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        try:
            import hisanta.contracts.family as top
            import hisanta.hisanta.contracts.family as nested
        except ImportError as exc:  # pragma: no cover - hisanta not vendored here
            self.skipTest(f"hisanta not importable: {exc}")
        for name in ("ParentApproval", "ApprovalStatus", "ConstitutionVerdict",
                     "CoppaConsent", "ParentVerificationReceipt", "constitution_check"):
            self.assertIs(getattr(top, name), getattr(nested, name), name)

    def test_constitution_gates_value_transfer(self):
        import sys
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        try:
            from hisanta.contracts.family import constitution_check, ConstitutionVerdict
        except ImportError as exc:  # pragma: no cover
            self.skipTest(f"hisanta not importable: {exc}")
        self.assertEqual(constitution_check("charge_child"), ConstitutionVerdict.DENY)
        self.assertEqual(constitution_check("purchase"), ConstitutionVerdict.ESCALATE)
        self.assertEqual(constitution_check("read_story"), ConstitutionVerdict.ALLOW)


if __name__ == "__main__":
    unittest.main()
