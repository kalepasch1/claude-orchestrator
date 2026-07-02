// POST /api/fleet/nl-compile  { text }
// Natural-language control plane: compile an English policy line into an enforceable rule
// and dry-run it against recent actions so Bear sees the diff BEFORE it applies. Returns
// the compiled rules + the twin diff; applying it (persisting the new constitution) is a
// separate, human-confirmed step.
import { compileNlControl, type AdminAction } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const { text } = (await readBody(event)) as { text?: string };
  if (!text) throw createError({ statusCode: 400, message: 'text required' });

  const sb = serviceClient();
  const { data } = await sb
    .from('fleet_admin_actions')
    .select('id,product,domain,type,actor,subject_id,amount_usd,confidence,reversibility,blast_radius,intent,created_at')
    .order('created_at', { ascending: false })
    .limit(1000);
  const history: AdminAction[] = (data ?? []).map((r: any) => ({
    id: r.id, product: r.product, domain: r.domain, type: r.type, actor: r.actor,
    subjectId: r.subject_id ?? undefined, amountUsd: r.amount_usd ?? undefined, confidence: Number(r.confidence),
    reversibility: r.reversibility, blastRadius: r.blast_radius, intent: r.intent, at: r.created_at,
  }));

  const result = compileNlControl({ text, history });
  return {
    normalizedLines: result.normalizedLines,
    addedRuleCount: result.addedRuleCount,
    addedRules: result.constitution.rules.slice(-result.addedRuleCount).map((r) => ({ id: r.id, text: r.text, effect: r.effect, appliesTo: r.appliesTo })),
    unmapped: result.unmapped,
    rejected: result.rejected,
    dryRun: result.dryRun,
  };
});
