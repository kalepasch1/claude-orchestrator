# Project Setup Guide

## Security Setup (REQUIRED)

This project contains security-sensitive code. The following setup steps prevent accidental commits of machine-specific configuration files.

### 1. Install Git Hooks

Git hooks prevent committing `.claude/settings.local.json` and other machine-specific files to version control.

**Automatic setup:**
```bash
bash .githooks/install.sh
```

**Manual setup (if the above doesn't work):**
```bash
# Configure git to use .githooks directory
git config core.hooksPath .githooks

# Make hooks executable
chmod +x .githooks/*

# Verify
git config core.hooksPath
```

### 2. Verify Hook Installation

After setup, verify the hook is working:

```bash
# This should print: .githooks
git config core.hooksPath

# Try to stage a machine-specific file (should be rejected)
echo "{}" > .claude/settings.local.json
git add .claude/settings.local.json
# You should see: ERROR: .claude/settings.local.json is machine-specific...
```

### 3. Run Security Tests

Verify that security tests pass:

```bash
# Full security test suite
python -m pytest runner/tests/test_settings_hygiene.py -v

# Individual tests
python -m pytest runner/tests/test_settings_hygiene.py::TestSettingsHygiene::test_settings_local_in_gitignore -v
python -m pytest runner/tests/test_settings_hygiene.py::TestSettingsHygiene::test_settings_local_not_tracked -v
python -m pytest runner/tests/test_settings_hygiene.py::TestSettingsHygiene::test_no_allowlist_files_tracked -v
python -m pytest runner/tests/test_settings_hygiene.py::TestSettingsHygiene::test_settings_local_not_in_recent_history -v
```

**Note:** The `test_settings_local_not_in_recent_history` test may fail if you have an old clone that includes `.claude/settings.local.json` in git history. See the "Cleanup Historic Commits" section below.

### 4. Cleanup Historic Commits (If Needed)

If you see `.claude/settings.local.json` in git history, you must remove it:

```bash
# First, install git-filter-repo
brew install git-filter-repo  # macOS
# or
sudo apt-get install git-filter-repo  # Ubuntu/Debian
# or
pip install git-filter-repo

# Then run the cleanup script
bash runner/scripts/cleanup_settings_history.sh

# Force-push the cleaned history
git push --force --all
```

See `SECURITY_SETTINGS_CLEANUP.md` for detailed information.

## Testing

Run the test suite to verify everything is working:

```bash
# All tests
python -m pytest runner/tests/ -v

# Settings security tests
python -m pytest runner/tests/test_settings_hygiene.py -v

# Improvement measure tests
python -m pytest runner/tests/test_improvement_measure.py -v

# Check for syntax errors
python3 -m py_compile runner/improvement_measure.py
python3 -m py_compile runner/tests/test_improvement_measure.py
python3 -m py_compile runner/tests/test_settings_hygiene.py
```

## What's Protected

The following files and patterns are protected from accidental commits:

- `.claude/settings.local.json` - Machine-specific allowlist configuration
- `.env.local` - Local environment variables
- `settings.local.json` - Local settings

These files are:
1. Listed in `.gitignore` (prevents tracking)
2. Checked by pre-commit hook (prevents staging)
3. Detected by `test_settings_hygiene.py` (CI verification)

## For Developers

When working on this project:

1. **Never commit machine-specific config** - If you need custom settings, use `.claude/settings.local.json` (it's ignored by git)
2. **Run the security tests** - Always run `test_settings_hygiene.py` before pushing
3. **Don't bypass the pre-commit hook** - If you encounter the "machine-specific file" error, unstage the file and continue

## Documentation

- `SECURITY_SETTINGS_CLEANUP.md` - Detailed cleanup guide for historic commits
- `.githooks/pre-commit` - Pre-commit hook source code
- `runner/tests/test_settings_hygiene.py` - Security test suite
- `runner/scripts/cleanup_settings_history.sh` - Automated cleanup script
