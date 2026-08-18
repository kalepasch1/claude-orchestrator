/**
 * Fleet immune system — shared domain contracts.
 *
 * Types only. Nothing here kills a process, writes a row, schedules a daemon or
 * reads a database; sibling work items implement the actuators against these
 * shapes. See `runner/FLEET_IMMUNE_CONTRACTS.md` for the incident these encode
 * and `runner/fleet_immune_contracts.py` for the Python side of the same
 * vocabulary — the string values below are deliberately identical so a verdict
 * crossing the language boundary needs no translation table.
 */

/** Bumped when a value's *meaning* changes, not when a field is added. */
export const CONTRACT_VERSION = '1.0.0' as const;

/**
 * The fleet's source of truth. File mirrors are advisory (offline mode, humans
 * tailing logs); a consumer that reads only the file goes blind the moment the
 * writer moves to the DB — that was diagnosis 5 of the 2026-08-02 incident.
 */
export const AUTHORITATIVE_SOURCE = 'db' as const;

/* ------------------------------------------------------------------ *
 * Enumerations
 * ------------------------------------------------------------------ */

/**
 * Lifecycle of a coder lane.
 *
 * `zombie` is the state that did not exist during the incident: 64 of 66 lanes
 * were over an hour old, pinning RAM and claim slots, and nothing could name
 * them.
 */
export const LANE_STATES = ['idle', 'claimed', 'running', 'suspect', 'zombie', 'released'] as const;
export type LaneState = (typeof LANE_STATES)[number];

/** Lifecycle of a worker process. */
export const WORKER_STATES = ['starting', 'ready', 'busy', 'draining', 'stopped', 'leaked'] as const;
export type WorkerState = (typeof WORKER_STATES)[number];

/**
 * Liveness of a runner host.
 *
 * `unknown` exists so it can be *rejected*: an unknown heartbeat age must never
 * classify as healthy. Mac 2 was dark for hours because "no data" and "fine"
 * were the same value.
 */
export const RUNNER_STATUSES = ['up', 'degraded', 'down', 'unknown'] as const;
export type RunnerStatus = (typeof RUNNER_STATUSES)[number];

/** Coarse health band shared by every subject the immune system observes. */
export const HEALTH_LEVELS = ['healthy', 'degraded', 'critical', 'unknown'] as const;
export type HealthLevel = (typeof HEALTH_LEVELS)[number];

/** Whether a subject may take on more work, and why not when it may not. */
export const CAPACITY_STATES = ['available', 'saturated', 'held', 'starved'] as const;
export type CapacityState = (typeof CAPACITY_STATES)[number];

/** Terminal and in-flight states of an assignment. */
export const ASSIGNMENT_STATES = ['pending', 'assigned', 'running', 'done', 'failed', 'abandoned'] as const;
export type AssignmentState = (typeof ASSIGNMENT_STATES)[number];

/* ------------------------------------------------------------------ *
 * Base fields
 * ------------------------------------------------------------------ */

/**
 * Timestamps every observable subject carries.
 * Epoch milliseconds, not ISO strings: ages are compared numerically against
 * second-based thresholds, and string dates invite timezone bugs in that math.
 */
export interface Timestamps {
  createdAt: number;
  updatedAt: number;
  /** Last time the subject proved it was alive. `null` means never — not "now". */
  lastHeartbeatAt: number | null;
}

/**
 * Provenance for anything the immune system records.
 *
 * `reason` is not optional. Diagnosis 6 was a missing-reason bug: the release
 * batch floor held small merges from production exactly as coded, and no log
 * anywhere said so. Nothing is held or reaped without a reason.
 */
export interface AuditFields {
  observedAt: number;
  observedBy: string;
  reason: string;
  contractVer: string;
  source: typeof AUTHORITATIVE_SOURCE | 'file';
}

/* ------------------------------------------------------------------ *
 * Identities
 * ------------------------------------------------------------------ */

export interface LaneIdentity {
  laneId: string;
  host: string;
  /** Owning worker, or `null` when the lane is unclaimed. */
  workerId: string | null;
}

export interface WorkerIdentity {
  workerId: string;
  host: string;
  pid: number;
  /** Free-form role label, e.g. `coder`, `merger`, `release-train`. */
  role: string;
}

export interface RunnerIdentity {
  runnerId: string;
  host: string;
  /** Git sha or build id the runner is running, for drift detection. */
  version: string;
}

/* ------------------------------------------------------------------ *
 * Observations
 * ------------------------------------------------------------------ */

export interface ClaimCapacity {
  subject: string;
  state: CapacityState;
  /** Tasks eligible to be claimed right now. */
  claimable: number;
  /** Tasks actually claimed. A large `claimable` with `claiming` near zero is diagnosis 3. */
  claiming: number;
  /** Hard ceiling on concurrent claims. */
  limit: number;
}

export interface JobAssignment {
  assignmentId: string;
  taskId: string;
  lane: LaneIdentity;
  worker: WorkerIdentity;
  state: AssignmentState;
  attempt: number;
  timestamps: Timestamps;
  audit: AuditFields;
}

export interface LaneSnapshot {
  identity: LaneIdentity;
  state: LaneState;
  health: HealthLevel;
  ageSeconds: number;
  timestamps: Timestamps;
}

export interface WorkerSnapshot {
  identity: WorkerIdentity;
  state: WorkerState;
  health: HealthLevel;
  activeLanes: number;
  timestamps: Timestamps;
}

export interface RunnerSnapshot {
  identity: RunnerIdentity;
  status: RunnerStatus;
  health: HealthLevel;
  /** `null` when the heartbeat age is unknown — which classifies as `down`, never `up`. */
  heartbeatAgeSeconds: number | null;
  timestamps: Timestamps;
}
