/**
 * The Fleet Admin adapter contract — the ONE interface a product implements to
 * join the control plane. Onboarding a new app = implement `FleetAdminAdapter`
 * (emit events, list proposable actions, execute an approved action). No bespoke
 * integration, no schema negotiation. This is the "accept new projects easily"
 * guarantee: the contract is tiny and stable.
 *
 * The control plane (Orchestrator) is the only caller. It never touches an app's
 * database directly — it goes through the app's adapter, which runs inside that
 * app with that app's own credentials + RLS. That keeps prod credentials out of
 * the code-build runner and keeps each blast radius inside its own app.
 */
import type { ProductId } from '../types.ts';
import type { AdminAction, AdminEvent } from './types.ts';

export interface ExecutionResult {
  ok: boolean;
  /** app-side id/reference for what was done (charge id, ticket id, deploy id, ...) */
  ref?: string;
  /** human summary of the effect, for the receipt + audit log */
  detail: string;
  /** if the action is reversible, an opaque token the plane can pass to `reverse` */
  undoToken?: string;
  error?: string;
}

/**
 * Implemented once per product. All methods are async + fail-safe: an adapter that
 * throws is treated by the plane as a hard failure (the action is NOT marked done).
 */
export interface FleetAdminAdapter {
  readonly product: ProductId;

  /** Pull new admin events since a cursor (poll) OR push via `onEvent` (realtime). */
  pollEvents(sinceIso: string): Promise<AdminEvent[]>;

  /**
   * For an event, return the remediation(s) an agent proposes — each already
   * carrying confidence/reversibility/blastRadius so the plane can run the dial.
   * (In practice a domain swarm fills these in; the adapter is the app-side seam.)
   */
  proposeActions(event: AdminEvent): Promise<AdminAction[]>;

  /** Execute an action the plane has cleared (constitution allow + autonomy auto,
   *  or a human approval). Must be idempotent on `action.id`. */
  execute(action: AdminAction): Promise<ExecutionResult>;

  /** Best-effort reversal for a previously-executed reversible action. */
  reverse?(action: AdminAction, undoToken: string): Promise<ExecutionResult>;

  /** Optional: a health signal the plane surfaces on the runner-health view. */
  health?(): Promise<{ ok: boolean; detail: string }>;
}

/** Registry so the plane can look up the adapter for whichever product emitted an event. */
export class FleetAdapterRegistry {
  private readonly adapters = new Map<ProductId, FleetAdminAdapter>();

  register(adapter: FleetAdminAdapter): void {
    this.adapters.set(adapter.product, adapter);
  }
  get(product: ProductId): FleetAdminAdapter | null {
    return this.adapters.get(product) ?? null;
  }
  list(): FleetAdminAdapter[] {
    return [...this.adapters.values()];
  }
  /** Poll every registered app for new events in parallel; failures are isolated. */
  async pollAll(sinceIso: string): Promise<{ product: ProductId; events: AdminEvent[]; error?: string }[]> {
    return Promise.all(
      this.list().map(async (a) => {
        try {
          return { product: a.product, events: await a.pollEvents(sinceIso) };
        } catch (err) {
          return { product: a.product, events: [], error: String(err) };
        }
      }),
    );
  }
}

/** In-memory adapter for tests + local composition of the whole plane. */
export function memoryAdapter(
  product: ProductId,
  seed: {
    events?: AdminEvent[];
    proposer?: (e: AdminEvent) => AdminAction[];
    executor?: (a: AdminAction) => ExecutionResult;
  } = {},
): FleetAdminAdapter {
  const events = [...(seed.events ?? [])];
  return {
    product,
    async pollEvents(sinceIso) {
      return events.filter((e) => e.at > sinceIso);
    },
    async proposeActions(event) {
      return seed.proposer ? seed.proposer(event) : [];
    },
    async execute(action) {
      return (
        seed.executor?.(action) ?? {
          ok: true,
          ref: `mem_${action.id}`,
          detail: `mock-executed ${action.type}`,
        }
      );
    },
    async health() {
      return { ok: true, detail: `${product} memory adapter` };
    },
  };
}
