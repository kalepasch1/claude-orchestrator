/**
 * developmentTerminalProof.ts — Madeus' projection layer.
 *
 * Bridges the shared development-session client to the VerificationChecklist
 * component. Its whole reason to exist is the invariant in the SDK: a step with
 * no evidence renders as `pending`, never as `pass`. The previous inline
 * implementation hardcoded five of seven steps to `pass`, so a task that had
 * merely reached a terminal state displayed a fully green proof.
 */
import {
  applyEvents,
  emptySessionState,
  projectVerificationSteps,
  proofSummary,
  type ProofStatus,
  type SessionEvent,
} from '../server/utils/developmentSessionClient';

export type ChecklistStatus = 'pass' | 'fail' | 'running' | 'pending' | 'skip';

export interface ChecklistStepView {
  key: string;
  label: string;
  status: ChecklistStatus;
}

/** A completion row as the orchestrator snapshot exposes it. Every evidence
 *  field is optional — that is the point. */
export interface CompletionRecord {
  slug?: string;
  state?: string;
  commit?: string | null;
  branch?: string | null;
  test_command?: string | null;
  tests_passed?: boolean | null;
  test_artifact_url?: string | null;
  integration_proof_url?: string | null;
  release_sha?: string | null;
  release_url?: string | null;
  production_url?: string | null;
  verified_at?: string | null;
}

/** `unknown` is surfaced to the UI as `pending`, which renders neutral. It is
 *  deliberately not mapped to `skip` — the step was not skipped, we simply do
 *  not know. */
export function toChecklistStatus(status: ProofStatus): ChecklistStatus {
  if (status === 'pass') return 'pass';
  if (status === 'fail') return 'fail';
  return 'pending';
}

/** Turn a completion record into the events the shared reducer understands, so
 *  the terminal and any other UI project identical proof from identical data. */
export function completionToEvents(rec: CompletionRecord): SessionEvent[] {
  const events: SessionEvent[] = [];
  let cursor = 0;
  const r = rec || {};
  if (r.commit || r.branch) {
    events.push({
      cursor: ++cursor, type: 'worktree',
      commit: r.commit ?? undefined, branch: r.branch ?? undefined,
    });
  }
  if (r.test_command || r.tests_passed !== undefined || r.test_artifact_url) {
    events.push({
      cursor: ++cursor, type: 'tests',
      command: r.test_command ?? undefined,
      passed: r.tests_passed === null ? undefined : r.tests_passed,
      artifactUrl: r.test_artifact_url ?? undefined,
    });
  }
  // A state of MERGED is evidence of a merge, and of nothing else.
  if (r.integration_proof_url || r.state) {
    events.push({
      cursor: ++cursor, type: 'integration',
      proofUrl: r.integration_proof_url ?? undefined,
      merged: r.state ? r.state === 'MERGED' : undefined,
    });
  }
  if (r.release_sha || r.release_url) {
    events.push({
      cursor: ++cursor, type: 'release',
      sha: r.release_sha ?? undefined, url: r.release_url ?? undefined,
    });
  }
  if (r.production_url || r.verified_at) {
    events.push({
      cursor: ++cursor, type: 'journey',
      productionUrl: r.production_url ?? undefined, verifiedAt: r.verified_at ?? undefined,
    });
  }
  return events;
}

export function projectCompletionSteps(rec: CompletionRecord): ChecklistStepView[] {
  const state = applyEvents(emptySessionState(String(rec?.slug ?? 'unknown')), completionToEvents(rec));
  return projectVerificationSteps(state).map((s) => ({
    key: s.key, label: s.label, status: toChecklistStatus(s.status),
  }));
}

/** Headline for the panel: never claims more than the evidence supports. */
export function completionProofSummary(rec: CompletionRecord) {
  const state = applyEvents(emptySessionState(String(rec?.slug ?? 'unknown')), completionToEvents(rec));
  return proofSummary(projectVerificationSteps(state));
}
