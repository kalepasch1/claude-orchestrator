/**
 * Throughput-accelerator and weak-coder-routing policy contracts.
 *
 * Types, constants and boundary validators only. Nothing here merges a branch,
 * schedules a batch or picks a route — sibling work items implement those
 * against these shapes.
 *
 * The defaults encode two findings from the 2026-08-02 incident:
 *
 *   - diagnosis 6: a release batch floor of 10 silently held small merges out of
 *     production. `RELEASE_MIN_BATCH_RECOVERY = 1` is the recovery-mode floor,
 *     and `MAX_HOLD_SECONDS` exists so a waiting batch ships on age regardless
 *     of any floor. A floor without an age override is a floor that can hold
 *     forever.
 *   - diagnosis 7: weak coder routes produced `0/12 merged` on legal-class
 *     tasks. `ROUTE_MIN_SAMPLES` is the evidence bar before a route may be
 *     demoted, so one unlucky batch cannot demote a good route.
 *
 * Validator note: the small `check`/`object` helpers below are local rather than
 * imported from `./schemas.ts`. That keeps this file a pure addition to the
 * package, so it merges independently of the branch that introduced the domain
 * schemas. Fold them together once both have landed.
 */
import { CONTRACT_VERSION, type AuditFields, type WorkerIdentity } from './domain.ts';

/* ------------------------------------------------------------------ *
 * Defaults — mirror the env vars in runner/FLEET_IMMUNE_CONTRACTS.md
 * ------------------------------------------------------------------ */

/** Recovery-mode release floor. Was 10; a floor of 10 is what held diagnosis 6. */
export const RELEASE_MIN_BATCH_RECOVERY = 1 as const;
/** Steady-state floor, used only when the fleet is not in recovery mode. */
export const RELEASE_MIN_BATCH_STEADY = 5 as const;
/** A waiting batch ships at this age whatever the floor says. */
export const RELEASE_MAX_HOLD_SECONDS = 3600 as const;
/** Evidence required before a route may be demoted. */
export const ROUTE_MIN_SAMPLES = 6 as const;
/** Merge rate below which a route is demoted, once it has enough samples. */
export const ROUTE_MIN_MERGE_RATE = 0.15 as const;

/* ------------------------------------------------------------------ *
 * Enumerations
 * ------------------------------------------------------------------ */

export const RELEASE_TRAIN_STATES = ['idle', 'accumulating', 'holding', 'releasing', 'blocked'] as const;
export type ReleaseTrainState = (typeof RELEASE_TRAIN_STATES)[number];

export const MERGE_CANDIDATE_STATES = ['pending', 'eligible', 'held', 'merged', 'rejected'] as const;
export type MergeCandidateState = (typeof MERGE_CANDIDATE_STATES)[number];

/** What a routing decision did. `hold` is distinct from `block`: hold is retryable. */
export const ROUTE_DECISIONS = ['promote', 'keep', 'demote', 'hold', 'block'] as const;
export type RouteDecision = (typeof ROUTE_DECISIONS)[number];

/* ------------------------------------------------------------------ *
 * Config and batch shapes
 * ------------------------------------------------------------------ */

export interface MergeWindow {
  /** Minutes past the hour the window opens, 0–1439 in local fleet time. */
  opensAtMinute: number;
  /** Window length in minutes. Zero means "always open". */
  durationMinutes: number;
}

export interface ReleaseTrainConfig {
  /** Minimum candidates before a batch may release. */
  batchFloor: number;
  mergeWindow: MergeWindow;
  /**
   * Recovery mode lowers the floor to `RELEASE_MIN_BATCH_RECOVERY`. It is a
   * flag rather than a computed state so an operator can force it on.
   */
  recoveryMode: boolean;
  /** Seconds after which a held batch releases regardless of `batchFloor`. */
  maxHoldSeconds: number;
  contractVer: string;
}

export interface MergeCandidate {
  candidateId: string;
  taskId: string;
  branch: string;
  baseBranch: string;
  state: MergeCandidateState;
  /** Seconds this candidate has been waiting. Drives the age override. */
  waitingSeconds: number;
  /** Files the branch touches; used by conflict pre-screening downstream. */
  changedFiles: number;
}

export interface ReleaseTrainBatch {
  batchId: string;
  state: ReleaseTrainState;
  candidates: MergeCandidate[];
  config: ReleaseTrainConfig;
  audit: AuditFields;
}

