/**
 * Supabase + HTTP wiring for the Fleet Admin Control Plane ports. Uses the SERVICE
 * ROLE key (the plane is trusted infra; RLS is enforced for the dashboard + bridge).
 */
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import type { Receipt } from '@darwin/kernel/governance';
import type {
  AdminAction,
  AdminEvent,
  ApprovalDecision,
  FleetApprovalCard,
  FleetVerdict,
} from '@darwin/kernel/fleetAdmin';
import type { PlanePorts } from './fleetPlane';

export function serviceClient(): SupabaseClient {
  return createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY!);
}

/** Per-product base URL for execute delegation + deep links (env: FLEET_URL_APPARENTLY, ...). */
export function appBaseUrl(product: string): string | null {
  return process.env[`FLEET_URL_${product.toUpperCase()}`] ?? null;
}

function actionFromRow(r: any): AdminAction {
  return {
    id: r.id, product: r.product, domain: r.domain, type: r.type, actor: r.actor,
    eventId: r.event_id ?? undefined, subjectId: r.subject_id ?? undefined,
    amountUsd: r.amount_usd ?? undefined, confidence: Number(r.confidence),
    reversibility: r.reversibility, blastRadius: r.blast_radius, intent: r.intent,
    params: r.params ?? {}, ifNotDone: r.if_not_done ?? undefined, at: r.created_at ?? r.at,
  };
}

function cardFromRow(r: any): FleetApprovalCard {
  return {
    id: r.id, actionId: r.action_id, product: r.product, domain: r.domain, tier: r.tier,
    priority: r.priority, title: r.title, why: r.why, value: r.value, risk: r.risk,
    alternatives: r.alternatives ?? [], intent: r.intent, ifNotDone: r.if_not_done ?? undefined,
    amountUsd: r.amount_usd ?? undefined, sourceUrl: r.source_url ?? undefined,
    receiptDigest: r.receipt_digest, callbackUrl: r.callback_url, status: r.status, createdAt: r.created_at,
  };
}

