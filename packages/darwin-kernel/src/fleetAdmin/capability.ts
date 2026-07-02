/**
 * Publish the Fleet Admin plane ITSELF as a Darwin capability. Once published on the
 * capability registry, ANY orchestrator — not just this portfolio's 9 apps — instantiates
 * governed admin autonomy in one line: `registry.instantiate(fleetGovernCapId, {...})`. The
 * plane stops being our internal system and becomes a product other orgs' orchestrators
 * consume. Zero-dep; mirrors the per-product wiring in `products/*.ts`.
 */
import { defineCapability, type CapabilitySpec } from '../orchestratorClient/capabilityRegistry.ts';

export const FLEET_ADMIN_CAPABILITY_TAGS = ['admin', 'governance', 'autonomy', 'ops', 'fleet'];

/**
 * The capabilities the plane exposes. `baseUrl` is the Orchestrator deployment hosting the
 * `/api/fleet/*` endpoints. Consumers discover by tag and invoke by id.
 */
export function fleetAdminCapabilities(baseUrl = ''): CapabilitySpec[] {
  return [
    defineCapability({
      name: 'admin_govern_action',
      owner: 'orchestrator',
      version: '1.0.0',
      description:
        'Govern one admin action: constitution + four-domain autonomy dial + precedent + signed receipt. Returns allow(auto) / escalate(approval) / deny. The 5/95 gate as a service.',
      input: { product: 'string', domain: 'string', type: 'string', confidence: 'number', reversibility: 'string', blastRadius: 'string', amountUsd: 'number?' },
      output: { decision: 'string', tier: 'string', receiptDigest: 'string' },
      tags: FLEET_ADMIN_CAPABILITY_TAGS,
      endpoint: `${baseUrl}/api/fleet/ingest`,
    }),
    defineCapability({
      name: 'admin_govern_intent',
      owner: 'orchestrator',
      version: '1.0.0',
      description:
        'Govern a multi-step remediation as ONE decision, with the constitution bounding the whole plan (intent-level autonomy).',
      input: { goal: 'string', subjectId: 'string', product: 'string' },
      output: { decision: 'string', tier: 'string', steps: 'array' },
      tags: FLEET_ADMIN_CAPABILITY_TAGS,
      endpoint: `${baseUrl}/api/fleet/intent`,
    }),
    defineCapability({
      name: 'admin_approval_feed',
      owner: 'orchestrator',
      version: '1.0.0',
      description: 'Mirror escalated admin decisions into a human approval inbox (e.g. Smarter) and receive decisions back.',
      input: { card: 'object' },
      output: { delivered: 'boolean' },
      tags: FLEET_ADMIN_CAPABILITY_TAGS,
      endpoint: `${baseUrl}/api/fleet/callback`,
    }),
    defineCapability({
      name: 'admin_autonomy_attestation',
      owner: 'orchestrator',
      version: '1.0.0',
      description: 'Signed, offline-verifiable proof-of-autonomy (rate + regression record + red-team envelope).',
      input: {},
      output: { attestation: 'object', verification: 'object' },
      tags: [...FLEET_ADMIN_CAPABILITY_TAGS, 'compliance'],
      endpoint: `${baseUrl}/api/fleet/attestation`,
    }),
  ];
}

/** The primary capability id consumers instantiate to govern an admin action. */
export function fleetGovernCapabilityId(baseUrl = ''): string {
  return fleetAdminCapabilities(baseUrl)[0]!.id;
}
