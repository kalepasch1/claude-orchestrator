import { sha256Canonical } from '../crypto/hash.ts';
import { defineCapability, type CapabilitySpec } from '../orchestratorClient/capabilityRegistry.ts';
import type {
  BrainPrimitive,
  BrainPrimitiveId,
  BrainProduct,
  BrainReceipt,
  BrainRecipe,
  BrainStage,
  BrainSurface,
  CadeDeploymentPattern,
} from './types.ts';

export const COMMON_BRAIN_PRIMITIVES: BrainPrimitive[] = [
  {
    id: 'canonical_spine',
    name: 'Canonical Spine',
    purpose: 'Collect facts once and reuse them across surfaces, verticals, and products.',
    appliesTo: ['all'],
    riskLevel: 'medium',
    requiresHumanGate: false,
  },
  {
    id: 'determination_twin',
    name: 'Determination + Digital Twin',
    purpose: 'Simulate requirements, risk, cost, timing, acceptance, and downstream consequences before acting.',
    appliesTo: ['regulated', 'technical', 'financial', 'legal'],
    riskLevel: 'high',
    requiresHumanGate: true,
  },
  {
    id: 'adaptive_intake',
    name: 'Adaptive Intake',
    purpose: 'Ask the minimum-information-gain questions and prefill from documents, memory, and prior artifacts.',
    appliesTo: ['all'],
    riskLevel: 'low',
    requiresHumanGate: false,
  },
  {
    id: 'zero_touch_autopilot',
    name: 'Zero-Touch Autopilot',
    purpose: 'Do the reversible work end to end, stopping at material or irreversible gates.',
    appliesTo: ['all'],
    riskLevel: 'high',
    requiresHumanGate: true,
  },
  {
    id: 'outcome_flywheel',
    name: 'Outcome Flywheel',
    purpose: 'Attribute every result back to the prompt, model, data, pattern, and guardrail that produced it.',
    appliesTo: ['all'],
    riskLevel: 'medium',
    requiresHumanGate: false,
  },
  {
    id: 'auto_remediation',
    name: 'Auto-Remediation',
    purpose: 'When facts, tests, law, markets, or user reactions change, identify impacted artifacts and propose fixes.',
    appliesTo: ['regulated', 'technical', 'legal'],
    riskLevel: 'high',
    requiresHumanGate: true,
  },
  {
    id: 'aligned_funding',
    name: 'Aligned-Counterparty Funding',
    purpose: 'Match commercially aligned funders without platform custody, principal flow, or undisclosed control.',
    appliesTo: ['financial', 'regulated'],
    riskLevel: 'high',
    requiresHumanGate: true,
  },
  {
    id: 'embedded_api_mcp',
    name: 'Embedded API / MCP',
    purpose: 'Expose the brain as a callable primitive for apps, agents, and external systems.',
    appliesTo: ['all'],
    riskLevel: 'medium',
    requiresHumanGate: false,
  },
  {
    id: 'confidence_guarantee',
    name: 'Confidence + Guarantee',
    purpose: 'Attach calibrated confidence, escalation thresholds, and optional guarantees only where outcome data supports them.',
    appliesTo: ['all'],
    riskLevel: 'high',
    requiresHumanGate: true,
  },
  {
    id: 'passport_identity',
    name: 'Passport / Identity',
    purpose: 'Reuse verified identity, profile, KYC, authority, and disclosure facts across products under consent.',
    appliesTo: ['all'],
    riskLevel: 'high',
    requiresHumanGate: true,
  },
  {
    id: 'disclosure_guardrail',
    name: 'Disclosure / Guardrail Engine',
    purpose: 'Structure and gate actions against policy, legal, privacy, privilege, money, and control constraints.',
    appliesTo: ['all'],
    riskLevel: 'high',
    requiresHumanGate: true,
  },
  {
    id: 'no_custody_payments',
    name: 'No-Custody Payments',
    purpose: 'Keep money movement off-platform via licensed PSP or direct-to-payee rails.',
    appliesTo: ['financial', 'regulated'],
    riskLevel: 'high',
    requiresHumanGate: true,
  },
  {
    id: 'cade_consensus',
    name: 'CADE Consensus',
    purpose: 'Decompose contestable units, seat a competence-matched panel, debate, red-team, and issue proof packs.',
    appliesTo: ['legal', 'financial', 'technical', 'negotiation', 'orchestration'],
    riskLevel: 'medium',
    requiresHumanGate: false,
  },
  {
    id: 'agent_market',
    name: 'Agent Market',
    purpose: 'Make model/vendor/role allocation competitive by settled outcome per dollar-minute.',
    appliesTo: ['all'],
    riskLevel: 'medium',
    requiresHumanGate: false,
  },
  {
    id: 'proof_pack',
    name: 'Proof Pack',
    purpose: 'Produce signed, replayable receipts: sources, deliberation, policy gates, model routes, and outcomes.',
    appliesTo: ['all'],
    riskLevel: 'low',
    requiresHumanGate: false,
  },
  {
    id: 'federated_learning',
    name: 'Federated Learning',
    purpose: 'Share distilled aggregate patterns with k-anonymity, DP, consent, and no raw customer data movement.',
    appliesTo: ['all'],
    riskLevel: 'high',
    requiresHumanGate: true,
  },
  {
    id: 'shared_artifact_ledger',
    name: 'Shared Artifact Ledger',
    purpose: 'Track reusable documents, diffs, templates, test receipts, citations, and evidence across surfaces.',
    appliesTo: ['all'],
    riskLevel: 'medium',
    requiresHumanGate: false,
  },
  {
    id: 'reuse_library',
    name: 'Reusable Intent Library',
    purpose: 'Start from proven patterns indexed by acceptance intent, symbols, tests, citations, and outcomes.',
    appliesTo: ['all'],
    riskLevel: 'low',
    requiresHumanGate: false,
  },
];

