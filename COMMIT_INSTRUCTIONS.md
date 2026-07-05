# Cleanup Instructions for agent/build-only-gate-lowrisk

## Summary
The LLM gating policy implementation is complete and tested. However, there is one file that should not be tracked in git:

- `.claude/settings.local.json` - machine-specific settings that are in `.gitignore` but were accidentally committed

## To Complete the Merge

Run these commands:

```bash
# Remove the settings file from git tracking (file stays on disk)
git rm --cached .claude/settings.local.json

# Verify the removal
git status

# Commit the cleanup
git commit -m "chore: remove machine-specific settings from git tracking

.claude/settings.local.json is machine-local and in .gitignore,
should not be committed to the repository."
```

## What Was Implemented

✅ **result_classifier.py** - Detects `error_max_turns` metadata objects (when max turns limit is reached)
✅ **auto_remediate.py** - Routes max_turns errors through intelligent remediation:
   - Under CAP: Simple retry
   - At CAP: Escalate model + implement with focused approach
✅ **model_policy.py** - LLM call gating policy that skips expensive LLM verification for low-risk diffs
✅ **Tests** - Comprehensive test coverage:
   - runner/tests/test_auto_remediate.py: max_turns retry & escalation tests
   - tests/test_result_classifier.py: error classification tests
   - runner/tests/test_model_routing.py: LLM gating policy tests

## Verification

All tests can be run with:

```bash
# Test auto_remediate max_turns handling
python3 -m unittest runner.tests.test_auto_remediate.TestAutoRemediateRecoveryTest.test_max_turns_retries_under_cap
python3 -m unittest runner.tests.test_auto_remediate.TestAutoRemediateRecoveryTest.test_max_turns_escalates_at_cap

# Test result classifier
python3 tests/test_result_classifier.py

# Test LLM gating policy
python3 -m unittest runner.tests.test_model_routing.LLMVerifyGatingTest
```

## Benefits

- **Cuts ~2 LLM calls per low-risk task** by gating expensive verify steps when tests + build already pass
- **Gracefully handles max_turns errors** with retry + escalation strategy
- **Reduces token costs** and improves throughput for low-blast-radius diffs
