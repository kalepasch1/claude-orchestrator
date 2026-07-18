# Canary Task Routing

Canary tasks validate that a given coder route (model + pipeline) can produce
merge-worthy output for a specific project. They are generated from historical
merged-task data, not from live feature requests.

## How canaries work

1. **Source**: `canary_generator.py` selects a recently merged task as a template.
2. **Constraint**: The canary must NOT duplicate the original feature — it makes
   a "tiny safe analogous improvement" (doc clarification, test hygiene, etc.).
3. **Routing**: `force_coder` is set to the model being evaluated (e.g.,
   `gemini-pro`, `xai`, `claude-sonnet-5`). The executor honours this field.
4. **Scoring**: Merge/no-merge outcome feeds back into `scoreboard.py` and the
   QPD (quality-per-dollar) leader tables used by `coder_router.py`.

## Acceptance criteria for canary output

- Must compile / pass existing tests (no regressions).
- Must not touch secrets, dependencies, billing, or legal copy.
- Must be a net-positive change (even if tiny) — not a no-op commit.

## Why canaries exist

They provide a low-risk, real-repo signal for model routing decisions without
risking production features on an unproven coder route.
