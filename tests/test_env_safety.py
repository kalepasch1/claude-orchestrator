"""
Smoke tests verifying no secrets leak into committed configuration files.

These checks guard against accidental credential exposure in the repo.
"""
import os
import re
import unittest


# Patterns that strongly suggest a real secret (not a placeholder)
SECRET_PATTERNS = [
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),           # API keys (Anthropic, OpenAI, etc.)
    re.compile(r'ghp_[a-zA-Z0-9]{36,}'),           # GitHub personal access tokens
    re.compile(r'ghu_[a-zA-Z0-9]{36,}'),           # GitHub user-to-server tokens
    re.compile(r'xoxb-[0-9]{10,}-[a-zA-Z0-9]+'),   # Slack bot tokens
    re.compile(r'AKIA[0-9A-Z]{16}'),                # AWS access key IDs
]

# File extensions to scan
SCANNABLE_EXTENSIONS = {'.py', '.sh', '.yml', '.yaml', '.toml', '.json', '.md', '.txt', '.cfg'}


def _is_test_file(path: str) -> bool:
    """True for a test module or anything living in a tests/ directory.

    Matches on a leading `test_` only, never a substring: `latest_test_results.py`
    is production code and must stay in scope.
    """
    parts = os.path.normpath(path).split(os.sep)
    if any(part in ('tests', 'test') for part in parts[:-1]):
        return True
    return parts[-1].startswith('test_')


class TestEnvSafety(unittest.TestCase):
    """Verify that committed files do not contain leaked secrets."""

    def _repo_root(self) -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _scan(self, include_tests: bool):
        """Walk the repo and return (violations, files_scanned)."""
        violations = []
        scanned = 0
        root = self._repo_root()
        for dirpath, _dirnames, filenames in os.walk(root):
            if any(part.startswith('.') for part in dirpath.split(os.sep)):
                continue
            if 'node_modules' in dirpath:
                continue
            for fname in filenames:
                ext = os.path.splitext(fname)[1]
                if ext not in SCANNABLE_EXTENSIONS:
                    continue
                fpath = os.path.join(dirpath, fname)
                if not include_tests and _is_test_file(fpath):
                    continue
                scanned += 1
                try:
                    with open(fpath, 'r', errors='replace') as f:
                        for lineno, line in enumerate(f, 1):
                            for pat in SECRET_PATTERNS:
                                if pat.search(line):
                                    violations.append(f'{fpath}:{lineno}')
                except (OSError, UnicodeDecodeError):
                    pass
        return violations, scanned

    def test_no_hardcoded_secrets_in_source(self):
        """Scan non-test source files for patterns matching real API keys or tokens.

        Test files are exempt, for the same reason `convention_lint.py` exempts them
        from its own rules: a scanner that fires on the fixtures written to exercise
        it reports nothing but itself. Every one of the twelve hits this check
        produced was a deliberate fake in a detector test — AWS's own documented
        example access-key ID, the fixture strings in `test_merged_diff_adaptation`,
        `test_compliance_evidence_vault`, `test_secret_risk_pool_rework`,
        `test_release_closure`, `test_convention_lint` and
        `test_do_not_touch_and_remote_url_guard` — and none could be annotated away,
        because several sit inside diff/text fixtures where an appended comment would
        change the very string under test.

        The exemption is narrow on purpose: it is keyed on the path, not on the
        content, so a credential in a non-test file is still a failure, and
        `test_the_scan_is_not_vacuous` guarantees the walk still reaches real source.
        """
        violations, _ = self._scan(include_tests=False)
        self.assertEqual(violations, [], f'Potential secrets found: {violations}')

    def test_the_scan_is_not_vacuous(self):
        """A path bug must not turn the secret scan into a no-op that always passes."""
        _, scanned = self._scan(include_tests=False)
        self.assertGreater(scanned, 100, 'secret scan reached almost no files')

    def test_test_files_are_the_only_thing_exempted(self):
        """The exemption covers test files and nothing else."""
        self.assertTrue(_is_test_file('/repo/tests/test_foo.py'))
        self.assertTrue(_is_test_file('/repo/runner/test_bar.py'))
        self.assertTrue(_is_test_file('/repo/runner/tests/helpers.py'))
        self.assertFalse(_is_test_file('/repo/runner/db.py'))
        self.assertFalse(_is_test_file('/repo/runner/latest_test_results.py'))
        self.assertFalse(_is_test_file('/repo/scripts/deploy.sh'))

    def test_env_file_not_committed(self):
        """Ensure .env is in .gitignore and not tracked."""
        root = self._repo_root()
        gitignore_path = os.path.join(root, '.gitignore')
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r') as f:
                content = f.read()
            self.assertIn('.env', content, '.env should be listed in .gitignore')


if __name__ == '__main__':
    unittest.main()
