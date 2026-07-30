# Security Fix: Remove Dangerous Settings File from Git

## Problem

The file `.claude/settings.local.json` contains overly permissive configuration with dangerous patterns and was accidentally committed to git. This is a **CRITICAL SECURITY REGRESSION**.

### Dangerous Patterns in Tracked File

The file contains:
- **Kill commands**: `Bash(kill 84440)`, `Bash(pkill -f 'runner.py')`
- **Database access**: `db.select()`, `db.update()` calls on production tables
- **Overly broad file permissions**: `Read(//Users/**)` patterns
- **Process manipulation**: Multiple process termination commands

### Current Status

```
$ git ls-files | grep settings.local.json
.claude/settings.local.json
```

**The file IS tracked in git.** This is the security violation.

## Fix

### Step 1: Remove from Git Tracking

```bash
# Remove from git index (keeps local file)
git rm --cached .claude/settings.local.json

# Commit the removal
git commit -m "security: remove settings.local.json from git tracking

- Removes tracked .claude/settings.local.json containing dangerous patterns
- Dangerous patterns: kill commands, database manipulation, overly broad file access
- File contains: kill 84440, pkill -f 'runner.py', db.select/update, Read(//Users/**)
- .gitignore (line 22) already protects future commits
- Complements security regression detection in test_settings_hygiene.py
- Fixes test_settings_local_not_tracked() assertion

This commit removes the file from git tracking while preserving it locally
for use in this specific environment (machine-specific configuration).

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

### Step 2: Verify .gitignore Entry

The following line should already be in `.gitignore` at line 22:

```
.claude/settings.local.json
```

This prevents future accidental commits of machine-specific configuration.

### Step 3: Verify the Fix

```bash
# Verify file is no longer tracked
git ls-files | grep settings.local.json
# (should return nothing)

# Verify file still exists locally
ls -la .claude/settings.local.json
# (should still exist)

# Run security tests to confirm fix
python3 -m pytest runner/tests/test_settings_hygiene.py::TestSettingsHygiene::test_settings_local_not_tracked -v
python3 -m pytest runner/tests/test_settings_security.py -v
```

### Step 4: Optional - Remove from All History (Advanced)

If the file should never have been in the repository at all, use `git filter-repo`:

```bash
# CAUTION: This rewrites git history and requires force-push
pip install git-filter-repo
git filter-repo --path .claude/settings.local.json --invert-paths
git push --force-with-lease origin agent/self-optimizing-pipeline
```

**Only do this if you own the branch and no one else has pulled it.**

## Why This Matters

Machine-specific configuration files should **NEVER** be committed to git because:

1. **Security Risk**: They contain allowlists for dangerous operations (kill, database access)
2. **Machine Dependency**: They're specific to one user/machine and cause conflicts when shared
3. **Accidental Exposure**: If pushed to a public repository, the dangerous allowlist is exposed
4. **Compliance**: Version control should only contain shareable code, not local configuration

## Testing

Two test suites verify this constraint:

1. **test_settings_hygiene.py**: Ensures no local settings files are tracked
   - `test_settings_local_not_tracked()` - Verifies file is not in git
   - `test_settings_local_in_gitignore()` - Verifies .gitignore has entry
   - `test_settings_local_not_in_recent_history()` - Verifies file removed from history

2. **test_settings_security.py**: Comprehensive security validation
   - `test_settings_local_json_not_tracked()` - Critical constraint
   - `test_dangerous_patterns_in_local_settings()` - Pattern detection
   - `test_no_machine_specific_allowlists_tracked()` - Pattern validation

## Implementation

The fix is implemented via:

1. **runner/security_check.py** - Automated security scanner that detects violations
2. **runner/tests/test_settings_security.py** - New comprehensive security tests
3. **runner/tests/test_settings_hygiene.py** - Existing hygiene tests

All tests verify that `.claude/settings.local.json` is:
- Not tracked in git (`git ls-files`)
- Not in git history (`git log --all`)
- Present in .gitignore
- Never contains dangerous patterns if tracked

## References

- **Task**: self-optimizing-pipeline security regression fix
- **Branch**: agent/self-optimizing-pipeline
- **Memory**: [[self-optimizing-pipeline-security-fix]]
- **Previous attempt**: Identified issue but blocked by git ops permissions

## Verification Checklist

- [ ] File removed from git index: `git ls-files .claude/settings.local.json` returns empty
- [ ] File still exists locally: `ls .claude/settings.local.json` shows the file
- [ ] Commit created with security fix message
- [ ] test_settings_local_not_tracked() passes
- [ ] test_settings_security.py all tests pass
- [ ] .gitignore contains `.claude/settings.local.json` entry
- [ ] No other machine-specific files are tracked
