/**
 * Runtime schemas for the fleet immune contracts.
 *
 * Why not Zod
 * -----------
 * The task allows Zod or io-ts. This package follows `@darwin/kernel`'s stated
 * convention — *zero runtime dependencies*, TypeScript source consumed directly —
 * because these contracts are imported by Python-adjacent tooling, by the Nuxt
 * app and by scripts run with `node --experimental-strip-types`, and a package
 * that needs an install step is a package that blocks a sibling on a broken
 * node_modules tree. (This repo currently has one: `web/node_modules` holds 250
 * truncated packages.)
 *
 * The surface below is deliberately Zod-shaped — `parse` throws, `safeParse`
 * returns a discriminated result — so swapping in Zod later is a mechanical
 * change at the boundary, not a rewrite of every caller.
 *
 * Validation is *closed*: unknown enum members and missing required fields are
 * rejected. That is the point. An unrecognised LaneState must not sail through
 * a boundary and land in a classifier that has no branch for it.
 */
import {
  ASSIGNMENT_STATES,
  AUTHORITATIVE_SOURCE,
  CAPACITY_STATES,
  CONTRACT_VERSION,
  HEALTH_LEVELS,
  LANE_STATES,
  RUNNER_STATUSES,
  WORKER_STATES,
  type AssignmentState,
  type AuditFields,
  type CapacityState,
  type ClaimCapacity,
  type HealthLevel,
  type JobAssignment,
  type LaneIdentity,
  type LaneSnapshot,
  type LaneState,
  type RunnerIdentity,
  type RunnerSnapshot,
  type RunnerStatus,
  type Timestamps,
  type WorkerIdentity,
  type WorkerSnapshot,
  type WorkerState,
} from './domain.ts';

export interface SchemaIssue {
  path: string;
  message: string;
}

export type SafeParseResult<T> =
  | { success: true; data: T }
  | { success: false; issues: SchemaIssue[] };

export interface Schema<T> {
  readonly name: string;
  /** Throws `SchemaError` on invalid input. */
  parse(value: unknown): T;
  /** Never throws; returns the issues instead. */
  safeParse(value: unknown): SafeParseResult<T>;
  /** Type guard, for call sites that only need a boolean. */
  is(value: unknown): value is T;
}

export class SchemaError extends Error {
  readonly issues: SchemaIssue[];
  constructor(name: string, issues: SchemaIssue[]) {
    super(`${name}: ${issues.map(i => `${i.path || '<root>'} ${i.message}`).join('; ')}`);
    this.name = 'SchemaError';
    this.issues = issues;
  }
}

/* ------------------------------------------------------------------ *
 * Primitive checkers
 * ------------------------------------------------------------------ */

type Check = (value: unknown, path: string, issues: SchemaIssue[]) => void;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const str: Check = (v, path, issues) => {
  if (typeof v !== 'string' || v.length === 0) issues.push({ path, message: 'must be a non-empty string' });
};

const num: Check = (v, path, issues) => {
  if (typeof v !== 'number' || !Number.isFinite(v)) issues.push({ path, message: 'must be a finite number' });
};

const int = (min?: number): Check => (v, path, issues) => {
  if (typeof v !== 'number' || !Number.isInteger(v)) {
    issues.push({ path, message: 'must be an integer' });
    return;
  }
  if (min !== undefined && v < min) issues.push({ path, message: `must be >= ${min}` });
};

const nullableNum: Check = (v, path, issues) => {
  if (v === null) return;
  num(v, path, issues);
};

const nullableStr: Check = (v, path, issues) => {
  if (v === null) return;
  str(v, path, issues);
};

const oneOf = (allowed: readonly string[]): Check => (v, path, issues) => {
  if (typeof v !== 'string' || !allowed.includes(v)) {
    issues.push({ path, message: `must be one of: ${allowed.join(', ')}` });
  }
};

const nested = <T>(schema: Schema<T>): Check => (v, path, issues) => {
  const result = schema.safeParse(v);
  if (!result.success) {
    for (const issue of result.issues) {
      issues.push({ path: issue.path ? `${path}.${issue.path}` : path, message: issue.message });
    }
  }
};

function object<T>(name: string, shape: Record<string, Check>): Schema<T> {
  const schema: Schema<T> = {
    name,
    safeParse(value: unknown): SafeParseResult<T> {
      const issues: SchemaIssue[] = [];
      if (!isPlainObject(value)) return { success: false, issues: [{ path: '', message: 'must be an object' }] };
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
      if (!result.success) throw new SchemaError(name, result.issues);
      return result.data;
    },
    is(value: unknown): value is T {
      return schema.safeParse(value).success;
    },
  };
  return schema;
}