const PRODUCT_SETTLEMENT: Record<string, string> = {
  orchestrator: 'rollback-free deployed improvement per dollar-minute',
  beethoven: 'rollback-free deployed improvement per dollar-minute',
  tomorrow: 'compliant execution or safe no-trade value per dollar',
  apparently: 'verified regulatory artifact or accepted filing per dollar',
  smarter: 'accepted low-edit privilege-safe work product per dollar',
  pareto: 'risk-adjusted planning value per dollar',
  galop: 'verified sports/racing decision value per dollar',
  hisanta: 'approved joyful experience per minute of creator effort',
};

const DEFAULT_SETTLEMENT = 'rollback-free deployed improvement per dollar-minute';

export function normalizeBrainProduct(product: BrainProduct): BrainProduct {
  const p = String(product || '').toLowerCase();
  if (p === 'claude-orchestrator') return 'orchestrator';
  return p || 'orchestrator';
}

function settlementFor(product: BrainProduct): string {
  const p = normalizeBrainProduct(product);
  return PRODUCT_SETTLEMENT[String(p)] ?? DEFAULT_SETTLEMENT;
}

export function cadePatternFor(product: BrainProduct): CadeDeploymentPattern {
  const p = normalizeBrainProduct(product);
  if (p === 'tomorrow') {
    return {
      product: p,
      target: 'trade path, negotiation stance, and safe no-trade determinations',
      issueKinds: ['negotiation', 'financial', 'technical'],
      roster: ['liquidity scout', 'execution strategist', 'market maker', 'risk officer', 'compliance counsel'],
      adversary: 'toxic flow, adverse selection, settlement failure, regulatory breach',
      reviewer: 'compliance officer, market operator, and post-trade audit',
      settlement: settlementFor(p),
      proofLabel: 'execution optimality receipt',
    };
  }
  if (p === 'apparently') {
    return {
      product: p,
      target: 'regulatory fact, filing, legal opinion, and autonomy-tier determinations',
      issueKinds: ['legal', 'technical'],
      roster: ['primary-source verifier', 'jurisdiction specialist', 'regulatory historian', 'operator counsel'],
      adversary: 'opposing counsel, regulator deficiency reviewer, stale-law detector',
      reviewer: 'customer counsel, regulator, financial-institution reviewer',
      settlement: settlementFor(p),
      proofLabel: 'regulatory determination proof pack',
    };
  }
  if (p === 'smarter') {
    return {
      product: p,
      target: 'legal work product, principal-fit, privilege, citation, and obligation determinations',
      issueKinds: ['legal', 'technical'],
      roster: ['assigning principal model', 'citation verifier', 'privilege guard', 'opposing counsel', 'best associate'],
      adversary: 'toughest partner, opposing counsel, court clerk, privilege waiver critic',
      reviewer: 'assigning partner, counsel, client, and later audit',
      settlement: settlementFor(p),
      proofLabel: 'defensible-work receipt',
    };
  }
  return {
    product: p,
    target: 'task priority, implementation plan, merge/release, and model-routing determinations',
    issueKinds: ['technical', 'feature'],
    roster: ['repo maintainer', 'build verifier', 'release engineer', 'security reviewer', 'cost treasurer'],
    adversary: 'red build, stale branch, unsafe merge, rollback, wasted model spend',
    reviewer: 'merge train, Vercel deployment, owner priority, and production telemetry',
    settlement: settlementFor(p),
    proofLabel: 'deployed-diff proof pack',
  };
}

