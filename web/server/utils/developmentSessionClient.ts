/**
 * developmentSessionClient.ts — the shared development-session client.
 *
 * One client, many UIs. Madeus (`components/DevelopmentTerminal.vue`) is the
 * reference consumer; anything else that wants to watch a development session
 * imports the same reducer and projections so two surfaces can never disagree
 * about what a session did.
 *
 * Three rules this module exists to enforce:
 *
 *  1. **The web app never executes.** Vercel functions may not shell out, touch
 *     the filesystem, or hold a service-role SQL connection. The client only
 *     ever *reads* a broker stream. `assertBrokerSafe` is the gate, and it is
 *     called on construction rather than left to reviewer vigilance.
 *  2. **Durable cursor replay.** Every event carries a monotonic cursor. A
 *     reconnect resumes from the last cursor seen, and replayed events are
 *     idempotent, so a dropped socket loses no output and duplicates nothing.
 *  3. **UNKNOWN stays UNKNOWN.** A proof step with no evidence projects as
 *     `unknown`, never as `pass`. There is no demo mode and no optimistic
 *     default — a green checklist has to be earned.
 *
 * Pure and transport-agnostic: SSE, WebSocket and Supabase realtime all reduce
 * to `applyEvent`, so the whole surface is unit-testable in node.
 */

export type SessionPhase =
  | 'unknown' | 'queued' | 'planning' | 'executing' | 'verifying' | 'integrating' | 'released' | 'failed';

export type StreamKind = 'stdout' | 'stderr' | 'tool' | 'system';

export type ProofStatus = 'pass' | 'fail' | 'unknown';

export interface OutputChunk {
  cursor: number;
  kind: StreamKind;
  text: string;
  tool?: string;
  at?: string;
}

export interface SteeringReceipt {
  gate: string;
  decision: 'allow' | 'warn' | 'hold';
  rationale?: string;
  authorities?: string[];
  digest?: string;
}

export interface DevelopmentSessionState {
  sessionId: string;
  phase: SessionPhase;
  /** Host / generation / adapter are UNKNOWN until the broker says otherwise. */
  host: string | null;
  generation: string | null;
  adapter: string | null;
  plan: { planId: string | null; digest: string | null; slices: number | null };
  steering: SteeringReceipt[];
  output: OutputChunk[];
  worktree: { path: string | null; branch: string | null; diffStat: string | null; commit: string | null };
  tests: { command: string | null; passed: boolean | null; artifactUrl: string | null };
  integration: { proofUrl: string | null; merged: boolean | null };
  release: { sha: string | null; url: string | null };
  journey: { productionUrl: string | null; verifiedAt: string | null };
  cursor: number;
  connected: boolean;
  droppedEvents: number;
  duplicateEvents: number;
}

export type SessionEvent =
  | { cursor: number; type: 'session'; phase?: SessionPhase; host?: string; generation?: string; adapter?: string }
  | { cursor: number; type: 'plan'; planId?: string; digest?: string; slices?: number }
  | { cursor: number; type: 'steering'; receipt: SteeringReceipt }
  | { cursor: number; type: 'output'; kind: StreamKind; text: string; tool?: string; at?: string }
  | { cursor: number; type: 'worktree'; path?: string; branch?: string; diffStat?: string; commit?: string }
  | { cursor: number; type: 'tests'; command?: string; passed?: boolean; artifactUrl?: string }
  | { cursor: number; type: 'integration'; proofUrl?: string; merged?: boolean }
  | { cursor: number; type: 'release'; sha?: string; url?: string }
  | { cursor: number; type: 'journey'; productionUrl?: string; verifiedAt?: string };

export class AuthRequiredError extends Error {}
export class UnsafeTransportError extends Error {}

/** Ring-buffer bound so a runaway build cannot exhaust the browser tab. */
export const MAX_OUTPUT_LINES = 5000;

const FORBIDDEN_TRANSPORT = /^(file|shell|exec|postgres|postgresql):/i;
const SERVICE_ROLE_HINT = /service[_-]?role/i;

/**
 * The web app is a viewer. Anything that would let it execute — a shell or file
 * URL, a direct Postgres DSN, or a service-role key smuggled in as a token — is
 * refused here rather than in review.
 */
export function assertBrokerSafe(opts: { brokerUrl: string; token?: string | null }): void {
  const url = String(opts.brokerUrl || '');
  if (!url) throw new UnsafeTransportError('brokerUrl is required');
  if (FORBIDDEN_TRANSPORT.test(url)) {
    throw new UnsafeTransportError(
      `refusing transport ${url.split(':')[0]}: the web app may not shell out, read the filesystem, or hold a raw SQL connection`,
    );
  }
  if (!/^(https?|wss?):\/\//i.test(url)) {
    throw new UnsafeTransportError(`brokerUrl must be http(s) or ws(s), got ${url}`);
  }
  if (opts.token && SERVICE_ROLE_HINT.test(String(opts.token))) {
    throw new UnsafeTransportError('refusing a service-role credential in a browser-reachable client');
  }
}

