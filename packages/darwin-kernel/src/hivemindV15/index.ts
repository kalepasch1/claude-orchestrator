/** Portable V15 runtime used by every fleet application.
 *
 * The kernel provides safe, dependency-free mechanisms and observed metrics;
 * the 50x–500x figures in the proposal remain benchmark targets, not promises.
 */

export const HIVEMIND_APPS = [
  'galop', 'tomorrow', 'smarter', 'pareto', 'apparently',
  'orchestrator', 'vigil', 'hisanta', 'predictions', 'trojun',
] as const;
export type HivemindApp = (typeof HIVEMIND_APPS)[number];
export type Path<T, R> = (query: T) => R | Promise<R>;

const aliases: Record<string, HivemindApp> = {
  beethoven: 'orchestrator', 'claude-orchestrator': 'orchestrator', racefeed: 'galop',
  'pareto-2080': 'pareto', '2080': 'pareto', 'santas-secret-workshop': 'hisanta',
  illuminati: 'trojun',
};

export function canonicalApp(value: string): HivemindApp {
  const normalized = value.trim().toLowerCase();
  return aliases[normalized] ?? (HIVEMIND_APPS.includes(normalized as HivemindApp)
    ? normalized as HivemindApp : 'orchestrator');
}

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value as Record<string, unknown>)
    .sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k}:${stable(v)}`).join(',')}}`;
  return JSON.stringify(value);
}

function hash(value: string): string {
  // FNV-1a: deterministic/non-cryptographic; keys are routing hints, not security tokens.
  let h = 0x811c9dc5;
  for (let i = 0; i < value.length; i++) { h ^= value.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return (h >>> 0).toString(16).padStart(8, '0');
}

export function structuralPattern(value: unknown): string {
  const shape = value && typeof value === 'object' && !Array.isArray(value)
    ? Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => [k, Array.isArray(v) ? 'array' : typeof v])
    : typeof value;
  return hash(stable(shape));
}

export interface FractalCoefficient { scale: number; index: number; value: number }

export function fractalKey(signal: readonly number[], scales = 6, keep = 4): FractalCoefficient[] {
  let current = [...signal]; const result: FractalCoefficient[] = [];
  for (let scale = 0; scale < scales && current.length > 1; scale++) {
    const approximation: number[] = []; const detail: FractalCoefficient[] = [];
    for (let i = 0; i + 1 < current.length; i += 2) {
      approximation.push((current[i]! + current[i + 1]!) / 2);
      detail.push({ scale, index: i / 2, value: (current[i]! - current[i + 1]!) / 2 });
    }
    result.push(...detail.sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, keep));
    current = approximation;
  }
  return result;
}

function vector(value: unknown, dimensions = 64): number[] {
  if (Array.isArray(value) && value.every(v => typeof v === 'number'))
    return [...value, ...Array(dimensions).fill(0)].slice(0, dimensions) as number[];
  const out = Array<number>(dimensions).fill(0); const text = stable(value);
  for (let i = 0; i < text.length; i++) out[parseInt(hash(text.slice(i, i + 2)), 16) % dimensions]! += i % 2 ? -1 : 1;
  return out;
}

interface MemoryEntry { coefficients: FractalCoefficient[]; contentKey: string; value: unknown; at: number }
export interface MemoryHit<T> { value: T; similarity: number; exact: boolean }

export class FractalHolographicMemory {
  private readonly entries = new Map<string, MemoryEntry>();
  readonly capacity: number;
  constructor(capacity = 4096) { this.capacity = capacity; }

  put(signal: unknown, value: unknown): void {
    const coefficients = fractalKey(vector(signal)); const key = hash(stable(coefficients));
    this.entries.delete(key); this.entries.set(key, { coefficients, contentKey: hash(stable(signal)), value, at: Date.now() });
    while (this.entries.size > this.capacity) this.entries.delete(this.entries.keys().next().value!);
  }

  get<T>(signal: unknown): MemoryHit<T> | undefined {
    const coefficients = fractalKey(vector(signal)); const exactKey = hash(stable(signal));
    const direct = this.entries.get(hash(stable(coefficients)));
    if (!direct) return undefined;
    const a = new Map(coefficients.map(c => [`${c.scale}:${c.index}`, c.value]));
    const b = new Map(direct.coefficients.map(c => [`${c.scale}:${c.index}`, c.value]));
    const keys = new Set([...a.keys(), ...b.keys()]);
    let dot = 0, na = 0, nb = 0;
    for (const key of keys) { const x = a.get(key) ?? 0, y = b.get(key) ?? 0; dot += x * y; na += x * x; nb += y * y; }
    return { value: direct.value as T, similarity: dot / (Math.sqrt(na * nb) || 1), exact: direct.contentKey === exactKey };
  }