export function chooseBrainPrimitives(surface: BrainSurface): BrainPrimitive[] {
  const product = normalizeBrainProduct(surface.product);
  const selected = new Set<BrainPrimitiveId>([
    'canonical_spine',
    'adaptive_intake',
    'outcome_flywheel',
    'cade_consensus',
    'agent_market',
    'proof_pack',
    'shared_artifact_ledger',
    'reuse_library',
    'embedded_api_mcp',
  ]);

  if (surface.regulated || product === 'apparently' || product === 'smarter' || product === 'tomorrow') {
    selected.add('determination_twin');
    selected.add('auto_remediation');
    selected.add('disclosure_guardrail');
    selected.add('confidence_guarantee');
    selected.add('federated_learning');
  }
  if (surface.moneyMovement || product === 'tomorrow') {
    selected.add('no_custody_payments');
  }
  if (product === 'apparently') {
    selected.add('passport_identity');
    selected.add('aligned_funding');
  }
  if (product === 'smarter') {
    selected.add('passport_identity');
  }
  if ((surface.materiality ?? 0) >= 0.5) {
    selected.add('zero_touch_autopilot');
  }

  return COMMON_BRAIN_PRIMITIVES.filter((p) => selected.has(p.id));
}

export function buildBrainStages(primitives: BrainPrimitive[]): BrainStage[] {
  const present = new Set(primitives.map((p) => p.id));
  const has = (id: BrainPrimitiveId) => present.has(id);
  const pick = (...ids: BrainPrimitiveId[]): BrainPrimitiveId[] => ids.filter(has);
  return [
    {
      id: 'sense',
      name: 'Sense',
      primitives: pick('canonical_spine', 'adaptive_intake'),
      deliverable: 'minimal clean context and missing-information list',
      gate: 'auto',
    },
    {
      id: 'decompose',
      name: 'Decompose',
      primitives: pick('cade_consensus', 'determination_twin'),
      deliverable: 'contestable units and acceptance intent',
      gate: 'auto',
    },
    {
      id: 'retrieve',
      name: 'Retrieve',
      primitives: pick('reuse_library', 'shared_artifact_ledger', 'embedded_api_mcp'),
      deliverable: 'prior proven patterns and relevant artifacts',
      gate: 'auto',
    },
    {
      id: 'deliberate',
      name: 'Deliberate',
      primitives: pick('cade_consensus'),
      deliverable: 'consensus, dissent, red-team hits, and optimality bound',
      gate: 'confidence',
    },
    {
      id: 'route',
      name: 'Route',
      primitives: pick('agent_market', 'disclosure_guardrail'),
      deliverable: 'role-by-role model/vendor allocation with privacy constraints',
      gate: 'policy',
    },
    {
      id: 'act',
      name: 'Act',
      primitives: pick('zero_touch_autopilot', 'no_custody_payments', 'aligned_funding'),
      deliverable: 'reversible work completed and irreversible actions held',
      gate: has('zero_touch_autopilot') ? 'human' : 'policy',
    },
    {
      id: 'verify',
      name: 'Verify',
      primitives: pick('agent_market', 'confidence_guarantee', 'auto_remediation'),
      deliverable: 'independent verification and repair plan',
      gate: 'confidence',
    },
    {
      id: 'prove',
      name: 'Prove',
      primitives: pick('proof_pack', 'passport_identity'),
      deliverable: 'signed receipt, sources, policy gates, and replayable record',
      gate: 'auto',
    },
    {
      id: 'learn',
      name: 'Learn',
      primitives: pick('outcome_flywheel', 'federated_learning'),
      deliverable: 'privacy-safe outcome attribution',
      gate: 'policy',
    },
    {
      id: 'reuse',
      name: 'Reuse',
      primitives: pick('reuse_library', 'shared_artifact_ledger', 'embedded_api_mcp'),
      deliverable: 'published recipe/capability for other surfaces',
      gate: 'auto',
    },
  ];
}