export function emptySessionState(sessionId: string): DevelopmentSessionState {
  return {
    sessionId,
    phase: 'unknown',
    host: null,
    generation: null,
    adapter: null,
    plan: { planId: null, digest: null, slices: null },
    steering: [],
    output: [],
    worktree: { path: null, branch: null, diffStat: null, commit: null },
    tests: { command: null, passed: null, artifactUrl: null },
    integration: { proofUrl: null, merged: null },
    release: { sha: null, url: null },
    journey: { productionUrl: null, verifiedAt: null },
    cursor: 0,
    connected: false,
    droppedEvents: 0,
    duplicateEvents: 0,
  };
}

/**
 * Reduce one broker event into state. Idempotent: an event whose cursor has
 * already been applied is counted and discarded, which is what makes replay
 * after a reconnect safe.
 */
export function applyEvent(
  state: DevelopmentSessionState,
  event: SessionEvent,
): DevelopmentSessionState {
  if (!event || typeof event.cursor !== 'number') {
    return { ...state, droppedEvents: state.droppedEvents + 1 };
  }
  if (event.cursor <= state.cursor) {
    return { ...state, duplicateEvents: state.duplicateEvents + 1 };
  }
  const next: DevelopmentSessionState = { ...state, cursor: event.cursor };
  switch (event.type) {
    case 'session':
      if (event.phase) next.phase = event.phase;
      if (event.host) next.host = event.host;
      if (event.generation) next.generation = event.generation;
      if (event.adapter) next.adapter = event.adapter;
      break;
    case 'plan':
      next.plan = {
        planId: event.planId ?? state.plan.planId,
        digest: event.digest ?? state.plan.digest,
        slices: event.slices ?? state.plan.slices,
      };
      break;
    case 'steering':
      next.steering = [...state.steering, event.receipt];
      break;
    case 'output': {
      const chunk: OutputChunk = {
        cursor: event.cursor, kind: event.kind, text: event.text, tool: event.tool, at: event.at,
      };
      const output = [...state.output, chunk];
      next.output = output.length > MAX_OUTPUT_LINES ? output.slice(output.length - MAX_OUTPUT_LINES) : output;
      break;
    }
    case 'worktree':
      next.worktree = {
        path: event.path ?? state.worktree.path,
        branch: event.branch ?? state.worktree.branch,
        diffStat: event.diffStat ?? state.worktree.diffStat,
        commit: event.commit ?? state.worktree.commit,
      };
      break;
    case 'tests':
      next.tests = {
        command: event.command ?? state.tests.command,
        passed: event.passed ?? state.tests.passed,
        artifactUrl: event.artifactUrl ?? state.tests.artifactUrl,
      };
      break;
    case 'integration':
      next.integration = {
        proofUrl: event.proofUrl ?? state.integration.proofUrl,
        merged: event.merged ?? state.integration.merged,
      };
      break;
    case 'release':
      next.release = { sha: event.sha ?? state.release.sha, url: event.url ?? state.release.url };
      break;
    case 'journey':
      next.journey = {
        productionUrl: event.productionUrl ?? state.journey.productionUrl,
        verifiedAt: event.verifiedAt ?? state.journey.verifiedAt,
      };
      break;
    default:
      return { ...state, droppedEvents: state.droppedEvents + 1 };
  }
  return next;
}

export function applyEvents(
  state: DevelopmentSessionState,
  events: SessionEvent[],
): DevelopmentSessionState {
  return (events || []).reduce(applyEvent, state);
}

// ---------------------------------------------------------------------------
// pagination
// ---------------------------------------------------------------------------

export interface OutputPage {
  lines: OutputChunk[];
  offset: number;
  limit: number;
  total: number;
  hasMore: boolean;
}

/** Page the output buffer. `offset` counts from the oldest retained line. */
export function pageOutput(
  state: DevelopmentSessionState,
  offset = 0,
  limit = 200,
): OutputPage {
  const all = state.output;
  const start = Math.max(0, Math.floor(offset));
  const size = Math.max(1, Math.floor(limit));
  const lines = all.slice(start, start + size);
  return { lines, offset: start, limit: size, total: all.length, hasMore: start + size < all.length };
}

/** The cursor a reconnect should resume from — 0 when nothing has been seen. */
export function resumeCursor(state: DevelopmentSessionState): number {
  return state.cursor;
}

// ---------------------------------------------------------------------------
// proof projection — UNKNOWN stays UNKNOWN
// ---------------------------------------------------------------------------

export interface ProofStep {
  key: string;
  label: string;
  status: ProofStatus;
  /** What we actually observed. `null` means we observed nothing. */
  evidence: string | null;
}

function step(key: string, label: string, evidence: string | null, passed: boolean | null): ProofStep {
  if (passed === null || passed === undefined) return { key, label, status: 'unknown', evidence };
  return { key, label, status: passed ? 'pass' : 'fail', evidence };
}