function enumeration<T extends string>(name: string, allowed: readonly T[]): Schema<T> {
  const schema: Schema<T> = {
    name,
    safeParse(value: unknown): SafeParseResult<T> {
      if (typeof value === 'string' && (allowed as readonly string[]).includes(value)) {
        return { success: true, data: value as T };
      }
      return { success: false, issues: [{ path: '', message: `must be one of: ${allowed.join(', ')}` }] };
    },
    parse(value: unknown): T {
      const result = schema.safeParse(value);
      if (!result.success) throw new SchemaError(name, result.issues);
      return result.data;
    },
    is(value: unknown): value is T {
      return schema.safeParse(value).success;
    },
  };
  return schema;
}

/* ------------------------------------------------------------------ *
 * Enum schemas
 * ------------------------------------------------------------------ */

export const laneStateSchema = enumeration<LaneState>('LaneState', LANE_STATES);
export const workerStateSchema = enumeration<WorkerState>('WorkerState', WORKER_STATES);
export const runnerStatusSchema = enumeration<RunnerStatus>('RunnerStatus', RUNNER_STATUSES);
export const healthLevelSchema = enumeration<HealthLevel>('HealthLevel', HEALTH_LEVELS);
export const capacityStateSchema = enumeration<CapacityState>('CapacityState', CAPACITY_STATES);
export const assignmentStateSchema = enumeration<AssignmentState>('AssignmentState', ASSIGNMENT_STATES);

/* ------------------------------------------------------------------ *
 * Object schemas
 * ------------------------------------------------------------------ */

export const timestampsSchema = object<Timestamps>('Timestamps', {
  createdAt: num,
  updatedAt: num,
  lastHeartbeatAt: nullableNum,
});

export const auditFieldsSchema = object<AuditFields>('AuditFields', {
  observedAt: num,
  observedBy: str,
  reason: str,
  contractVer: str,
  source: oneOf([AUTHORITATIVE_SOURCE, 'file']),
});

export const laneIdentitySchema = object<LaneIdentity>('LaneIdentity', {
  laneId: str,
  host: str,
  workerId: nullableStr,
});

export const workerIdentitySchema = object<WorkerIdentity>('WorkerIdentity', {
  workerId: str,
  host: str,
  pid: int(1),
  role: str,
});

export const runnerIdentitySchema = object<RunnerIdentity>('RunnerIdentity', {
  runnerId: str,
  host: str,
  version: str,
});

export const claimCapacitySchema = object<ClaimCapacity>('ClaimCapacity', {
  subject: str,
  state: oneOf(CAPACITY_STATES),
  claimable: int(0),
  claiming: int(0),
  limit: int(0),
});

export const jobAssignmentSchema = object<JobAssignment>('JobAssignment', {
  assignmentId: str,
  taskId: str,
  lane: nested(laneIdentitySchema),
  worker: nested(workerIdentitySchema),
  state: oneOf(ASSIGNMENT_STATES),
  attempt: int(0),
  timestamps: nested(timestampsSchema),
  audit: nested(auditFieldsSchema),
});

export const laneSnapshotSchema = object<LaneSnapshot>('LaneSnapshot', {
  identity: nested(laneIdentitySchema),
  state: oneOf(LANE_STATES),
  health: oneOf(HEALTH_LEVELS),
  ageSeconds: num,
  timestamps: nested(timestampsSchema),
});

export const workerSnapshotSchema = object<WorkerSnapshot>('WorkerSnapshot', {
  identity: nested(workerIdentitySchema),
  state: oneOf(WORKER_STATES),
  health: oneOf(HEALTH_LEVELS),
  activeLanes: int(0),
  timestamps: nested(timestampsSchema),
});

export const runnerSnapshotSchema = object<RunnerSnapshot>('RunnerSnapshot', {
  identity: nested(runnerIdentitySchema),
  status: oneOf(RUNNER_STATUSES),
  health: oneOf(HEALTH_LEVELS),
  heartbeatAgeSeconds: nullableNum,
  timestamps: nested(timestampsSchema),
});

/** Convenience for producers: audit fields stamped with the current contract version. */
export function auditNow(observedBy: string, reason: string, at: number = Date.now()): AuditFields {
  return {
    observedAt: at,
    observedBy,
    reason,
    contractVer: CONTRACT_VERSION,
    source: AUTHORITATIVE_SOURCE,
  };
}
