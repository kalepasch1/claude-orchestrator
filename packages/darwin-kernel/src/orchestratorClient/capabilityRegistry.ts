/**
 * Capability registry client — the contract layer that lets a process built in
 * ONE product be published once and instantiated by ANY other (opportunity #2).
 * Mirrors the orchestrator's capability-registry primitive.
 *
 * A Capability is a versioned, privacy-scrubbed contract: inputs, outputs, and a
 * stable id. Products publish capabilities (e.g. tomorrow:war_room_pipeline,
 * pareto:monte_carlo, smarter:obligation_extraction, galop:kyc_geo_gate) and
 * other products discover + instantiate them without copying code.
 *
 * Transport is injected (Supabase REST, HTTP, in-memory) so this stays portable.
 */
import { contentId } from '../crypto/hash.ts';
import type { ProductId } from '../types.ts';

export interface CapabilitySpec {
  id: string; // contentId('cap', {name,version})
  name: string; // e.g. 'monte_carlo'
  owner: ProductId; // who published it
  version: string; // semver
  description: string;
  /** JSON-schema-ish input/output contracts (kept as opaque records here) */
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  /** semantic tags for discovery (feeds pgvector search on the server) */
  tags: string[];
  /** invocation endpoint the owner exposes (HTTP path or queue topic) */
  endpoint: string;
}

export interface CapabilityTransport {
  publish(spec: CapabilitySpec): Promise<void>;
  /** keyword/tag search; server may upgrade this to semantic (pgvector) */
  search(query: string, tags?: string[]): Promise<CapabilitySpec[]>;
  get(id: string): Promise<CapabilitySpec | null>;
  /** invoke a published capability and return its output */
  invoke(id: string, input: Record<string, unknown>): Promise<unknown>;
}

export function defineCapability(params: Omit<CapabilitySpec, 'id'>): CapabilitySpec {
  const id = contentId('cap', { name: params.name, version: params.version, owner: params.owner });
  return { id, ...params };
}

export class CapabilityRegistry {
  private readonly transport: CapabilityTransport;
  constructor(transport: CapabilityTransport) {
    this.transport = transport;
  }

  publish(spec: CapabilitySpec): Promise<void> {
    return this.transport.publish(spec);
  }

  discover(query: string, tags?: string[]): Promise<CapabilitySpec[]> {
    return this.transport.search(query, tags);
  }

  async instantiate(id: string, input: Record<string, unknown>): Promise<unknown> {
    const spec = await this.transport.get(id);
    if (!spec) throw new Error(`capability_not_found:${id}`);
    return this.transport.invoke(id, input);
  }
}

/** In-memory transport for tests + single-process composition. */
export function memoryTransport(
  handlers: Record<string, (input: Record<string, unknown>) => unknown> = {},
): CapabilityTransport {
  const store = new Map<string, CapabilitySpec>();
  return {
    async publish(spec) {
      store.set(spec.id, spec);
    },
    async search(query, tags) {
      const q = query.toLowerCase();
      return [...store.values()].filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.description.toLowerCase().includes(q) ||
          (tags ?? []).some((t) => s.tags.includes(t)),
      );
    },
    async get(id) {
      return store.get(id) ?? null;
    },
    async invoke(id, input) {
      const h = handlers[id];
      if (!h) throw new Error(`no_handler:${id}`);
      return h(input);
    },
  };
}
