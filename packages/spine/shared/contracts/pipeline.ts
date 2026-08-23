/**
 * Pipeline structure contracts for the compounding code-generation platform.
 *
 * `compound.ts` / `wave.ts` describe WHAT gets run and in what order. This file
 * describes the SHAPE of the thing being run: a pipeline is the stage graph a
 * wave executes, and its descriptor is what the code generator reads to emit an
 * implementation.
 *
 * Declaration-only, like every file in `shared/contracts` — nothing here may
 * carry a runtime value. Downstream slices fill in the details, so fields whose
 * shape is not yet settled are typed `unknown` rather than guessed at: an
 * `unknown` forces a consumer to narrow, whereas a speculative interface lets
 * wrong assumptions compile.
 */

import type { EpochMillis, WaveId } from "./common.ts";

/** Opaque identifier for a pipeline. Branded so a raw string cannot be passed by accident. */
export type PipelineId = string & { readonly __brand: "PipelineId" };

/** Opaque identifier for one stage within a pipeline. Unique per pipeline, not globally. */
export type PipelineStageId = string & { readonly __brand: "PipelineStageId" };

/**
 * What a stage does, coarsely. The generator switches on this to decide which
 * emitter to use, so it is a closed union rather than a free string — a new
 * kind is a deliberate, reviewable addition, not a typo that silently produces
 * no code.
 */
export type PipelineStageKind =
  | "source"
  | "transform"
  | "validate"
  | "generate"
  | "verify"
  | "publish";

/**
 * Lifecycle of a single stage. `skipped` is distinct from `succeeded`: a stage
 * whose guard excluded it did not prove anything, and treating the two as equal
 * is how a pipeline reports green while never having run its checks.
 */
export type PipelineStageStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "skipped"
  | "failed";

/**
 * One node of the stage graph.
 *
 * `dependsOn` is what makes this a graph rather than a list, and it is declared
 * per-stage rather than as a separate edge set so a stage cannot be copied into
 * another pipeline while leaving its edges behind.
 */
export interface PipelineStage {
  readonly id: PipelineStageId;
  readonly kind: PipelineStageKind;
  /** Human-facing label. Not an identifier — never key off this. */
  readonly name: string;
  /**
   * Stages that must reach a terminal non-failed status before this one starts.
   * Empty means the stage is a root. Must reference ids within the same
   * `PipelineStructure`; a dangling id is a malformed pipeline, not a no-op.
   */
  readonly dependsOn: readonly PipelineStageId[];
  /**
   * Stage-specific configuration. Deliberately `unknown`: each `kind` has its
   * own settled shape, and those shapes are owned by the slices that implement
   * the emitters. Narrow on `kind` before reading.
   */
  readonly config?: unknown;
}

/**
 * The stage graph a wave executes.
 *
 * `stages` is a flat list plus per-stage `dependsOn` rather than a nested tree
 * because a stage can have several dependents, which a tree cannot express
 * without duplicating the node.
 */
export interface PipelineStructure {
  readonly id: PipelineId;
  /** Monotonic; a structure is immutable once referenced by a wave. */
  readonly version: number;
  readonly stages: readonly PipelineStage[];
  /**
   * Roots to start from. Redundant with `dependsOn: []` and kept anyway so a
   * malformed graph (every stage depending on another, i.e. a cycle) is
   * detectable without traversing it.
   */
  readonly entryStageIds: readonly PipelineStageId[];
}

/** A stage's observed state during one wave. Contracts carry no `Date`. */
export interface PipelineStageState {
  readonly stageId: PipelineStageId;
  readonly status: PipelineStageStatus;
  readonly startedAt?: EpochMillis;
  readonly finishedAt?: EpochMillis;
  /** Present only when `status` is `failed`. */
  readonly failureReason?: string;
}

