/**
 * The Fleet Admin Control Plane loop — pure, port-injected orchestration. Lives in
 * the kernel (zero deps) so it is portable + unit-testable; the Orchestrator wires
 * the ports to Supabase + fetch. This is the Orchestrator's new "admin-ops" workload
 * class, distinct from the code-build runner.
 *
 * Invariants:
 *   - The plane NEVER touches an app's production DB directly. It governs, then
 *     either auto-executes by DELEGATING to the app's own execute port, or mints an
 *     approval card and mirrors it to Bear's Smarter inbox.
 *   - Every routed action leaves a signed, hash-chained receipt.
 *   - Fail-safe: a failed delegate-execute marks the action errored, never "done".
 */
import type { Receipt } from '../governance/receipts.ts';
import { fleetAdminConstitution } from './constitution.ts';
import { DEFAULT_DOMAIN_POLICIES } from './autonomy.ts';
import { governFleetAction, type FleetVerdict } from './govern.ts';
import { buildApprovalCard, type ApprovalDecision, type FleetApprovalCard } from './bridge.ts';
import { precedentAdvice, type ResolvedCase } from './precedent.ts';
import type { AdminAction, AdminEvent } from './types.ts';

export interface PlanePorts {
  saveEvent(event: AdminEvent): Promise<void>;
  saveAction(action: AdminAction, verdict: FleetVerdict): Promise<void>;
  saveReceipt(receipt: Receipt): Promise<void>;
  prevReceipt(chain: string): Promise<Receipt | null>;
  saveApproval(card: FleetApprovalCard): Promise<void>;
  markApprovalMirrored(actionId: string): Promise<void>;
  getApproval(actionId: string): Promise<FleetApprovalCard | null>;
  getAction(actionId: string): Promise<AdminAction | null>;
  updateApprovalStatus(actionId: string, status: FleetApprovalCard['status'], approver: string, note?: string): Promise<void>;
  markExecuted(actionId: string, ref: string, undoToken?: string, error?: string): Promise<void>;
  isApprover(email: string): Promise<boolean>;
  recordLedger(domain: AdminAction['domain'], actionType: string, decision: ApprovalDecision['decision']): Promise<void>;
  pushToSmarter(card: FleetApprovalCard): Promise<boolean>;
  delegateExecute(action: AdminAction): Promise<{ ok: boolean; ref?: string; undoToken?: string; error?: string }>;
  /** optional: resolved historical cases for case-based autonomy (precedent) */
  recentCases?(action: AdminAction): Promise<ResolvedCase[]>;
}

export interface PlaneConfig {
  callbackUrl: string;
  /** shadow mode: govern + record what the plane WOULD do, but never execute + never mirror.
   *  The safe way to onboard a new app — observe agreement before granting any autonomy. */
  shadowMode?: boolean;
}

export function planeChainFor(a: AdminAction): string {
  return `${a.product}:${a.domain}:${a.subjectId ?? 'global'}`;
}

/** Govern one proposed action and route it: auto-execute, deny, or raise+mirror an approval. */
export async function governAndRoute(ports: PlanePorts, cfg: PlaneConfig, action: AdminAction): Promise<FleetVerdict> {
  const chain = planeChainFor(action);
  const prev = await ports.prevReceipt(chain);
  // Case-based autonomy: fetch similar resolved cases and let precedent clamp the dial.
  const cases = ports.recentCases ? await ports.recentCases(action) : [];
  const precedent = cases.length ? precedentAdvice(action, cases) : undefined;
  const verdict = governFleetAction({
    action,
    constitution: fleetAdminConstitution(),
    policies: DEFAULT_DOMAIN_POLICIES,
    precedent,
    prevReceipt: prev,
    chain,
  });

  await ports.saveAction(action, verdict);
  await ports.saveReceipt(verdict.receipt);

  if (verdict.decision === 'deny') return verdict;

  // Shadow mode: never touch a real system + never bug a human. The saved action row already
  // records what the plane WOULD have decided (decision/tier) for the agreement analysis.
  if (cfg.shadowMode) return verdict;

  if (verdict.decision === 'allow') {
    const res = await ports.delegateExecute(action);
    await ports.markExecuted(action.id, res.ref ?? '', res.undoToken, res.ok ? undefined : res.error ?? 'execute_failed');
    return verdict;
  }

  const card = buildApprovalCard({ action, verdict, callbackUrl: cfg.callbackUrl });
  await ports.saveApproval(card);
  const delivered = await ports.pushToSmarter(card);
  if (delivered) await ports.markApprovalMirrored(action.id);
  return verdict;
}

/** Ingest an event + its proposed remediations (from the app's swarm/adapter). */
export async function ingestEvent(
  ports: PlanePorts,
  cfg: PlaneConfig,
  event: AdminEvent,
  proposedActions: AdminAction[],
): Promise<{ event: AdminEvent; verdicts: FleetVerdict[] }> {
  await ports.saveEvent(event);
  const verdicts: FleetVerdict[] = [];
  for (const action of proposedActions) verdicts.push(await governAndRoute(ports, cfg, action));
  return { event, verdicts };
}

/** Handle a decision posted back from Smarter. Verifies approver, executes, learns. */
export async function handleDecision(
  ports: PlanePorts,
  decision: ApprovalDecision,
): Promise<{ ok: boolean; executed: boolean; reason: string }> {
  if (!(await ports.isApprover(decision.approver))) return { ok: false, executed: false, reason: 'approver_not_allowlisted' };
  const card = await ports.getApproval(decision.actionId);
  const action = await ports.getAction(decision.actionId);
  if (!card || !action) return { ok: false, executed: false, reason: 'approval_or_action_not_found' };
  if (card.status !== 'pending') return { ok: false, executed: false, reason: `already_${card.status}` };

  const status = decision.decision === 'approve' ? 'approved' : decision.decision === 'modify' ? 'modified' : 'rejected';
  await ports.updateApprovalStatus(decision.actionId, status, decision.approver, decision.note);
  await ports.recordLedger(action.domain, action.type, decision.decision);

  if (decision.decision === 'reject') return { ok: true, executed: false, reason: 'rejected_no_action' };

  const effective: AdminAction =
    decision.decision === 'modify' && decision.modifiedParams
      ? { ...action, params: { ...action.params, ...decision.modifiedParams } }
      : action;

  const res = await ports.delegateExecute(effective);
  await ports.markExecuted(action.id, res.ref ?? '', res.undoToken, res.ok ? undefined : res.error ?? 'execute_failed');
  return { ok: res.ok, executed: res.ok, reason: res.ok ? 'executed' : res.error ?? 'execute_failed' };
}