  consolidate(): number {
    const cutoff = Date.now() - 86_400_000 * 30; let removed = 0;
    for (const [key, entry] of this.entries) if (entry.at < cutoff) { this.entries.delete(key); removed++; }
    return removed;
  }
}

/** Fixed-size typed-array ring. `publish` returns a view into shared backing
 * storage, so same-process consumers perform no serialization or copy. */
export class ZeroCopyHolographicRing {
  private readonly storage: Float64Array; private cursor = 0;
  readonly slots: number; readonly width: number;
  constructor(slots = 128, width = 24) { this.slots = slots; this.width = width; this.storage = new Float64Array(slots * width); }
  publish(coefficients: readonly FractalCoefficient[]): Float64Array {
    const slot = this.cursor++ % this.slots; const view = this.storage.subarray(slot * this.width, (slot + 1) * this.width);
    view.fill(0); coefficients.slice(0, Math.floor(this.width / 3)).forEach((c, i) => {
      view[i * 3] = c.scale; view[i * 3 + 1] = c.index; view[i * 3 + 2] = c.value;
    });
    return view;
  }
}

export class FractalCausalGraph {
  private readonly series = new Map<string, number[]>();
  readonly scales: readonly number[]; readonly history: number;
  constructor(scales: readonly number[] = [1, 4, 16, 64], history = 512) { this.scales = scales; this.history = history; }
  observe(values: Record<string, number>): void {
    for (const [name, value] of Object.entries(values)) {
      const points = this.series.get(name) ?? []; points.push(value);
      if (points.length > this.history) points.shift(); this.series.set(name, points);
    }
  }
  predict(target: string, drivers: readonly string[]): { prediction: number; causes: Array<{ driver: string; scale: number; correlation: number }> } {
    const ys = this.series.get(target) ?? []; const causes: Array<{ driver: string; scale: number; correlation: number }> = [];
    for (const driver of drivers) for (const scale of this.scales) {
      const values = this.series.get(driver) ?? []; const n = Math.min(values.length, ys.length);
      if (n <= scale + 2) continue;
      const xs = values.slice(-n, -scale), shifted = ys.slice(-n + scale);
      const mx = xs.reduce((a, b) => a + b, 0) / xs.length, my = shifted.reduce((a, b) => a + b, 0) / shifted.length;
      let dot = 0, nx = 0, ny = 0;
      xs.forEach((x, i) => { const dx = x - mx, dy = shifted[i]! - my; dot += dx * dy; nx += dx * dx; ny += dy * dy; });
      causes.push({ driver, scale, correlation: dot / (Math.sqrt(nx * ny) || 1) });
    }
    causes.sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation));
    let delta = 0;
    for (const cause of causes.slice(0, 3)) { const d = this.series.get(cause.driver)!; delta += cause.correlation * (d.at(-1)! - d.at(-1 - cause.scale)!) / 3; }
    return { prediction: (ys.at(-1) ?? 0) + delta, causes: causes.slice(0, 10) };
  }
}

export class MetabolicSpikeBudget {
  private states = new Map<string, { load: number; awake: boolean; at: number }>();
  readonly threshold: number; readonly decay: number;
  constructor(threshold = .6, decay = .85) { this.threshold = threshold; this.decay = decay; }
  signal(module: string, significance: number, demand = 1): number {
    const previous = this.states.get(module) ?? { load: 0, awake: false, at: 0 };
    const load = this.decay * previous.load + (1 - this.decay) * Math.max(0, demand);
    const awake = significance >= this.threshold && load >= .05;
    this.states.set(module, { load, awake, at: awake ? Date.now() : previous.at });
    return awake ? Math.min(1, significance * Math.max(.1, load)) : 0;
  }
  restIdle(milliseconds = 60_000): number {
    let count = 0;
    for (const state of this.states.values()) if (state.awake && Date.now() - state.at > milliseconds) { state.awake = false; count++; }
    return count;
  }
}

export class ErrorCorrectionCurriculum {
  private rates = new Map<string, number>();
  observe(source: HivemindApp, target: HivemindApp, failed: boolean): number {
    const key = `${source}:${target}:${Math.floor(new Date().getHours() / 4)}`;
    const rate = .2 * Number(failed) + .8 * (this.rates.get(key) ?? 0); this.rates.set(key, rate);
    return rate >= .2 ? 3 : rate >= .05 ? 2 : 1;
  }
}

