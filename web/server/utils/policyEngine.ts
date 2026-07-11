/**
 * Policy Engine — natural-language policy definitions that auto-resolve common admin actions.
 *
 * Policies are stored in the fleet_policies table and evaluated against incoming events.
 * When an event matches a policy's conditions, the policy's actions are auto-executed
 * (subject to domain autonomy ceilings from fleetAdmin).
 *
 * Self-improving: the approverProfile learning system feeds back into policy suggestions.
 */
import { serviceClient } from './fleetSupabase'

export interface Policy {
  id: string
  name: string
  description: string
  product: string | '*'           // which app this applies to, * = all
  domain: string                   // users_access | billing | trust_safety | infra
  trigger: PolicyTrigger
  conditions: PolicyCondition[]
  actions: PolicyAction[]
  enabled: boolean
  autoExecute: boolean             // if true, skip approval queue
  createdAt: string
  lastMatchedAt: string | null
  matchCount: number
  successCount: number
}

export interface PolicyTrigger {
  eventCategory: string            // e.g. 'redemption', 'submission', 'trade'
  severity?: 'info' | 'warn' | 'critical'
}

export interface PolicyCondition {
  field: string                    // dot-path into event details, e.g. 'details.amount', 'amountUsd'
  op: 'eq' | 'neq' | 'gt' | 'lt' | 'gte' | 'lte' | 'contains' | 'exists'
  value: any
}

export interface PolicyAction {
  type: string                     // e.g. 'approve_redemption', 'flag_submission'
  params: Record<string, any>
}

// ── Core evaluation ──────────────────────────────────────────────────────

export function evaluateConditions(conditions: PolicyCondition[], event: any): boolean {
  return conditions.every((c) => {
    const val = getNestedValue(event, c.field)
    switch (c.op) {
      case 'eq':       return val === c.value
      case 'neq':      return val !== c.value
      case 'gt':       return typeof val === 'number' && val > c.value
      case 'lt':       return typeof val === 'number' && val < c.value
      case 'gte':      return typeof val === 'number' && val >= c.value
      case 'lte':      return typeof val === 'number' && val <= c.value
      case 'contains': return typeof val === 'string' && val.includes(c.value)
      case 'exists':   return val !== undefined && val !== null
      default:         return false
    }
  })
}

function getNestedValue(obj: any, path: string): any {
  return path.split('.').reduce((o, k) => o?.[k], obj)
}

export async function findMatchingPolicies(event: any): Promise<Policy[]> {
  const sb = serviceClient()
  const { data } = await sb
    .from('fleet_policies')
    .select('*')
    .eq('enabled', true)
    .or(`product.eq.${event.product},product.eq.*`)
    .eq('domain', domainFromCategory(event.category))

  if (!data) return []

  return data.filter((p: any) => {
    const policy = p as Policy
    // Check trigger
    if (policy.trigger.eventCategory !== event.category) return false
    if (policy.trigger.severity && policy.trigger.severity !== event.severity) return false
    // Check conditions
    return evaluateConditions(policy.conditions, event)
  })
}

export async function recordPolicyMatch(policyId: string, success: boolean): Promise<void> {
  const sb = serviceClient()
  const now = new Date().toISOString()

  // Increment match count atomically
  await sb.rpc('increment_policy_match', { policy_id: policyId, was_success: success })
    .then(() => {})
    .catch(async () => {
      // Fallback: non-atomic update if RPC doesn't exist
      const { data } = await sb.from('fleet_policies').select('match_count, success_count').eq('id', policyId).single()
      if (data) {
        await sb.from('fleet_policies').update({
          match_count: (data.match_count || 0) + 1,
          success_count: (data.success_count || 0) + (success ? 1 : 0),
          last_matched_at: now,
        }).eq('id', policyId)
      }
    })
}

// ── Policy suggestion from approver patterns ─────────────────────────────

export interface PolicySuggestion {
  name: string
  description: string
  product: string
  domain: string
  trigger: PolicyTrigger
  conditions: PolicyCondition[]
  actions: PolicyAction[]
  confidence: number
  basedOn: number // number of historical decisions
}

