PROJECT: tomorrow

- id: prune-webhook-type-fix-redo
  title: Re-do the prune-webhook-deliveries type fix correctly (narrow err before access)
  material: yes
  model: haiku
  depends: []
  proof: `npx vue-tsc --noEmit` produces 0 errors (no increase over .tsc-error-baseline)
  prompt: |
    File: server/api/cron/prune-webhook-deliveries.post.ts (payments/webhook path).

    A prior auto-proposal (coordination_tasks git_commit_proposal a26b8e6f) was rejected
    because it changed `catch (err: any)` -> `catch (err: unknown)` but the body still
    accessed `err?.message`, which is a compile error under tsconfig strict with
    .tsc-error-baseline=0. Redo it correctly:
      - Either keep the catch variable safely typed, OR narrow before use:
        `const e = err as { message?: string }` then use `e?.message`.
      - Only replace `usePrisma() as any` with the typed client if the `webhookDelivery`
        delegate is actually present in the generated Prisma client; if not, leave the
        `as any` to avoid build breakage.
    Goal: pure type-safety, ZERO new tsc errors, no runtime/behavior change. Verify
    `npx vue-tsc --noEmit` does not increase the error count vs the committed baseline.

- id: runner-backlog-health
  title: Add a runner-health surface for the self-improvement queue backlog
  material: no
  model: sonnet
  depends: []
  proof: `npx vitest run server/utils/coordination/__tests__/runner-health.test.ts` exits 0
  prompt: |
    The self-improvement runner has a large backlog (~1,420 queued code_improvement_request
    rows + ~459 queued cron_failure rows in coordination_tasks). Add observability + a drain
    policy WITHOUT deleting tasks:
      - Add a pure helper server/utils/coordination/runnerHealth.ts `summarizeQueue(rows)`
        returning counts by task_type+status and the oldest queued age per type.
      - Add GET /api/coordination/runner-health (CRON_SECRET- or requireAuth-gated) returning
        that summary for a dashboard tile.
      - Add a drain-priority helper ordering code_improvement_request processing by priority
        then oldest-first, capped per run (configurable env), so the queue drains
        deterministically instead of growing.
    Add server/utils/coordination/__tests__/runner-health.test.ts proving summarizeQueue
    aggregates correctly and drain ordering is priority-then-age. Pure/unit-testable; do not
    delete or mutate live rows in the test.

OPERATOR:
  - Decide the drain-policy knobs (per-run cap, max age before any auto-cancel) before enabling auto-cancel of stale code_improvement_request rows — no bulk delete without sign-off.
  - Confirm the Tomorrow self-improvement GitHub Action runner has its push/deploy secrets set; the growing backlog may indicate it isn't draining in prod.