export function buildBrainRecipe(surface: BrainSurface): BrainRecipe {
  const normalized: BrainSurface = { ...surface, product: normalizeBrainProduct(surface.product) };
  const primitives = chooseBrainPrimitives(normalized);
  const cade = cadePatternFor(normalized.product);
  const stages = buildBrainStages(primitives);
  const settlement = cade.settlement;
  const id = `brain_${String(normalized.product).replace(/[^a-z0-9]+/gi, '_')}_${normalized.surface.replace(/[^a-z0-9]+/gi, '_')}`.toLowerCase();
  const metrics = [
    `settled outcome: ${settlement}`,
    'tokens avoided by reuse',
    'minutes avoided by prebuild/cache',
    'review failures per accepted artifact',
    'rollback/escalation rate',
    'privacy/guardrail violations',
  ];
  const guardrails = [
    'route crown-jewel or privileged content only to local or approved no-training providers',
    'never auto-execute irreversible/material actions without human gate',
    'record dissent, red-team hits, and verifier receipts',
    'persist only distilled patterns unless explicit consent allows more',
  ];
  if (normalized.moneyMovement) {
    guardrails.push('never custody principal; route money via licensed PSP or direct-to-payee rails');
  }
  return {
    id,
    surface: normalized,
    northStar: normalized.objective,
    settlement,
    stages,
    primitives,
    cade,
    guardrails,
    metrics,
    deploymentPrompt: buildBrainDeploymentPrompt({ surface: normalized, stages, primitives, cade, settlement, guardrails, metrics }),
  };
}

export function buildBrainDeploymentPrompt(recipe: Pick<BrainRecipe, 'surface' | 'stages' | 'primitives' | 'cade' | 'settlement' | 'guardrails' | 'metrics'>): string {
  const primitiveLines = recipe.primitives.map((p) => `- ${p.id}: ${p.purpose}`).join('\n');
  const stageLines = recipe.stages.map((s) => `- ${s.name}: ${s.deliverable} [gate=${s.gate}]`).join('\n');
  return `Deploy the reusable Common Brain into ${recipe.surface.product}/${recipe.surface.surface}.

Objective: ${recipe.surface.objective}
Settlement function: ${recipe.settlement}

Use the shared primitives:
${primitiveLines}

CADE adaptation:
- target: ${recipe.cade.target}
- issue kinds: ${recipe.cade.issueKinds.join(', ')}
- roster: ${recipe.cade.roster.join(', ')}
- adversary: ${recipe.cade.adversary}
- reviewer: ${recipe.cade.reviewer}
- proof: ${recipe.cade.proofLabel}

Pipeline:
${stageLines}

Guardrails:
${recipe.guardrails.map((g) => `- ${g}`).join('\n')}

Metrics:
${recipe.metrics.map((m) => `- ${m}`).join('\n')}

Implement this by reusing existing app primitives first. Add a small adapter only where the app lacks one.
Every autonomous action must produce a proof/receipt and must feed the outcome flywheel.`;
}

export function buildBrainReceipt(recipe: BrainRecipe): BrainReceipt {
  const body = {
    recipeId: recipe.id,
    product: recipe.surface.product,
    surface: recipe.surface.surface,
    primitiveIds: recipe.primitives.map((p) => p.id),
    stageIds: recipe.stages.map((s) => s.id),
  };
  return { ...body, digest: sha256Canonical(body) };
}

export function commonBrainCapabilities(baseUrl = ''): CapabilitySpec[] {
  return [
    defineCapability({
      name: 'common_brain_recipe',
      owner: 'orchestrator',
      version: '1.0.0',
      description: 'Build a deployable Common Brain recipe for any app surface: primitives, CADE adaptation, guardrails, metrics, and proof pack.',
      input: { product: 'string', surface: 'string', domain: 'string', objective: 'string' },
      output: { recipe: 'object', deploymentPrompt: 'string', receiptDigest: 'string' },
      tags: ['brain', 'cade', 'agent-market', 'reuse', 'commonality'],
      endpoint: `${baseUrl}/api/fleet/common-brain/recipe`,
    }),
    defineCapability({
      name: 'common_brain_deploy',
      owner: 'orchestrator',
      version: '1.0.0',
      description: 'Queue an app-specific implementation of a Common Brain recipe with privacy, CADE, proof-pack, and outcome-flywheel requirements.',
      input: { recipe: 'object', targetProject: 'string' },
      output: { queued: 'boolean', taskSlug: 'string' },
      tags: ['brain', 'deployment', 'orchestrator'],
      endpoint: `${baseUrl}/api/fleet/common-brain/deploy`,
    }),
  ];
}
