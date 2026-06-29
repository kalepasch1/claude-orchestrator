/**
 * Hisanta wiring — kids character-building platform.
 *
 * Adoption: the parent-approval gate becomes a constitution with child-facing AI
 * delivery in `alwaysEscalate` (already its posture). Emit a `guardian_verified`
 * claim that routes the parent to Pareto household/college planning, and model
 * guardian→child edges in the identity graph for the generational account fabric.
 */
import type { Constitution } from '../governance/constitution.ts';
import { rule } from '../governance/constitution.ts';
import { defineCapability, type CapabilitySpec } from '../orchestratorClient/capabilityRegistry.ts';
import { claim, type Claim } from '../passport/passport.ts';

export const HISANTA_LOCKED_DIMENSIONS = [
  'no_real_money_to_child',
  'ai_is_guide_not_companion', // no open chat, no sentience, safety-filter-before-display
  'parent_gates_all_child_content',
  'aggregated_anonymized_demand_only', // cohort >= k
] as const;

export function hisantaConstitution(version = 1): Constitution {
  return {
    product: 'hisanta',
    version,
    // anything the child sees from the AI, or any commerce, escalates to the parent
    alwaysEscalate: ['deliver_ai_message', 'open_loot_box', 'gift_purchase'],
    rules: [
      rule.denyActionType('no-child-realmoney', 'charge_child'),
      rule.denyActionType('no-open-chat', 'open_ended_child_chat'),
      rule.allowUnder('log-spark', 'log_spark', Number.MAX_SAFE_INTEGER, 30),
    ],
  };
}

export function hisantaCapabilities(baseUrl = ''): CapabilitySpec[] {
  return [
    defineCapability({
      name: 'character_ledger',
      owner: 'hisanta',
      version: '1.0.0',
      description: 'Per-child, per-trait ledger of logged virtues over time (the moat dataset)',
      input: { childId: 'string' },
      output: { traits: 'object', totalSparks: 'number' },
      tags: ['kids', 'character', 'ledger'],
      endpoint: `${baseUrl}/api/child/ledger`,
    }),
    defineCapability({
      name: 'adaptive_difficulty',
      owner: 'hisanta',
      version: '1.0.0',
      description: 'Per-child rolling-average level engine (0..3) — portable to any learning game',
      input: { childId: 'string', recentScores: 'array' },
      output: { level: 'number' },
      tags: ['kids', 'adaptive', 'gameplay'],
      endpoint: `${baseUrl}/api/child/level`,
    }),
  ];
}

/** Verified parent → routes to Pareto household/college planning + anchors the child node. */
export function hisantaGuardianClaim(ttlDays = 365): Claim {
  return claim('guardian_verified', 'hisanta', 1, ttlDays);
}
