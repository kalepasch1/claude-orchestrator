# Canary Task Acceptance Criteria

Defines the pass/fail criteria for canary tasks used in coder routing.

## What a Canary Must Do

1. Make exactly **one** tiny, safe change (doc, test, or hygiene)
2. **Not** change secrets, dependencies, package managers, billing,
   legal copy, or product behavior
3. Commit on the designated `agent/<slug>` branch
4. Push successfully to the remote

## What a Canary Measures

- Can the coder model follow constrained instructions?
- Can it produce a clean commit from minimal context?
- Does it avoid scope creep beyond the requested change?

## Pass Criteria

- Branch pushed with at least one non-empty commit
- No files outside the allowed categories modified
- No test regressions introduced

## Fail Criteria

- Empty commit or no commit at all
- Modified protected files (package.json, .env, legal docs)
- Introduced new dependencies or changed existing ones
- Scope creep beyond a single small change