export class AdversarialAnomalyCurriculum {
  level = 1; private outcomes: boolean[] = [];
  generate(sample: readonly number[], count = 8): number[][] {
    const severity = Math.max(.02, .8 / this.level);
    return Array.from({ length: count }, (_, n) => sample.map((v, i) => i === n % sample.length ? v + severity * (Math.abs(v) + 1) : v));
  }
  record(detected: boolean): number {
    this.outcomes.push(detected); if (this.outcomes.length > 32) this.outcomes.shift();
    if (this.outcomes.length >= 16 && this.outcomes.filter(Boolean).length / this.outcomes.length >= .85) { this.level++; this.outcomes = []; }
    return this.level;
  }
}

interface Cluster<T, R> { node: DistilledTopologyNode<T, R>; lastSeen: number; hits: number }
export class DistilledTopologyNode<T, R> {
  private cache = new Map<string, R>();
  private readonly teacher: Path<T, R>;
  constructor(teacher: Path<T, R>) { this.teacher = teacher; }
  async execute(query: T): Promise<R> {
    const key = hash(stable(query)); if (this.cache.has(key)) return this.cache.get(key)!;
    const value = await this.teacher(query); this.cache.set(key, value); return value;
  }
}

export interface QueryResult<R> { app: HivemindApp; source: 'memory'|'rest'|'compiled'|'speculative'; result?: R; attention: number }

export class HivemindV15 {
  readonly memory = new FractalHolographicMemory(); readonly budget = new MetabolicSpikeBudget();
  readonly ring = new ZeroCopyHolographicRing(); readonly causal = new FractalCausalGraph();
  readonly correction = new ErrorCorrectionCurriculum(); readonly anomalies = new AdversarialAnomalyCurriculum();
  private patterns = new Map<string, number>(); private clusters = new Map<string, Cluster<unknown, unknown>>();
  private pathWins = new Map<string, Map<string, number>>();

  adapter(app: string): HivemindAdapter { return new HivemindAdapter(canonicalApp(app), this); }

  async query<T, R>(app: HivemindApp, query: T, paths: Record<string, Path<T, R>>, significance = 1): Promise<QueryResult<R>> {
    this.ring.publish(fractalKey(vector(query)));
    const hit = this.memory.get<R>(query);
    if (hit?.exact) return { app, source: 'memory', result: hit.value, attention: 0 };
    const attention = this.budget.signal(app, significance); if (!attention) return { app, source: 'rest', attention };
    const pattern = `${app}:${structuralPattern(query)}`; const seen = (this.patterns.get(pattern) ?? 0) + 1; this.patterns.set(pattern, seen);
    let cluster = this.clusters.get(pattern) as Cluster<T, R> | undefined;
    const first = Object.values(paths)[0];
    if (!cluster && seen >= 3 && first) { cluster = { node: new DistilledTopologyNode(first), lastSeen: Date.now(), hits: 0 }; this.clusters.set(pattern, cluster as Cluster<unknown, unknown>); }
    let result: R; let source: QueryResult<R>['source'];
    if (cluster?.hits) { cluster.hits++; cluster.lastSeen = Date.now(); result = await cluster.node.execute(query); source = 'compiled'; }
    else {
      const wins = this.pathWins.get(pattern) ?? new Map<string, number>();
      const selected = Object.entries(paths).sort(([a], [b]) => (wins.get(b) ?? 0) - (wins.get(a) ?? 0)).slice(0, 3);
      if (!selected.length) throw new Error('at least one query path is required');
      const winner = await Promise.any(selected.map(async ([name, path]) => ({ name, value: await path(query) })));
      result = winner.value; wins.set(winner.name, (wins.get(winner.name) ?? 0) + 1); this.pathWins.set(pattern, wins); source = 'speculative';
      if (cluster) cluster.hits++;
    }
    this.memory.put(query, result); return { app, source, result, attention };
  }

  dissolve(ttlMs = 900_000): number {
    let removed = 0; for (const [key, cluster] of this.clusters) if (Date.now() - cluster.lastSeen > ttlMs) { this.clusters.delete(key); removed++; }
    return removed;
  }
}

export class HivemindAdapter {
  readonly app: HivemindApp; private readonly runtime: HivemindV15;
  constructor(app: HivemindApp, runtime: HivemindV15) { this.app = app; this.runtime = runtime; }
  query<T, R>(query: T, paths: Record<string, Path<T, R>>, significance = 1): Promise<QueryResult<R>> {
    return this.runtime.query(this.app, query, paths, significance);
  }
  channelOutcome(target: string, failed: boolean): number { return this.runtime.correction.observe(this.app, canonicalApp(target), failed); }
  anomalyBatch(sample: readonly number[], count = 8): number[][] { return this.runtime.anomalies.generate(sample, count); }
}
