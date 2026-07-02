/**
 * Executor runtime — production hardening for the side-effecting path. Before any domain
 * graduates to `auto`, the executor must be safe under retries and partial failure:
 *   - IDEMPOTENT on action.id (a retried delivery never double-charges / double-suspends).
 *   - Multi-step actions RUN with COMPENSATION: on a mid-plan failure, already-completed steps
 *     are rolled back in reverse (best-effort), so the world is never left half-changed.
 * Pure orchestration; the real side effects + the store are injected. Zero-dep.
 */
import type { ExecutionResult } from './adapter.ts';

/** Records the result of an executed action so a retry returns the SAME result. */
export interface IdempotencyStore {
  get(actionId: string): Promise<ExecutionResult | null>;
  set(actionId: string, result: ExecutionResult): Promise<void>;
}

export function memoryIdempotencyStore(): IdempotencyStore {
  const m = new Map<string, ExecutionResult>();
  return {
    async get(id) { return m.get(id) ?? null; },
    async set(id, r) { m.set(id, r); },
  };
}

/**
 * Execute a handler at-most-once per actionId. A second call with the same id returns the
 * stored result instead of re-running the side effect. A thrown handler is captured as a
 * failed result and NOT stored (so it can be retried).
 */
export async function executeIdempotent(
  actionId: string,
  handler: () => Promise<ExecutionResult>,
  store: IdempotencyStore,
): Promise<ExecutionResult & { deduped?: boolean }> {
  const prior = await store.get(actionId);
  if (prior) return { ...prior, deduped: true };
  let result: ExecutionResult;
  try {
    result = await handler();
  } catch (err) {
    return { ok: false, detail: 'handler_threw', error: String(err) };
  }
  if (result.ok) await store.set(actionId, result); // only successes are memoized
  return result;
}

/** One step of a compensable plan: `run` does it, `undo` reverses it (best-effort). */
export interface CompensableStep {
  name: string;
  run: () => Promise<ExecutionResult>;
  undo?: (result: ExecutionResult) => Promise<void>;
}

export interface SagaResult {
  ok: boolean;
  completed: string[];
  rolledBack: string[];
  failedStep?: string;
  error?: string;
}

/**
 * Run steps in order; on the first failure, compensate the completed steps in REVERSE. This is
 * the saga pattern — the safe way to run a multi-step remediation (intent) against real systems.
 */
export async function runCompensable(steps: CompensableStep[]): Promise<SagaResult> {
  const completed: { step: CompensableStep; result: ExecutionResult }[] = [];
  for (const step of steps) {
    let result: ExecutionResult;
    try {
      result = await step.run();
    } catch (err) {
      result = { ok: false, detail: 'step_threw', error: String(err) };
    }
    if (!result.ok) {
      const rolledBack: string[] = [];
      for (const done of [...completed].reverse()) {
        try { await done.step.undo?.(done.result); rolledBack.push(done.step.name); } catch { /* best-effort */ }
      }
      return { ok: false, completed: completed.map((c) => c.step.name), rolledBack, failedStep: step.name, error: result.error ?? 'step_failed' };
    }
    completed.push({ step, result });
  }
  return { ok: true, completed: completed.map((c) => c.step.name), rolledBack: [] };
}
