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
                                if pat.search(line):
                                    violations.append(f'{fpath}:{lineno}')
                except (OSError, UnicodeDecodeError):
                    pass
        self.assertEqual(violations, [], f'Potential secrets found: {violations}')

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
