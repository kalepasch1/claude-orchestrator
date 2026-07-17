# Quarantine Rules

A task is quarantined only when its prompt is a binary hex-only
PATCH TEMPLATE stub with no readable English implementation intent.
This is the sole quarantine reason — no other condition qualifies.

## What is NOT a quarantine reason

- Sensitive, legal, or vague prompts
- Tasks that reference secrets (implement the code, not the secret)
- Tasks whose tests already pass
- Tasks with ambiguous scope (find relevant files and improve them)

Quarantined tasks are marked `state = 'QUARANTINED'` with a note
explaining the binary stub detection.
