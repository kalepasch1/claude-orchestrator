/**
 * Shared read helpers that shape live Supabase rows into the kernel's amplifier inputs
 * (ResolvedCase / ApproverDecisionRecord / ExposureRecord / LedgerEntry). Service-role.
 */
import type { SupabaseClient } from '@supabase/supabase-js';
import type { ResolvedCase, ApproverDecisionRecord, ExposureRecord, LedgerEntry, AppTypeStat, ExecutionOutcome, AdminAction, SettledDecision, PendingDecision } from '@darwin/kernel/fleetAdmin';

const OUTCOME: Record<string, 'approve' | 'modify' | 'reject'> = { approved: 'approve', modified: 'modify', rejected: 'reject' };

/** Human-resolved approvals joined to their action = the decision log for replay/learning. */
export async function resolvedHistory(sb: SupabaseClient): Promise<ResolvedCase[]> {
  const { data } = await sb
    .from('fleet_approvals')
    .select('status, act:fleet_admin_actions(domain,type,amount_usd,reversibility,blast_radius,created_at)')
    .neq('status', 'pending')
    .limit(5000);
  return (data ?? [])
    .filter((r: any) => r.act && OUTCOME[r.status])
    .map((r: any) => ({
      domain: r.act.domain, type: r.act.type, amountUsd: r.act.amount_usd ?? undefined,
      reversibility: r.act.reversibility, blastRadius: r.act.blast_radius,
      outcome: OUTCOME[r.status]!, at: r.act.created_at,
    }));
}

export async function approverDecisions(sb: SupabaseClient): Promise<ApproverDecisionRecord[]> {
  const { data } = await sb
    .from('fleet_approvals')
    .select('status, decided_at, note, act:fleet_admin_actions(domain,type)')
    .neq('status', 'pending')
    .limit(5000);
  return (data ?? [])
    .filter((r: any) => r.act && OUTCOME[r.status])
    .map((r: any) => ({
      domain: r.act.domain, actionType: r.act.type, outcome: OUTCOME[r.status]!,
      at: r.decided_at ?? new Date().toISOString(),
    }));
}

/** Historical $ occurrences of an action-type across apps, to size the blast radius. */
export async function exposureFor(sb: SupabaseClient, domain: string, actionType: string): Promise<ExposureRecord[]> {
  const { data } = await sb
    .from('fleet_admin_actions')
    .select('product,amount_usd,created_at')
    .eq('domain', domain)
    .eq('type', actionType)
    .limit(5000);
  return (data ?? []).map((r: any) => ({ product: r.product, amountUsd: r.amount_usd ?? undefined, at: r.created_at }));
}

/** Per-(app, domain, type) clean-rate stats → federated precedent (privacy-walled). */
export async function appTypeStats(sb: SupabaseClient): Promise<AppTypeStat[]> {
  const { data } = await sb
    .from('fleet_approvals')
    .select('status, act:fleet_admin_actions(product,domain,type)')
    .neq('status', 'pending')
    .limit(5000);
  const map = new Map<string, AppTypeStat>();
  for (const r of (data ?? []) as any[]) {
    if (!r.act) continue;
    const k = `${r.act.product}::${r.act.domain}::${r.act.type}`;
    const s = map.get(k) ?? { product: r.act.product, domain: r.act.domain, actionType: r.act.type, total: 0, cleanApprovals: 0 };
    s.total += 1;
    if (r.status === 'approved') s.cleanApprovals += 1;
    map.set(k, s);
  }
  return [...map.values()];
}

/** Recent execute outcomes per app → adapter health. */
export async function executionOutcomes(sb: SupabaseClient): Promise<ExecutionOutcome[]> {
  const { data } = await sb
    .from('fleet_admin_actions')
    .select('product,executed,error,executed_at,created_at')
    .not('executed_at', 'is', null)
    .order('executed_at', { ascending: false })
    .limit(2000);
  return (data ?? []).map((r: any) => ({ product: r.product, ok: r.executed && !r.error, error: r.error ?? undefined, at: r.executed_at ?? r.created_at }));
}

/** Actions + their human outcome (by id) → rule-market backtests. */
export async function historyWithOutcomes(sb: SupabaseClient): Promise<{ actions: AdminAction[]; outcomes: Record<string, 'approve' | 'modify' | 'reject'> }> {
  const { data } = await sb
    .from('fleet_approvals')
    .select('status, act:fleet_admin_actions(id,product,domain,type,actor,subject_id,amount_usd,confidence,reversibility,blast_radius,intent,created_at)')
    .neq('status', 'pending')
    .limit(3000);
  const actions: AdminAction[] = [];
  const outcomes: Record<string, 'approve' | 'modify' | 'reject'> = {};
  for (const r of (data ?? []) as any[]) {
    if (!r.act || !OUTCOME[r.status]) continue;
    actions.push({
      id: r.act.id, product: r.act.product, domain: r.act.domain, type: r.act.type, actor: r.act.actor,
      subjectId: r.act.subject_id ?? undefined, amountUsd: r.act.amount_usd ?? undefined, confidence: Number(r.act.confidence),
      reversibility: r.act.reversibility, blastRadius: r.act.blast_radius, intent: r.act.intent, at: r.act.created_at,
    });
    outcomes[r.act.id] = OUTCOME[r.status]!;
  }
  return { actions, outcomes };
}

/** All routed actions (+ resolved outcome) → the treasury P&L. */
export async function settledDecisions(sb: SupabaseClient): Promise<SettledDecision[]> {
  const { data } = await sb
    .from('fleet_admin_actions')
    .select('domain,decision,tier,amount_usd, appr:fleet_approvals(status)')
    .not('decision', 'is', null)
    .limit(10000);
  return (data ?? []).map((r: any) => ({
    domain: r.domain, tier: r.tier ?? 'human', decision: r.decision, amountUsd: r.amount_usd ?? undefined,
    outcome: r.appr?.[0]?.status ? OUTCOME[r.appr[0].status] : undefined,
  }));
}

/** Pending approvals (+ subject) → dependency-aware bundling. */
export async function pendingDecisions(sb: SupabaseClient): Promise<PendingDecision[]> {
  const { data } = await sb
    .from('fleet_approvals')
    .select('action_id, domain, priority, act:fleet_admin_actions(type,subject_id)')
    .eq('status', 'pending')
    .limit(500);
  return (data ?? []).filter((r: any) => r.act).map((r: any) => ({
    actionId: r.action_id, subjectId: r.act.subject_id ?? undefined, domain: r.domain, type: r.act.type, priority: r.priority,
  }));
}

export async function ledgerEntries(sb: SupabaseClient): Promise<LedgerEntry[]> {
  const { data } = await sb.from('fleet_autonomy_ledger').select('*');
  return (data ?? []).map((r: any) => ({
    actionType: r.action_type, domain: r.domain, streak: r.streak, total: r.total,
    cleanApprovals: r.clean_approvals, edits: r.edits, rejections: r.rejections,
    promotedTier: r.promoted_tier ?? undefined, promotedAt: r.promoted_at ?? undefined, updatedAt: r.updated_at,
  }));
}
