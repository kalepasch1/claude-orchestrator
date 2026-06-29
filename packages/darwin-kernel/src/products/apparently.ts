/**
 * Apparently wiring — legal-opinions / licensing / regulator-intel / disclosure.
 *
 * Adoption: wrap the disclosure/opinion bots in `governAction`; publish
 * regulator-intel + legal-opinion + licensing as capabilities that Tomorrow,
 * Galop and Smarter consume as their shared legal/regulatory backbone.
 */
import type { Constitution } from '../governance/constitution.ts';
import { rule } from '../governance/constitution.ts';
import { defineCapability, type CapabilitySpec } from '../orchestratorClient/capabilityRegistry.ts';

export const APPARENTLY_LOCKED_DIMENSIONS = [
  'opinion_requires_grounding_citation', // every assertion cites a source or is not asserted
  'materiality_gate_before_publish',
  'rls_default_deny',
] as const;

export function apparentlyConstitution(version = 1): Constitution {
  return {
    product: 'apparently',
    version,
    alwaysEscalate: ['publish_legal_opinion', 'file_regulatory_submission'],
    rules: [
      rule.denyActionType('no-ungrounded-opinion', 'assert_without_citation'),
      rule.allowUnder('draft-opinion', 'draft_opinion', Number.MAX_SAFE_INTEGER, 30),
      rule.allowUnder('scan-regulator', 'scan_regulator_intel', Number.MAX_SAFE_INTEGER, 20),
    ],
  };
}

export function apparentlyCapabilities(baseUrl = ''): CapabilitySpec[] {
  return [
    defineCapability({
      name: 'regulator_intel',
      owner: 'apparently',
      version: '1.0.0',
      description: 'Live regulator-intel digest by jurisdiction/topic (CFTC/SEC/state) with citations',
      input: { jurisdiction: 'string', topic: 'string' },
      output: { findings: 'array', citations: 'array' },
      tags: ['legal', 'regulatory', 'intel'],
      endpoint: `${baseUrl}/api/regulator-intel/query`,
    }),
    defineCapability({
      name: 'legal_opinion',
      owner: 'apparently',
      version: '1.0.0',
      description: 'Grounded legal-opinion draft (cited; materiality-gated before publish)',
      input: { question: 'string', context: 'object' },
      output: { opinion: 'string', citations: 'array', needsCounsel: 'boolean' },
      tags: ['legal', 'opinion'],
      endpoint: `${baseUrl}/api/legal-opinions/draft`,
    }),
    defineCapability({
      name: 'licensing_check',
      owner: 'apparently',
      version: '1.0.0',
      description: 'Licensing/disclosure requirement check for a product+jurisdiction',
      input: { productType: 'string', jurisdiction: 'string' },
      output: { required: 'array', status: 'string' },
      tags: ['legal', 'licensing', 'compliance'],
      endpoint: `${baseUrl}/api/licensing/check`,
    }),
  ];
}
