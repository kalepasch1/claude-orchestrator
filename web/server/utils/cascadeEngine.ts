/**
 * Cascade Engine — when an action completes in one app, trigger related actions in other apps.
 *
 * Example: New client signs up in Tomorrow → provision Smarter workspace, create Apparently
 * compliance profile, set up Galop operator account.
 *
 * Cascades are defined declaratively and executed through each app's fleet/execute endpoint.
 */

export interface CascadeRule {
  id: string
  name: string
  description: string
  sourceProduct: string
  sourceAction: string
  targetSteps: CascadeStep[]
  enabled: boolean
}

export interface CascadeStep {
  targetProduct: string
  action: {
    domain: string
    type: string
    params: Record<string, any> | ((sourceAction: any) => Record<string, any>)
  }
  condition?: (sourceAction: any) => boolean
  continueOnError?: boolean
}

export interface CascadeResult {
  ruleId: string
  ruleName: string
  steps: Array<{
    targetProduct: string
    actionType: string
    ok: boolean
    ref?: string
    error?: string
  }>
  allSucceeded: boolean
}

// ── Execute cascade ──────────────────────────────────────────────────────

export async function executeCascade(
  rule: CascadeRule,
  sourceAction: any,
  executeOnApp: (product: string, action: any) => Promise<{ ok: boolean; ref?: string; error?: string }>
): Promise<CascadeResult> {
  const results: CascadeResult['steps'] = []

  for (const step of rule.targetSteps) {
    // Check condition
    if (step.condition && !step.condition(sourceAction)) {
      continue
    }

    const params = typeof step.action.params === 'function'
      ? step.action.params(sourceAction)
      : { ...step.action.params }

    const action = {
      id: `cascade-${rule.id}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      product: step.targetProduct,
      domain: step.action.domain,
      type: step.action.type,
      actor: 'cascade-engine',
      subjectId: sourceAction.subjectId,
      params,
      intent: `cascade from ${rule.sourceProduct}:${rule.sourceAction}`,
      at: new Date().toISOString(),
    }

    const result = await executeOnApp(step.targetProduct, action)
    results.push({
      targetProduct: step.targetProduct,
      actionType: step.action.type,
      ok: result.ok,
      ref: result.ref,
      error: result.error,
    })

    if (!result.ok && !step.continueOnError) break
  }

  return {
    ruleId: rule.id,
    ruleName: rule.name,
    steps: results,
    allSucceeded: results.every(r => r.ok),
  }
}

// ── Find matching cascades ───────────────────────────────────────────────

export function findMatchingCascades(
  sourceProduct: string,
  sourceActionType: string,
): CascadeRule[] {
  return DEFAULT_CASCADES.filter(
    c => c.enabled && c.sourceProduct === sourceProduct && c.sourceAction === sourceActionType
  )
}

// ── Default cascade definitions ──────────────────────────────────────────

export const DEFAULT_CASCADES: CascadeRule[] = [
  {
    id: 'cascade-new-client',
    name: 'New client onboarding',
    description: 'When a new client signs up in Tomorrow, provision across all apps',
    sourceProduct: 'tomorrow',
    sourceAction: 'create_client',
    enabled: true,
    targetSteps: [
      {
        targetProduct: 'smarter',
        action: {
          domain: 'users_access',
          type: 'provision_workspace',
          params: (src: any) => ({
            workspaceName: src.params?.clientName,
            ownerEmail: src.params?.email,
            tier: 'standard',
          }),
        },
      },
      {
        targetProduct: 'apparently',
        action: {
          domain: 'users_access',
          type: 'create_compliance_profile',
          params: (src: any) => ({
            entityName: src.params?.clientName,
            email: src.params?.email,
            jurisdiction: src.params?.jurisdiction || 'US',
          }),
        },
        continueOnError: true,
      },
    ],
  },
  {
    id: 'cascade-suspend-cross-app',
    name: 'Cross-app user suspension',
    description: 'Suspending a user in one app suspends them across all apps',
    sourceProduct: '*',
    sourceAction: 'suspend_user',
    enabled: true,
    targetSteps: [
      {
        targetProduct: 'apparently',
        action: { domain: 'users_access', type: 'suspend_user', params: {} },
        continueOnError: true,
      },
      {
        targetProduct: 'tomorrow',
        action: { domain: 'users_access', type: 'suspend_user', params: {} },
        continueOnError: true,
      },
      {
        targetProduct: 'smarter',
        action: { domain: 'users_access', type: 'suspend_user', params: {} },
        continueOnError: true,
      },
      {
        targetProduct: 'galop',
        action: { domain: 'users_access', type: 'ban_player', params: {} },
        continueOnError: true,
      },
      {
        targetProduct: 'hisanta',
        action: { domain: 'users_access', type: 'ban_family', params: {} },
        continueOnError: true,
      },
      {
        targetProduct: 'pareto',
        action: { domain: 'users_access', type: 'suspend_user', params: {} },
        continueOnError: true,
      },
    ],
  },
  {
    id: 'cascade-critical-alert',
    name: 'Critical alert broadcast',
    description: 'Critical events in any app trigger a review in all related apps',
    sourceProduct: '*',
    sourceAction: 'critical_alert',
    enabled: true,
    targetSteps: [
      {
        targetProduct: 'orchestrator',
        action: {
          domain: 'infra',
          type: 'create_incident',
          params: (src: any) => ({
            source: src.product,
            title: src.intent || 'Critical alert cascade',
            severity: 'critical',
          }),
        },
      },
    ],
  },
  {
    id: 'cascade-feature-flag-sync',
    name: 'Feature flag sync',
    description: 'Global feature flags propagate to all apps',
    sourceProduct: 'orchestrator',
    sourceAction: 'toggle_global_feature',
    enabled: true,
    targetSteps: [
      { targetProduct: 'apparently', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
      { targetProduct: 'tomorrow', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
      { targetProduct: 'smarter', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
      { targetProduct: 'galop', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
      { targetProduct: 'hisanta', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
      { targetProduct: 'pareto', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
    ],
  },
]
