/**
 * Receipt-chain projection — folds a per-subject receipt chain into derived
 * state + stats, turning the receipt log into an event-sourcing spine with
 * DR replay capability.
 *
 * Does NOT modify `verifyChain` or its signature. This module adds a parallel
 * projection utility that consumes the same `Receipt[]` input.
 */
import type { Receipt } from './receipts.ts';
import { verifyChain } from './receipts.ts';

/** Per-subject projected state derived from replaying a receipt chain. */
export interface ProjectedState {
  /** The chain key (e.g. `product:subjectId`). */
  chain: string;
  /** Total receipts replayed. */
  totalReceipts: number;
  /** Count of receipts by decision (allow / deny / etc.). */
  decisionCounts: Record<string, number>;
  /** Count of receipts per ruleId (null key = no rule). */
  ruleCounts: Record<string, number>;
  /** ISO timestamp of the first receipt. */
  firstAt: string | null;
  /** ISO timestamp of the most recent receipt. */
  lastAt: string | null;
  /** Digest of the latest receipt (chain head). */
  headDigest: string | null;
  /** Sequence number of the latest receipt. */
  headSeq: number;
}

/** Result of projecting a receipt chain. */
export interface ProjectionResult {
  /** Whether the chain is intact (hash-chain + signatures valid). */
  ok: boolean;
  /** Index of the first broken receipt, or null if chain is intact. */
  brokenAt: number | null;
  /** Projected state (populated even if chain is broken, up to the break). */
  state: ProjectedState;
}

/**
 * Replay a receipt chain into projected state + integrity check.
 *
 * Combines `verifyChain` integrity verification with a fold that accumulates
 * per-subject statistics. If the chain is broken/reordered, `ok` is false and
 * `brokenAt` indicates the first bad receipt; state is projected up to that point.
 */
export function projectChain(receipts: Receipt[]): ProjectionResult {
  const verification = verifyChain(receipts);
  const replayEnd = verification.brokenAt !== null ? verification.brokenAt : receipts.length;

  const state: ProjectedState = {
    chain: receipts.length > 0 ? receipts[0]!.chain : '',
    totalReceipts: 0,
    decisionCounts: {},
    ruleCounts: {},
    firstAt: null,
    lastAt: null,
    headDigest: null,
    headSeq: -1,
  };

  for (let i = 0; i < replayEnd; i++) {
    const r = receipts[i]!;
    state.totalReceipts++;
    state.decisionCounts[r.decision] = (state.decisionCounts[r.decision] ?? 0) + 1;
    const ruleKey = r.ruleId ?? '__none__';
    state.ruleCounts[ruleKey] = (state.ruleCounts[ruleKey] ?? 0) + 1;
    if (state.firstAt === null) state.firstAt = r.at;
    state.lastAt = r.at;
    state.headDigest = r.digest;
    state.headSeq = r.seq;
  }

  return { ok: verification.ok, brokenAt: verification.brokenAt, state };
}
