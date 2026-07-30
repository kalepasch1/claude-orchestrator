# Security Settings Cleanup Guide

## Problem

The file `.claude/settings.local.json` (containing overly permissive Bash/Read allowlists and database access configuration) was accidentally committed to git history in **63 commits** across multiple branches.

**Machine-specific configuration should NEVER be tracked in git**, as it creates a security regression that exposes sensitive permissions and commands to all users of the repository.

## Current Status

- ✓ `.gitignore` properly blocks future commits
- ✓ Tests in `runner/tests/test_settings_hygiene.py` detect the regression
- ⚠️ Historic git history still contains the file (63 occurrences)
- ⚠️ `git ls-files` correctly excludes it from current tracking

## Cleanup Steps

### Option 1: Using git-filter-repo (Recommended)

1. **Install git-filter-repo:**
   ```bash
   # macOS
   brew install git-filter-repo
   
   # Ubuntu/Debian
   apt-get install git-filter-repo
   
   # pip
   pip install git-filter-repo
   ```

2. **Run cleanup:**
   ```bash
   ./runner/scripts/cleanup_settings_history.sh
   ```
   
   Or manually:
   ```bash
   git filter-repo --path .claude/settings.local.json --invert-paths
   ```

3. **Verify cleanup:**
   ```bash
   git log --all --full-history --name-only --pretty=format: | grep -c "\.claude/settings.local.json" || echo "0"
   # Should output: 0
   ```

4. **Run security tests:**
   ```bash
   python -m pytest runner/tests/test_settings_hygiene.py -v
   # All tests should pass
   ```

5. **Force-push to remote:**
   ```bash
   git push --force --all
   git push --force origin master
   ```

6. **Inform collaborators:**
   - All developers must re-clone or force-fetch the updated history
   - Local branches will need to be reset to the new history

### Option 2: Using git filter-branch (Fallback)

If git-filter-repo is unavailable:

```bash
git filter-branch --tree-filter 'rm -f .claude/settings.local.json' -- --all
git reflog expire --expire=now --all
git gc --prune=now
```

## Prevention

### Pre-commit Hook

To prevent future accidental commits, install the pre-commit hook:

```bash
# Configure git to use .githooks directory
git config core.hooksPath .githooks

# Make hook executable
chmod +x .githooks/pre-commit

# Test it works
git status
```

The hook will reject any attempt to commit `.claude/settings.local.json`.

## Verification

Run the security tests to verify the cleanup:

```bash
python -m pytest runner/tests/test_settings_hygiene.py::TestSettingsHygiene::test_settings_local_not_in_recent_history -v
```

This test specifically checks for the regression and will fail if the file is still in history.

## Impact Assessment

After cleanup:
- **Git history**: Rewritten (all commits get new SHAs)
- **Branches**: All branches will have new commits
- **Remote**: Must force-push to update remote
- **Collaboration**: All team members must update local repos
- **Security**: Sensitive configuration is removed from all accessible history

## Test Coverage

The regression is caught by:
- `test_settings_local_in_gitignore()` - Ensures entry exists
- `test_settings_local_not_tracked()` - Verifies not in current tracking
- `test_no_allowlist_files_tracked()` - Checks for any sensitive files
- `test_no_secrets_in_tracked_settings()` - Scans tracked files for secrets
- `test_settings_local_not_in_recent_history()` - **Detects the security regression**
- `test_no_allowlist_with_dangerous_commands()` - Verifies no dangerous patterns

All tests pass only after the file is removed from git history.

## Questions?

For CI/CD integration or automation, see:
- `runner/scripts/cleanup_settings_history.sh` - Standalone cleanup script
- `runner/tests/test_settings_hygiene.py` - Comprehensive test suite
- `.githooks/pre-commit` - Prevention hook
