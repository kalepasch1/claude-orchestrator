# Archive

Fleet-generated documentation moved out of the repo root for legibility.
Nothing deleted — every file is here and in git history.

- `root-docs/` — status/remediation/security notes auto-emitted during fleet runs
- `duplicate-adrs/` — repeat ADRs for decisions that already had one. Root cause fixed
  2026-07-30 in `runner/cx_auto_adr.py`: idempotency keyed on date+slug instead of slug alone,
  so every still-recent decision re-emitted a new ADR daily (49 files for 17 decisions).