/* ------------------------------------------------------------------ *
 * Routing shapes
 * ------------------------------------------------------------------ */

export interface CoderQualityMetric {
  /** Provider/model route key, e.g. `claude:claude-haiku-4-5-20251001`. */
  route: string;
  taskClass: string;
  /** Attempts observed. Below ROUTE_MIN_SAMPLES a demotion is not evidence-backed. */
  samples: number;
  merged: number;
  testPassed: number;
  /** `merged / samples`, precomputed so consumers cannot each derive it differently. */
  mergeRate: number;
  costUsd: number;
}

export interface RouteScore {
  route: string;
  taskClass: string;
  /** Normalised 0–1 quality; higher is better. */
  score: number;
  decision: RouteDecision;
  /** Never optional: nothing is demoted or held without a reason. */
  reason: string;
  metric: CoderQualityMetric;
}

/**
 * The interface a routing implementation satisfies. Declared, not implemented —
 * the actual scoring lives in the sibling that owns routing.
 */
export interface RoutingPolicy {
  readonly name: string;
  readonly minSamples: number;
  readonly minMergeRate: number;
  /** Pure: same metrics in, same score out. No IO, no clock, no randomness. */
  score(metric: CoderQualityMetric): RouteScore;
  /** Best route for a task class, or null when no route clears the bar. */
  select(taskClass: string, metrics: readonly CoderQualityMetric[]): RouteScore | null;
}

/** The default config, in recovery mode, matching the constants above. */
export const DEFAULT_RELEASE_TRAIN_CONFIG: ReleaseTrainConfig = {
  batchFloor: RELEASE_MIN_BATCH_RECOVERY,
  mergeWindow: { opensAtMinute: 0, durationMinutes: 0 },
  recoveryMode: true,
  maxHoldSeconds: RELEASE_MAX_HOLD_SECONDS,
  contractVer: CONTRACT_VERSION,
};

/* ------------------------------------------------------------------ *
 * Validators (Zod-shaped, dependency-free — see the file header)
 * ------------------------------------------------------------------ */

export interface PolicyIssue {
  path: string;
  message: string;
}

export type PolicyParseResult<T> =
  | { success: true; data: T }
  | { success: false; issues: PolicyIssue[] };

export interface PolicySchema<T> {
  readonly name: string;
  parse(value: unknown): T;
  safeParse(value: unknown): PolicyParseResult<T>;
  is(value: unknown): value is T;
}

export class PolicyError extends Error {
  readonly issues: PolicyIssue[];
  constructor(name: string, issues: PolicyIssue[]) {
    super(`${name}: ${issues.map(i => `${i.path || '<root>'} ${i.message}`).join('; ')}`);
    this.name = 'PolicyError';
    this.issues = issues;
  }
}

type PolicyCheck = (value: unknown, path: string, issues: PolicyIssue[]) => void;

