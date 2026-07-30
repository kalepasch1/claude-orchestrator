# Security Fix: Remove settings.local.json from Git Tracking

## Issue

The file `.claude/settings.local.json` was accidentally committed to git history. This file contains:
- Overly permissive Bash/Read allowlists
- Database access credentials
- File manipulation permissions
- Other machine-specific configuration

**This is a security regression** — machine-specific config should never be in git history.

## Root Cause

- `.claude/settings.local.json` is in `.gitignore` (correctly placed)
- However, it was committed before being added to `.gitignore`
- Now it's in the git history and needs to be removed from tracking

## Solution

### Step 1: Remove from Git Tracking

The file should be removed from git tracking without deleting it locally (since it's a working file):

```bash
git rm --cached .claude/settings.local.json
```

### Step 2: Verify Removal

Confirm it's no longer tracked:

```bash
git ls-files .claude/settings.local.json
# Should return empty
```

### Step 3: Commit

```bash
git add runner/tests/test_settings_hygiene.py
git commit -m "fix: remove settings.local.json from git tracking, add hygiene test

- Remove .claude/settings.local.json from git index (still in .gitignore)
- Add test_settings_hygiene.py to catch future regressions
- Prevent machine-specific config from being committed

Security: Settings files with allowlist and credentials should never
be in git history. The hygiene test will fail CI if this happens again."
```

## Prevention

A new test file `runner/tests/test_settings_hygiene.py` has been added that:

1. **Verifies** `.claude/settings.local.json` is in `.gitignore`
2. **Checks** that it's not tracked in git
3. **Prevents** any machine-specific files from being committed
4. **Catches** this regression in CI/testing before merge

## Notes

- The local file `.claude/settings.local.json` remains on disk (not deleted)
- Only its git tracking is removed
- Future commits will not track this file (protected by `.gitignore`)
- The hygiene test is idempotent and can be run multiple times

## Related Issues

- Prior attempt introduced this vulnerability when committing settings
- This fix addresses the security regression
- Test coverage ensures this cannot happen again
