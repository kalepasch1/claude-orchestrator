// GET /api/growth-oversight — Orchestrator oversight of the Growth OS.
// Ties marketing (momentum/budget/spend) to AI token usage per app, so marketing spend can steer
// token/improvement focus. Also returns governance accuracy + counterfactual value + campaigns.
import { createClient } from '@supabase/supabase-js'

export default defineEventHandler(async () => {
  const sb = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY!)
  const [st, gov, camp, cf] = await Promise.all([
    sb.from('growth_spend_tokens').select('*'),
    sb.from('growth_governance_analytics').select('*'),
    sb.from('growth_campaign').select('app,name,status,segment').order('created_at', { ascending: false }).limit(20),
    sb.from('resource_events').select('value,created_at').eq('kind', 'growth_counterfactual_value').order('created_at', { ascending: false }).limit(1),
  ])
  const rows = st.data ?? []
  // suggested token/improvement focus weight = share of total momentum (marketing steers the build).
  const totalMom = rows.reduce((s: number, r: any) => s + Number(r.momentum || 0), 0) || 1
  const spendTokens = rows.map((r: any) => ({
    ...r,
    focus_weight: Math.round((Number(r.momentum || 0) / totalMom) * 100),
    // ratio of AI token cost to marketing spend — flags apps burning tokens without marketing traction
    token_to_marketing: Number(r.marketing_spend) > 0 ? Number((Number(r.token_cost_30d) / Number(r.marketing_spend)).toFixed(2)) : null,
  })).sort((a: any, b: any) => b.focus_weight - a.focus_weight)
  return {
    spendTokens,
    governance: gov.data ?? [],
    campaigns: camp.data ?? [],
    counterfactualValue: cf.data?.[0]?.value ?? null,
  }
})