function isObj(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const pStr: PolicyCheck = (v, path, issues) => {
  if (typeof v !== 'string' || v.length === 0) issues.push({ path, message: 'must be a non-empty string' });
};

const pBool: PolicyCheck = (v, path, issues) => {
  if (typeof v !== 'boolean') issues.push({ path, message: 'must be a boolean' });
};

/** Non-negative integer. A negative batch floor is the canonical invalid value. */
const pIntMin = (min: number, max?: number): PolicyCheck => (v, path, issues) => {
  if (typeof v !== 'number' || !Number.isInteger(v)) {
    issues.push({ path, message: 'must be an integer' });
    return;
  }
  if (v < min) issues.push({ path, message: `must be >= ${min}` });
  if (max !== undefined && v > max) issues.push({ path, message: `must be <= ${max}` });
};

const pRate: PolicyCheck = (v, path, issues) => {
  if (typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > 1) {
    issues.push({ path, message: 'must be a number between 0 and 1' });
  }
};

const pEnum = (allowed: readonly string[]): PolicyCheck => (v, path, issues) => {
  if (typeof v !== 'string' || !allowed.includes(v)) {
    issues.push({ path, message: `must be one of: ${allowed.join(', ')}` });
  }
};

const pNested = <T>(schema: PolicySchema<T>): PolicyCheck => (v, path, issues) => {
  const result = schema.safeParse(v);
  if (!result.success) {
    for (const issue of result.issues) {
      issues.push({ path: issue.path ? `${path}.${issue.path}` : path, message: issue.message });
    }
  }
};

const pArrayOf = <T>(schema: PolicySchema<T>): PolicyCheck => (v, path, issues) => {
  if (!Array.isArray(v)) {
    issues.push({ path, message: 'must be an array' });
    return;
  }
  v.forEach((item, i) => {
    const result = schema.safeParse(item);
    if (!result.success) {
      for (const issue of result.issues) {
        issues.push({ path: `${path}[${i}]${issue.path ? `.${issue.path}` : ''}`, message: issue.message });
      }
    }
  });
};

function policyObject<T>(name: string, shape: Record<string, PolicyCheck>): PolicySchema<T> {
  const schema: PolicySchema<T> = {
    name,
    safeParse(value: unknown): PolicyParseResult<T> {
      if (!isObj(value)) return { success: false, issues: [{ path: '', message: 'must be an object' }] };
      const issues: PolicyIssue[] = [];
      for (const [key, check] of Object.entries(shape)) {
        if (!(key in value)) {
          issues.push({ path: key, message: 'is required' });
          continue;
        }
        check(value[key], key, issues);
      }
      return issues.length ? { success: false, issues } : { success: true, data: value as T };
    },
    parse(value: unknown): T {
      const result = schema.safeParse(value);
      if (!result.success) throw new PolicyError(name, result.issues);
      return result.data;
    },
    is(value: unknown): value is T {
      return schema.safeParse(value).success;
    },
  };
  return schema;
}

export const mergeWindowSchema = policyObject<MergeWindow>('MergeWindow', {
  opensAtMinute: pIntMin(0, 1439),
  durationMinutes: pIntMin(0, 1440),
});

export const releaseTrainConfigSchema = policyObject<ReleaseTrainConfig>('ReleaseTrainConfig', {
  batchFloor: pIntMin(0),
  mergeWindow: pNested(mergeWindowSchema),
  recoveryMode: pBool,
  maxHoldSeconds: pIntMin(0),
  contractVer: pStr,
});

export const mergeCandidateSchema = policyObject<MergeCandidate>('MergeCandidate', {
  candidateId: pStr,
  taskId: pStr,
  branch: pStr,
  baseBranch: pStr,
  state: pEnum(MERGE_CANDIDATE_STATES),
  waitingSeconds: pIntMin(0),
  changedFiles: pIntMin(0),
});

export const coderQualityMetricSchema = policyObject<CoderQualityMetric>('CoderQualityMetric', {
  route: pStr,
  taskClass: pStr,
  samples: pIntMin(0),
  merged: pIntMin(0),
  testPassed: pIntMin(0),
  mergeRate: pRate,
  costUsd: (v, path, issues) => {
    if (typeof v !== 'number' || !Number.isFinite(v) || v < 0) {
      issues.push({ path, message: 'must be a non-negative number' });
    }
  },
});

export const routeScoreSchema = policyObject<RouteScore>('RouteScore', {
  route: pStr,
  taskClass: pStr,
  score: pRate,
  decision: pEnum(ROUTE_DECISIONS),
  reason: pStr,
  metric: pNested(coderQualityMetricSchema),
});

/** Local audit validator, so this file stays a pure addition to the package. */
export const policyAuditSchema = policyObject<AuditFields>('AuditFields', {
  observedAt: (v, path, issues) => {
    if (typeof v !== 'number' || !Number.isFinite(v)) issues.push({ path, message: 'must be a finite number' });
  },
  observedBy: pStr,
  reason: pStr,
  contractVer: pStr,
  source: pEnum(['db', 'file']),
});

export const releaseTrainBatchSchema = policyObject<ReleaseTrainBatch>('ReleaseTrainBatch', {
  batchId: pStr,
  state: pEnum(RELEASE_TRAIN_STATES),
  candidates: pArrayOf(mergeCandidateSchema),
  config: pNested(releaseTrainConfigSchema),
  audit: pNested(policyAuditSchema),
});

/** The effective batch floor for a config. Pure; no clock, no IO. */
export function effectiveBatchFloor(config: ReleaseTrainConfig): number {
  return config.recoveryMode ? RELEASE_MIN_BATCH_RECOVERY : config.batchFloor;
}

/** Type-only marker so a routing implementation can assert it satisfies the policy. */
export type RoutingPolicyOf<T extends RoutingPolicy> = T;

/** Re-exported for callers that stamp routing decisions. */
export type { AuditFields, WorkerIdentity };