export function supabasePorts(sb: SupabaseClient): PlanePorts {
  return {
    async saveEvent(e: AdminEvent) {
      await sb.from('fleet_admin_events').upsert({
        id: e.id, product: e.product, domain: e.domain, category: e.category, raw_category: e.rawCategory,
        severity: e.severity, title: e.title, summary: e.summary, subject_id: e.subjectId,
        amount_usd: e.amountUsd, details: e.details ?? {}, source_url: e.sourceUrl, at: e.at,
      });
    },
    async saveAction(a: AdminAction, v: FleetVerdict) {
      await sb.from('fleet_admin_actions').upsert({
        id: a.id, event_id: a.eventId, product: a.product, domain: a.domain, type: a.type, actor: a.actor,
        subject_id: a.subjectId, amount_usd: a.amountUsd, confidence: a.confidence, reversibility: a.reversibility,
        blast_radius: a.blastRadius, intent: a.intent, params: a.params ?? {}, if_not_done: a.ifNotDone,
        decision: v.decision, tier: v.tier, receipt_digest: v.receipt.digest, created_at: a.at,
      });
    },
    async saveReceipt(r: Receipt) {
      await sb.from('fleet_receipts').upsert({
        id: r.id, chain: r.chain, seq: r.seq, prev_hash: r.prevHash, digest: r.digest,
        signature: r.signature, action_id: (r.action as any)?.metadata?.eventId ?? null,
        decision: r.decision, reason: r.reason, at: r.at,
      });
    },
    async prevReceipt(chain: string) {
      const { data } = await sb.from('fleet_receipts').select('*').eq('chain', chain).order('seq', { ascending: false }).limit(1).maybeSingle();
      if (!data) return null;
      return {
        id: data.id, chain: data.chain, seq: data.seq, prevHash: data.prev_hash, action: {} as any,
        decision: data.decision, ruleId: null, reason: data.reason, at: data.at, digest: data.digest, signature: data.signature,
      } as Receipt;
    },
    async saveApproval(c: FleetApprovalCard) {
      await sb.from('fleet_approvals').upsert({
        id: c.id, action_id: c.actionId, product: c.product, domain: c.domain, tier: c.tier, priority: c.priority,
        title: c.title, why: c.why, value: c.value, risk: c.risk, alternatives: c.alternatives, intent: c.intent,
        if_not_done: c.ifNotDone, amount_usd: c.amountUsd, source_url: c.sourceUrl, receipt_digest: c.receiptDigest,
        callback_url: c.callbackUrl, status: c.status, created_at: c.createdAt,
      });
    },
    async markApprovalMirrored(actionId: string) {
      await sb.from('fleet_approvals').update({ mirrored_to_smarter: true }).eq('action_id', actionId);
    },
    async getApproval(actionId: string) {
      const { data } = await sb.from('fleet_approvals').select('*').eq('action_id', actionId).maybeSingle();
      return data ? cardFromRow(data) : null;
    },
    async getAction(actionId: string) {
      const { data } = await sb.from('fleet_admin_actions').select('*').eq('id', actionId).maybeSingle();
      return data ? actionFromRow(data) : null;
    },
    async updateApprovalStatus(actionId, status, approver, note) {
      await sb.from('fleet_approvals').update({ status, approver, note, decided_at: new Date().toISOString() }).eq('action_id', actionId);
    },
    async markExecuted(actionId, ref, undoToken, error) {
      await sb.from('fleet_admin_actions').update({
        executed: !error, execution_ref: ref, undo_token: undoToken, error: error ?? null, executed_at: new Date().toISOString(),
      }).eq('id', actionId);
    },
    async isApprover(email: string) {
      const { data } = await sb.from('fleet_approvers').select('email').eq('email', email).maybeSingle();
      return !!data;
    },
    async recordLedger(domain, actionType, decision) {
      const { data } = await sb.from('fleet_autonomy_ledger').select('*').eq('domain', domain).eq('action_type', actionType).maybeSingle();
      const base = data ?? { domain, action_type: actionType, streak: 0, total: 0, clean_approvals: 0, edits: 0, rejections: 0 };
      base.total += 1;
      if (decision === 'approve') { base.streak += 1; base.clean_approvals += 1; }
      else { base.streak = 0; if (decision === 'modify') base.edits += 1; else base.rejections += 1; }
      base.updated_at = new Date().toISOString();
      await sb.from('fleet_autonomy_ledger').upsert(base);
    },
    async pushToSmarter(card: FleetApprovalCard) {
      const url = process.env.SMARTER_INBOX_URL; // e.g. https://smarter.app/api/fleet/inbox
      if (!url) return false;
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'content-type': 'application/json', 'x-fleet-secret': process.env.FLEET_SHARED_SECRET ?? '' },
          body: JSON.stringify({ card }),
        });
        return res.ok;
      } catch { return false; }
    },
    async recentCases(action: AdminAction) {
      // Human-resolved approvals become precedent (auto-runs have no human outcome).
      const { data } = await sb
        .from('fleet_approvals')
        .select('status, act:fleet_admin_actions(domain,type,amount_usd,reversibility,blast_radius,created_at)')
        .neq('status', 'pending')
        .eq('domain', action.domain)
        .order('decided_at', { ascending: false })
        .limit(500);
      const outcomeOf = (s: string) => (s === 'approved' ? 'approve' : s === 'modified' ? 'modify' : 'reject') as 'approve' | 'modify' | 'reject';
      return (data ?? [])
        .filter((r: any) => r.act)
        .map((r: any) => ({
          domain: r.act.domain, type: r.act.type, amountUsd: r.act.amount_usd ?? undefined,
          reversibility: r.act.reversibility, blastRadius: r.act.blast_radius,
          outcome: outcomeOf(r.status), at: r.act.created_at,
        }));
    },
    async delegateExecute(action: AdminAction) {
      const base = appBaseUrl(action.product);
      if (!base) return { ok: false, error: `no_execute_url_for_${action.product}` };
      try {
        const res = await fetch(`${base}/api/fleet/execute`, {
          method: 'POST',
          headers: { 'content-type': 'application/json', 'x-fleet-secret': process.env.FLEET_SHARED_SECRET ?? '' },
          body: JSON.stringify({ action }),
        });
        if (!res.ok) return { ok: false, error: `app_execute_${res.status}` };
        const j = await res.json();
        return { ok: !!j.ok, ref: j.ref, undoToken: j.undoToken, error: j.error };
      } catch (e) { return { ok: false, error: String(e) }; }
    },
  };
}

export type { ApprovalDecision };
