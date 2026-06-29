PROJECT: apparently

- id: apparently-typecheck-green
  title: Restore TypeScript typecheck to 0 errors, then merge to master
  material: yes
  model: opus
  depends: []
  proof: "NODE_OPTIONS=--max-old-space-size=8192 npx nuxt typecheck 2>&1 | grep -cE 'error TS' == 0; the 9 source-of-truth engine tests pass; @ts-nocheck count == 0"
  prompt: |
    Branch: fix/master-typecheck-green (off master). Drive `npx nuxt typecheck` to ZERO errors.
    NOTE: the orchestrator runs a single headless agent — do NOT rely on the interactive Workflow
    multi-agent tool or /private/tmp scratchpad from the interactive session. Work in batches:
    regenerate the error list yourself (NODE_OPTIONS=--max-old-space-size=8192 npx nuxt typecheck
    2>&1 | grep "error TS"), fix the highest-count files first, commit per batch.

    Dominant error codes + fixes: TS2769 (no overload — verify columns against
    types/database.types.ts; fix call signature), TS18048/TS2532 (possibly undefined — use `x!` or
    `x ?? fallback`), TS2322 (type not assignable), TS2339 (stale property name), TS2345 (arg type),
    TS2554 (arg count), TS7006 (implicit any — annotate).

    INVARIANTS (never violate):
    - NEVER add @ts-nocheck (a ratchet test enforces 0); use @ts-expect-error only as last resort
      WITH an explanatory comment.
    - Do NOT change logic in source-of-truth engines (server/engines/trust/, /ledger/, /benchmark/,
      determination-provenance.ts) — type annotations only.
    - No fabricated data: verify Supabase column names via information_schema before changing; never
      invent columns.
    - Before vitest: rm -f _sla*.mjs _sla-check-run-tmp.mjs
    - Keep the 9 source-of-truth engine tests green (attestation-crypto, canonical-ledger,
      ledger-feedback, ledger-as-of, determination-provenance, ledger-changelog, network-benchmarks,
      attestation-subscriptions, subject-attestation) and the full suite (8200+).
    Update IMPLEMENTATION_LOG.md with the final error count (0). MATERIAL: merge to master is gated —
    do NOT merge autonomously; produce the green branch and wait for human approval.

OPERATOR:
  - This duplicates the running interactive "Restore typecheck green" session — pick ONE owner before unpausing apparently in the orchestrator, or the two will conflict on the same files.
