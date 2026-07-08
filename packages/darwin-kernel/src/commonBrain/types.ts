/**
 * Common Brain - reusable cross-product intelligence substrate.
 *
 * This module packages the common systems that keep recurring across the
 * portfolio: CADE, agent markets, capability registry, federated/privacy-safe
 * learning, proof packs, passports, outcome flywheels, and guardrails. Products
 * can deploy the same brain recipe into any surface instead of rebuilding a
 * bespoke "AI layer" each time.
 */

export type BrainProduct =
  | 'orchestrator'
  | 'beethoven'
  | 'tomorrow'
  | 'apparently'
  | 'smarter'
  | 'pareto'
  | 'galop'
  | 'hisanta'
  | string;

export type BrainPrimitiveId =
  | 'canonical_spine'
  | 'determination_twin'
  | 'adaptive_intake'
  | 'zero_touch_autopilot'
  | 'outcome_flywheel'
  | 'auto_remediation'
  | 'aligned_funding'
  | 'embedded_api_mcp'
  | 'confidence_guarantee'
  | 'passport_identity'
  | 'disclosure_guardrail'
  | 'no_custody_payments'
  | 'cade_consensus'
  | 'agent_market'
  | 'proof_pack'
  | 'federated_learning'
  | 'shared_artifact_ledger'
  | 'reuse_library';

export type BrainStageId =
  | 'sense'
  | 'decompose'
  | 'retrieve'
  | 'deliberate'
  | 'route'
  | 'act'
  | 'verify'
  | 'prove'
  | 'learn'
  | 'reuse';

export interface BrainPrimitive {
  id: BrainPrimitiveId;
  name: string;
  purpose: string;
  appliesTo: string[];
  riskLevel: 'low' | 'medium' | 'high';
  requiresHumanGate: boolean;
}

export interface BrainSurface {
  product: BrainProduct;
  surface: string;
  domain: string;
  objective: string;
  regulated?: boolean;
  materiality?: number;
  sensitivity?: 'public' | 'standard' | 'confidential' | 'crown_jewel';
  moneyMovement?: boolean;
}

export interface BrainStage {
  id: BrainStageId;
  name: string;
  primitives: BrainPrimitiveId[];
  deliverable: string;
  gate: 'auto' | 'human' | 'policy' | 'confidence';
}

export interface CadeDeploymentPattern {
  product: BrainProduct;
  target: string;
  issueKinds: string[];
  roster: string[];
  adversary: string;
  reviewer: string;
  settlement: string;
  proofLabel: string;
}

export interface BrainRecipe {
  id: string;
  surface: BrainSurface;
  northStar: string;
  settlement: string;
  stages: BrainStage[];
  primitives: BrainPrimitive[];
  cade: CadeDeploymentPattern;
  guardrails: string[];
  metrics: string[];
  deploymentPrompt: string;
}

export interface BrainReceipt {
  recipeId: string;
  product: BrainProduct;
  surface: string;
  primitiveIds: BrainPrimitiveId[];
  stageIds: BrainStageId[];
  digest: string;
}
