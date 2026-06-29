/**
 * Supabase adapters — drop-in transports so any product in the portfolio wires
 * the kernel to the shared control-plane tables with ~3 lines. Works with the
 * `@supabase/supabase-js` client every app already has.
 *
 * Tables are created by `sql/0001_darwin_kernel.sql` (apply once to the shared
 * Supabase project, or per-product project if you prefer isolation).
 *
 * Usage:
 *   import { createClient } from '@supabase/supabase-js';
 *   import { supabaseCapabilityTransport, supabaseTaskQueueTransport } from '@darwin/kernel/adapters/supabase';
 *   const sb = createClient(URL, SERVICE_KEY);
 *   const registry = new CapabilityRegistry(supabaseCapabilityTransport(sb));
 */
import type { CapabilitySpec, CapabilityTransport } from '../orchestratorClient/capabilityRegistry.ts';
import type {
  ApprovalCard,
  QueuedTask,
  TaskQueueTransport,
  TaskState,
} from '../orchestratorClient/taskQueue.ts';
import type { Receipt } from '../governance/receipts.ts';
import type { ProductId } from '../types.ts';

/** Minimal structural type for the supabase-js client (avoids a hard dependency). */
export interface SupabaseLike {
  from(table: string): any;
}

/** invoke() is left to the product (HTTP/queue). Discovery + storage via Supabase. */
export function supabaseCapabilityTransport(
  sb: SupabaseLike,
  invoke: (id: string, input: Record<string, unknown>) => Promise<unknown>,
  table = 'darwin_capabilities',
): CapabilityTransport {
  return {
    async publish(spec: CapabilitySpec) {
      await sb.from(table).upsert({ id: spec.id, owner: spec.owner, name: spec.name, version: spec.version, spec });
    },
    async search(query: string, tags?: string[]) {
      const { data } = await sb.from(table).select('spec');
      const q = query.toLowerCase();
      return ((data ?? []) as { spec: CapabilitySpec }[])
        .map((r) => r.spec)
        .filter(
          (s) =>
            s.name.toLowerCase().includes(q) ||
            s.description.toLowerCase().includes(q) ||
            (tags ?? []).some((t) => s.tags.includes(t)),
        );
    },
    async get(id: string) {
      const { data } = await sb.from(table).select('spec').eq('id', id).maybeSingle();
      return (data?.spec as CapabilitySpec) ?? null;
    },
    invoke,
  };
}

export function supabaseTaskQueueTransport(
  sb: SupabaseLike,
  tasksTable = 'darwin_tasks',
  approvalsTable = 'darwin_approvals',
): TaskQueueTransport {
  return {
    async enqueue(task: QueuedTask) {
      await sb.from(tasksTable).insert({
        id: task.id,
        product: task.product,
        goal: task.goal,
        input: task.input,
        state: task.state,
        depends_on: task.dependsOn,
        requires_approval: task.requiresApproval,
        created_at: task.createdAt,
      });
    },
    async get(id: string) {
      const { data } = await sb.from(tasksTable).select('*').eq('id', id).maybeSingle();
      if (!data) return null;
      return {
        id: data.id,
        product: data.product as ProductId,
        goal: data.goal,
        input: data.input,
        state: data.state as TaskState,
        dependsOn: data.depends_on ?? [],
        requiresApproval: data.requires_approval,
        createdAt: data.created_at,
      };
    },
    async setState(id: string, state: TaskState) {
      await sb.from(tasksTable).update({ state }).eq('id', id);
    },
    async upsertApproval(card: ApprovalCard) {
      await sb.from(approvalsTable).upsert({
        task_id: card.taskId,
        why: card.why,
        value: card.value,
        risk: card.risk,
        alternatives: card.alternatives,
        decision: card.decision,
      });
    },
    async pendingApprovals(product?: ProductId) {
      let q = sb.from(approvalsTable).select('*, darwin_tasks!inner(product)').eq('decision', 'pending');
      if (product) q = q.eq('darwin_tasks.product', product);
      const { data } = await q;
      return ((data ?? []) as any[]).map((r) => ({
        taskId: r.task_id,
        why: r.why,
        value: r.value,
        risk: r.risk,
        alternatives: r.alternatives ?? [],
        decision: r.decision,
      }));
    },
  };
}

import type { UsageRecord } from '../orchestratorClient/metering.ts';
import type { Attestation } from '../attestation/attestation.ts';
import type { RewardLedgerEntry } from '../dataCoop/dataCoop.ts';
import type { IdentityEdge } from '../identity/rollups.ts';

/** Persist a signed capability usage record (audit + invoice line). */
export async function persistUsageRecord(
  sb: SupabaseLike,
  rec: UsageRecord,
  table = 'darwin_usage_records',
): Promise<void> {
  await sb.from(table).insert({
    id: rec.id,
    capability_id: rec.capabilityId,
    caller: rec.caller,
    owner: rec.owner,
    latency_ms: rec.latencyMs,
    units: rec.units,
    amount_cents: rec.amountCents,
    at: rec.at,
    digest: rec.digest,
    signature: rec.signature,
  });
}

/** Persist a generic signed attestation. */
export async function persistAttestation(
  sb: SupabaseLike,
  att: Attestation,
  table = 'darwin_attestations',
): Promise<void> {
  await sb.from(table).insert({
    id: att.id,
    kind: att.kind,
    issuer: att.issuer,
    about: att.about,
    payload: att.payload,
    issued_at: att.issuedAt,
    expires_at: att.expiresAt,
    digest: att.digest,
    signature: att.signature,
  });
}

/** Append data-coop reward entries to the ledger. */
export async function persistRewards(
  sb: SupabaseLike,
  rewards: RewardLedgerEntry[],
  table = 'darwin_reward_ledger',
): Promise<void> {
  if (rewards.length === 0) return;
  await sb.from(table).insert(
    rewards.map((r) => ({ subject: r.subject, currency: r.currency, amount: r.amount, reason: r.reason })),
  );
}

/** Upsert an identity edge (household/entity graph). */
export async function persistIdentityEdge(
  sb: SupabaseLike,
  edge: IdentityEdge,
  table = 'darwin_identity_edges',
): Promise<void> {
  await sb.from(table).upsert(
    { from_subject: edge.from, to_subject: edge.to, kind: edge.kind },
    { onConflict: 'from_subject,to_subject,kind' },
  );
}

/** Append a signed governance receipt to the shared, append-only chain table. */
export async function persistReceipt(
  sb: SupabaseLike,
  receipt: Receipt,
  table = 'darwin_receipts',
): Promise<void> {
  await sb.from(table).insert({
    id: receipt.id,
    chain: receipt.chain,
    seq: receipt.seq,
    prev_hash: receipt.prevHash,
    product: receipt.action.product,
    action_type: receipt.action.type,
    actor: receipt.action.actor,
    subject_id: receipt.action.subjectId ?? null,
    decision: receipt.decision,
    rule_id: receipt.ruleId,
    reason: receipt.reason,
    at: receipt.at,
    digest: receipt.digest,
    signature: receipt.signature,
  });
}
