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


# --- fixture discrimination -------------------------------------------------
#
# This scan was red on 12 lines, every one of them a TEST FIXTURE: the redaction
# tests, the secret-risk-pool tests and the remote-url guard all have to contain
# secret-SHAPED strings, because a string that does not look like a secret cannot
# prove a redactor redacts one.
#
# The tempting fixes are both wrong. Deleting the fixtures removes the coverage
# that makes redaction trustworthy. Skipping every test file blinds the scanner in
# exactly the directory where a careless paste is most likely (a debugging session
# that pins a real token into a test). So the discrimination is made on the VALUE:
# a fixture is low-entropy by construction — a run of the alphabet, a repeated
# character, a digit ramp, or a vendor's published documentation sample. A real
# credential is none of those.
#
# Anything that looks random is still a violation, wherever it appears.

#: Vendor documentation samples. Public, revoked, and impossible to derive from an
#: entropy rule because they were generated to LOOK real.
KNOWN_DOC_SAMPLES = {
    'AKIAIOSFODNN7EXAMPLE',                       # AWS docs
    'ghp_16C7e42F292c6912E7710c838347Ae178B4a',   # GitHub docs
}

#: This file's own negative-test fixtures — locally generated, never valid, and
#: deliberately high-entropy so they PROVE the filter below still rejects something
#: that looks real. They are allowlisted by exact value rather than by entropy,
#: because being indistinguishable from a real secret is the entire point of them.
SELF_TEST_SAMPLES = {
    'sk-7Qv3Zx9Lm2Tk8Rb4Ny6Wd1Hs5Gj0Pf',
    'ghp_9Kd2Wq7Lz4Vn8Bx3Mr6Ty1Hs5Gj0PfQz42Ab',
    'xoxb-9427310586-Zq7Lm3Vn8Bx',
    'AKIA7QVZXLMTKRBNY6WD',
}

_ASCENDING_RUN = 8


def _has_ascending_run(body, length=_ASCENDING_RUN):
    """True when *body* contains `length` consecutive ascending characters
    ('abcdefgh', '12345678') — the signature of a hand-typed placeholder."""
    run = 1
    for prev, current in zip(body, body[1:]):
        run = run + 1 if ord(current) - ord(prev) == 1 else 1
        if run >= length:
            return True
    return False


def is_obvious_fixture(secret):
    """True when *secret* is plainly a placeholder rather than a credential."""
    if not secret:
        return True
    if secret in KNOWN_DOC_SAMPLES or 'EXAMPLE' in secret.upper():
        return True
    # Strip the vendor prefix; the entropy question is about the body.
    body = re.sub(r'^(sk-|ghp_|ghu_|xoxb-|AKIA)', '', secret)
    if len(set(body)) <= max(2, len(body) // 4):   # 'AAAA…', 'abababab'
        return True
    return _has_ascending_run(body)


class TestEnvSafety(unittest.TestCase):
    """Verify that committed files do not contain leaked secrets."""

    def _repo_root(self) -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_no_hardcoded_secrets_in_source(self):
        """Scan source files for patterns matching real API keys or tokens."""
        violations = []
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
                try:
                    with open(fpath, 'r', errors='replace') as f:
                        for lineno, line in enumerate(f, 1):
                            for pat in SECRET_PATTERNS:
                                found = pat.search(line)
                                if not found:
                                    continue
                                secret = found.group(0)
                                if secret in SELF_TEST_SAMPLES:
                                    continue  # this file's own negative fixtures
                                if not is_obvious_fixture(secret):
                                    violations.append(f'{fpath}:{lineno}')
                except (OSError, UnicodeDecodeError):
                    pass
        self.assertEqual(violations, [], f'Potential secrets found: {violations}')

    def test_the_fixture_filter_still_catches_a_random_looking_secret(self):
        """A filter nobody has seen reject something is not a filter.

        These are locally generated, never-valid strings with fixture structure
        deliberately removed: no ascending run, no repetition, no EXAMPLE.
        """
        for secret in sorted(SELF_TEST_SAMPLES):
            self.assertFalse(is_obvious_fixture(secret),
                             f'{secret!r} would have been waved through')
            self.assertTrue(any(p.search(secret) for p in SECRET_PATTERNS),
                            f'{secret!r} does not match any scanner pattern')

    def test_the_fixture_filter_recognises_the_placeholders_in_this_repo(self):
        for secret in (
            'sk-abcdefghijklmnopqrstuvwxyz012345',
            'ghp_abcdefghijklmnopqrstuvwxyz0123456789',
            'ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
            'xoxb-1234567890123-1234567890123',
            'AKIAIOSFODNN7EXAMPLE',
            'ghp_16C7e42F292c6912E7710c838347Ae178B4a',
        ):
            self.assertTrue(is_obvious_fixture(secret), secret)

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