/**
 * What the generator emitted for one pipeline, and from what.
 *
 * `sourceDigest` is the point of this record: regeneration is only safe to skip
 * when the inputs are byte-identical, so the digest is over the generator's
 * inputs, not over its output. Comparing outputs would make any change in
 * emitter formatting look like a change in meaning.
 */
export interface CodegenMetadata {
  readonly pipelineId: PipelineId;
  /** Structure version this output was generated from. */
  readonly pipelineVersion: number;
  /** Identifier of the emitter that produced the output. */
  readonly generator: string;
  /** Emitter version, so output can be attributed after the emitter changes. */
  readonly generatorVersion: string;
  /** Content digest over the generator's INPUTS. Skip regeneration only on an exact match. */
  readonly sourceDigest: string;
  readonly generatedAt: EpochMillis;
  /** Paths written, relative to the target repo root. */
  readonly emittedPaths: readonly string[];
}

/**
 * How one wave's output compounds into the next.
 *
 * "Compounding" is the platform's whole premise: a wave does not just run, it
 * leaves behind something the next wave starts from. `carriedForward` is that
 * something. It is `unknown` because what compounds differs per wave kind and
 * is owned by downstream slices — the contract fixes that a payload exists and
 * which wave produced it, not what is in it.
 */
export interface CompoundingMetadata {
  /** Wave that produced this contribution. */
  readonly waveId: WaveId;
  /** Waves whose output this one built on. Empty for the first wave in a compound. */
  readonly builtOn: readonly WaveId[];
  /** 0 for the first wave, incrementing along the compounding chain. */
  readonly generation: number;
  /** Payload handed to the next wave. Narrow before use. */
  readonly carriedForward?: unknown;
  readonly codegen?: CodegenMetadata;
}

/**
 * The passport shape the spine exchanges with `@darwin/kernel`.
 *
 * Declared structurally here rather than imported from `@darwin/kernel` on
 * purpose. `@spine/contracts` is declaration-only with zero dependencies, and
 * importing the kernel would pull a runtime package into a contract surface
 * whose entire value is that a consumer can depend on it without depending on
 * an implementation.
 *
 * The trade is explicit: this must stay structurally assignable from the
 * kernel's `Passport`. Fields are typed to match it (ISO-8601 strings, not
 * `EpochMillis`, because that is what the kernel emits — converting here would
 * break the digest, which is computed over the string form). `signature` and
 * per-claim `detail` are `unknown`: their shapes belong to the kernel's crypto
 * layer, and restating them here would be a second source of truth that can
 * drift silently.
 */

/** What a passport claim asserts. Additive — a new kind is non-breaking. */
export type PassportClaimKind =
  | "kyc_verified"
  | "ecp_eligible"
  | "accredited"
  | "geo_allowed"
  | "credit_quality"
  | "financial_profile"
  | "reliability"
  | "guardian_verified"
  | "sanctions_clear";

export interface PassportClaim {
  readonly kind: PassportClaimKind;
  /** Issuing product id. */
  readonly issuer: string;
  /** Score or band where meaningful; 1 for boolean claims. */
  readonly value: number;
  /** Structured detail owned by the issuer. Narrow before use. */
  readonly detail?: unknown;
  /** ISO-8601. */
  readonly issuedAt: string;
  /** ISO-8601. A consumer MUST reject an expired passport rather than warn. */
  readonly expiresAt: string;
}

/**
 * A portable, content-addressed, signed credential carried between products.
 *
 * Verified offline against `digest` + `signature`; the spine never calls back
 * to the issuer, which is the property that makes the passport worth passing
 * through a pipeline at all.
 */
export interface PassportData {
  readonly id: string;
  /** Stable subject id within the identity graph. */
  readonly subject: string;
  readonly version: 1;
  readonly claims: readonly PassportClaim[];
  /** ISO-8601. */
  readonly issuedAt: string;
  /** Digest over the canonical form of {subject, version, claims, issuedAt}. */
  readonly digest: string;
  /** Signature envelope; shape owned by the kernel's crypto layer. */
  readonly signature: unknown;
}
