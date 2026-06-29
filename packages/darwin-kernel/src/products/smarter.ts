/**
 * Smarter wiring — AI legal/deal workspace + bot fleet.
 *
 * Adoption: replace the local policy evaluator with `evaluateConstitution`
 * (the pre-send/UPL gate becomes a constitution), publish obligation/negotiation/
 * time-estimate engines as capabilities, and emit a `reliability` passport claim
 * per counterparty that Tomorrow's credit index consumes.
 */
import type { Constitution } from '../governance/constitution.ts';
import { rule } from '../governance/constitution.ts';
import { defineCapability, type CapabilitySpec } from '../orchestratorClient/capabilityRegistry.ts';
import { claim, type Claim } from '../passport/passport.ts';

export const SMARTER_LOCKED_DIMENSIONS = [
  'no_upl', // never give legal advice as the system; counsel-in-the-loop
  'no_autosend_when_killswitch',
  'strict_workspace_no_body_storage', // in-house/firm tier
] as const;

export function smarterConstitution(version = 1): Constitution {
  return {
    product: 'smarter',
    version,
    alwaysEscalate: ['execute_signature', 'send_to_counterparty_final'],
    rules: [
      rule.denyActionType('no-upl-advice', 'render_legal_advice'),
      // drafting + internal routing allowed; outbound send gated by pre-send review
      rule.allowUnder('draft-reply', 'draft_reply', Number.MAX_SAFE_INTEGER, 30),
      rule.allowUnder('classify', 'classify_email', Number.MAX_SAFE_INTEGER, 20),
    ],
  };
}

export function smarterCapabilities(baseUrl = ''): CapabilitySpec[] {
  return [
    defineCapability({
      name: 'obligation_extraction',
      owner: 'smarter',
      version: '1.0.0',
      description: 'Extract promises/commitments from text + auto-reconcile fulfillment (grounded, cited)',
      input: { text: 'string', context: 'object' },
      output: { obligations: 'array' },
      tags: ['legal', 'nlp', 'extraction'],
      endpoint: `${baseUrl}/api/obligations/extract`,
    }),
    defineCapability({
      name: 'negotiation_position',
      owner: 'smarter',
      version: '1.0.0',
      description: 'Reconcile their-ask → our-counter → concession trajectory per clause',
      input: { thread: 'array', clauses: 'array' },
      output: { positions: 'array' },
      tags: ['legal', 'negotiation'],
      endpoint: `${baseUrl}/api/negotiation/positions`,
    }),
    defineCapability({
      name: 'time_estimate',
      owner: 'smarter',
      version: '1.0.0',
      description: 'Task description → minutes (drives billing + scheduling)',
      input: { taskDescription: 'string' },
      output: { minutes: 'number', billingCode: 'string' },
      tags: ['legal', 'billing'],
      endpoint: `${baseUrl}/api/billing/estimate`,
    }),
    defineCapability({
      name: 'contact_enrichment',
      owner: 'smarter',
      version: '1.0.0',
      description: 'Email address → inferred role/org/seniority + talking points',
      input: { email: 'string' },
      output: { role: 'string', org: 'string', seniority: 'string' },
      tags: ['crm', 'enrichment'],
      endpoint: `${baseUrl}/api/contacts/enrich`,
    }),
  ];
}

/** Per-counterparty reliability (0..1) from sender profiles → feeds Tomorrow credit index. */
export function smarterReliabilityClaim(reliability: number, ttlDays = 60): Claim {
  return claim('reliability', 'smarter', Math.max(0, Math.min(1, reliability)), ttlDays);
}
