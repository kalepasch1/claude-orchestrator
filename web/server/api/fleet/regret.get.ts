// GET /api/fleet/regret — closes the loop on auto-runs. Derives implicit regret signals
// (a chargeback / error-spike / reopened event landing on a subject AFTER we auto-acted on it)
// and reports the per-type regret rate — the KPI that should trend to zero. These regrets also
// feed precedent + replay as implicit rejections so the same shape auto-runs less next time.
import { regretReport, regretToResolvedCases, type AutoRunRecord, type RegretSignal } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

const REGRET_CATEGORY: Record<string, RegretSignal['kind']> = {
  chargeback: 'reversed_charge', error_spike: 'rollback', system_error: 'rollback', abuse_report: 'complaint',
};

export default defineEventHandler(async () => {
  const sb = serviceClient();
  const [{ data: acts }, { data: evs }] = await Promise.all([
    sb.from('fleet_admin_actions').select('id,domain,type,amount_usd,reversibility,blast_radius,subject_id,created_at').eq('tier', 'auto').eq('executed', true).limit(5000),
    sb.from('fleet_admin_events').select('category,subject_id,at').not('subject_id', 'is', null).limit(5000),
  ]);
  const autos: AutoRunRecord[] = (acts ?? []).map((r: any) => ({ id: r.id, domain: r.domain, type: r.type, amountUsd: r.amount_usd ?? undefined, reversibility: r.reversibility, blastRadius: r.blast_radius, at: r.created_at }));

  // A regret is a regret-category event on the same subject AFTER the auto action ran.
  const signals: RegretSignal[] = [];
  const bySubject = new Map<string, any[]>();
  for (const e of evs ?? []) if (REGRET_CATEGORY[e.category]) (bySubject.get(e.subject_id) ?? bySubject.set(e.subject_id, []).get(e.subject_id)!).push(e);
  for (const a of (acts ?? [])) {
    const later = (bySubject.get(a.subject_id) ?? []).find((e: any) => Date.parse(e.at) > Date.parse(a.created_at));
    if (later) signals.push({ actionId: a.id, kind: REGRET_CATEGORY[later.category]!, at: later.at });
  }

  const report = regretReport(autos, signals);
  const regretCases = regretToResolvedCases(autos, signals);
  return { report, regretCasesForPrecedent: regretCases.length };
});
