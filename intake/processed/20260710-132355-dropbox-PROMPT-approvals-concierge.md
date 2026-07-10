# Approvals concierge — pending operator cards reach Macey with context, preconditions tracked

## Problem (from 2026-07-10 fleet brief)
8 approval cards sat pending for up to 2 days; the operator only saw them when a session
manually queried the approvals table. Several cards had unmet preconditions (e.g. "after
relfix-X merges") and should not have been nagging yet at all. One card (gh PAT) was
already satisfied by existing `gh` keyring auth and nobody noticed.

## Objective
Build `runner/approvals_concierge.py`, a recurring job that keeps the approvals queue
truthful and pushes what actually needs a human:
1. **Precondition tracking**: parse cards whose detail references a task slug
   ("when/after <slug> merges/lands"); while that task is not MERGED/DONE, mark the card
   `brief_status='deferred'` (or equivalent existing column) so digests can separate
   "actionable now" from "waiting on the fleet". Flip back automatically when the
   dependency merges.
2. **Self-verification before nagging**: for cards with a machine-checkable claim, check
   it and auto-annotate: gh auth present (`gh auth status`), env key present in
   runner/.env (presence only — never read or log values), gemini oauth creds file
   exists, file perms already hardened. If the check passes, auto-approve the card with
   decided_by='concierge:verified' and the evidence in decision_text.
3. **Digest push**: once daily (env-tunable hour), if any actionable cards remain, write
   a single markdown digest into the morning-brief pipeline (whatever daily-fleet-brief
   reads) listing actionable cards first, deferred cards second, each with a one-line
   "what to do". No emails or external sends — brief integration only.
4. **Expiry**: self-healing "self"-kind cards (low-memory pause etc.) older than 24h that
   reference a condition no longer true get auto-approved with a note.

## Constraints
- Never auto-approve `secret`-kind cards that require the operator to mint/rotate/enter
  a credential — verification may only confirm work already done.
- Presence checks must never print secret values anywhere (logs, decision_text, DB).
- Fail-soft; ORCH_-prefixed env tunables; unit tests for the precondition parser,
  each verifier, digest formatting, and the never-auto-approve rule.

## Acceptance
- Seeded queue with one precondition card (unmerged slug), one verifiable-done card
  (fake gh auth ok), and one credential card → after one run: first is deferred, second
  is approved with evidence, third is untouched and appears first in the digest.