/**
 * Project the session's real evidence onto the verification checklist.
 *
 * This replaces a hardcoded all-green checklist. Absence of evidence is
 * reported as `unknown`; it is never rounded up to `pass`.
 */
export function projectVerificationSteps(state: DevelopmentSessionState): ProofStep[] {
  const s = state || emptySessionState('unknown');
  return [
    step('code_implemented', 'Code implemented', s.worktree.commit, s.worktree.commit ? true : null),
    step('worktree_branch', 'Worktree branch pushed', s.worktree.branch, s.worktree.branch ? true : null),
    step('tests_passed', 'Tests passed', s.tests.command, s.tests.passed ?? null),
    step('test_artifact', 'Test artifact captured', s.tests.artifactUrl, s.tests.artifactUrl ? true : null),
    step('integration_proof', 'Integration proof', s.integration.proofUrl, s.integration.proofUrl ? true : null),
    step('merged', 'Merged', s.integration.merged === null ? null : String(s.integration.merged), s.integration.merged ?? null),
    step('released', 'Release SHA', s.release.sha, s.release.sha ? true : null),
    step('production_journey', 'Production journey verified', s.journey.productionUrl,
      s.journey.verifiedAt ? true : null),
  ];
}

/** True only when every step is a real pass. Any `unknown` keeps it false. */
export function isFullyProven(steps: ProofStep[]): boolean {
  return (steps || []).length > 0 && (steps || []).every((s) => s.status === 'pass');
}

export function proofSummary(steps: ProofStep[]): { pass: number; fail: number; unknown: number; proven: boolean } {
  const acc = { pass: 0, fail: 0, unknown: 0, proven: false };
  for (const s of steps || []) acc[s.status] += 1;
  acc.proven = isFullyProven(steps);
  return acc;
}

// ---------------------------------------------------------------------------
// accessibility
// ---------------------------------------------------------------------------

/** Attributes for the streaming output region so screen readers follow along
 *  without being interrupted on every single line. */
export function outputAriaAttributes(streaming: boolean): Record<string, string> {
  return {
    role: 'log',
    'aria-live': streaming ? 'polite' : 'off',
    'aria-relevant': 'additions text',
    'aria-atomic': 'false',
    'aria-label': 'development session output',
  };
}

/** A short, non-visual description of where the session is. */
export function ariaStatusMessage(state: DevelopmentSessionState): string {
  const s = state || emptySessionState('unknown');
  const where = s.phase === 'unknown' ? 'state unknown' : s.phase;
  const conn = s.connected ? 'connected' : 'disconnected';
  return `Session ${s.sessionId}: ${where}, ${conn}, ${s.output.length} output lines.`;
}

// ---------------------------------------------------------------------------
// client
// ---------------------------------------------------------------------------

export interface ClientOptions {
  sessionId: string;
  brokerUrl: string;
  /** Bearer token. Required — there is no anonymous read of a session. */
  token?: string | null;
  fetchImpl?: typeof fetch;
}

export interface DevelopmentSessionClient {
  getState(): DevelopmentSessionState;
  ingest(events: SessionEvent[]): DevelopmentSessionState;
  /** Fetch the durable replay from `resumeCursor()` and apply it. */
  reconnect(): Promise<DevelopmentSessionState>;
  setConnected(connected: boolean): DevelopmentSessionState;
  page(offset?: number, limit?: number): OutputPage;
  proof(): ProofStep[];
}

export function createDevelopmentSessionClient(opts: ClientOptions): DevelopmentSessionClient {
  if (!opts?.token) {
    throw new AuthRequiredError('a bearer token is required to read a development session');
  }
  assertBrokerSafe({ brokerUrl: opts.brokerUrl, token: opts.token });

  let state = emptySessionState(opts.sessionId);
  const doFetch = opts.fetchImpl ?? (globalThis.fetch as typeof fetch);

  return {
    getState: () => state,
    ingest(events) {
      state = applyEvents(state, events);
      return state;
    },
    setConnected(connected) {
      state = { ...state, connected: !!connected };
      return state;
    },
    async reconnect() {
      const url = `${opts.brokerUrl.replace(/\/+$/, '')}/sessions/${encodeURIComponent(opts.sessionId)}/replay?cursor=${resumeCursor(state)}`;
      const res = await doFetch(url, { headers: { Authorization: `Bearer ${opts.token}` } });
      if (res && (res as Response).status === 401) {
        throw new AuthRequiredError('broker rejected the session token');
      }
      const body = await (res as Response).json();
      state = applyEvents({ ...state, connected: true }, (body?.events ?? []) as SessionEvent[]);
      return state;
    },
    page(offset = 0, limit = 200) {
      return pageOutput(state, offset, limit);
    },
    proof() {
      return projectVerificationSteps(state);
    },
  };
}