export async function suggestPolicies(): Promise<PolicySuggestion[]> {
  const sb = serviceClient()

  // Look at the autonomy ledger for domains with high clean-approval streaks
  const { data: ledger } = await sb
    .from('fleet_autonomy_ledger')
    .select('*')
    .gte('streak', 5)           // 5+ consecutive clean approvals
    .gte('clean_approvals', 10) // minimum sample size
    .order('streak', { ascending: false })

  if (!ledger?.length) return []

  return ledger.map((entry: any) => ({
    name: `Auto-${entry.action_type} for ${entry.domain}`,
    description: `${entry.clean_approvals} consecutive clean approvals — promote to auto-execute`,
    product: '*',
    domain: entry.domain,
    trigger: { eventCategory: entry.action_type },
    conditions: [],
    actions: [{ type: entry.action_type, params: {} }],
    confidence: entry.clean_approvals / (entry.total || 1),
    basedOn: entry.total,
  }))
}

// ── Helpers ──────────────────────────────────────────────────────────────

function domainFromCategory(category: string): string {
  const map: Record<string, string> = {
    compliance: 'trust_safety', security: 'trust_safety', fraud: 'trust_safety',
    billing: 'billing', subscription: 'billing', refund: 'billing',
    user: 'users_access', access: 'users_access', auth: 'users_access',
    infra: 'infra', deploy: 'infra', monitoring: 'infra',
    redemption: 'billing', submission: 'trust_safety', trade: 'trust_safety',
  }
  return map[category] || 'infra'
}

// ── Default seed policies ────────────────────────────────────────────────

export const SEED_POLICIES: Omit<Policy, 'id' | 'createdAt' | 'lastMatchedAt' | 'matchCount' | 'successCount'>[] = [
  {
    name: 'Auto-approve small HiSanta redemptions',
    description: 'Redemptions under 100 sparks are auto-approved if child has clean history',
    product: 'hisanta',
    domain: 'billing',
    trigger: { eventCategory: 'redemption' },
    conditions: [
      { field: 'details.sparks', op: 'lte', value: 100 },
      { field: 'details.childFlagged', op: 'eq', value: false },
    ],
    actions: [{ type: 'approve_redemption', params: {} }],
    enabled: true,
    autoExecute: true,
  },
  {
    name: 'Auto-approve Apparently submissions under review threshold',
    description: 'Standard submissions with confidence > 0.9 skip manual review',
    product: 'apparently',
    domain: 'trust_safety',
    trigger: { eventCategory: 'submission' },
    conditions: [
      { field: 'details.confidence', op: 'gte', value: 0.9 },
      { field: 'details.jurisdiction', op: 'neq', value: 'restricted' },
    ],
    actions: [{ type: 'approve_submission', params: {} }],
    enabled: true,
    autoExecute: true,
  },
  {
    name: 'Flag high-value Galop bets',
    description: 'Bets over $500 from new players get flagged for review',
    product: 'galop',
    domain: 'trust_safety',
    trigger: { eventCategory: 'bet', severity: 'warn' },
    conditions: [
      { field: 'amountUsd', op: 'gt', value: 500 },
      { field: 'details.playerAge', op: 'lt', value: 30 }, // days since signup
    ],
    actions: [{ type: 'flag_bet', params: { reason: 'high-value bet from new player' } }],
    enabled: true,
    autoExecute: false,
  },
  {
    name: 'Auto-retry failed Tomorrow settlements',
    description: 'Settlement failures from transient errors get one automatic retry',
    product: 'tomorrow',
    domain: 'billing',
    trigger: { eventCategory: 'settlement', severity: 'warn' },
    conditions: [
      { field: 'details.errorType', op: 'eq', value: 'transient' },
      { field: 'details.retryCount', op: 'lt', value: 1 },
    ],
    actions: [{ type: 'retry_settlement', params: {} }],
    enabled: true,
    autoExecute: true,
  },
  {
    name: 'Never auto-execute Pareto money movements',
    description: 'All fund transfers in Pareto require human approval — no exceptions',
    product: 'pareto',
    domain: 'billing',
    trigger: { eventCategory: 'transfer' },
    conditions: [],
    actions: [],
    enabled: true,
    autoExecute: false,
  },
]
