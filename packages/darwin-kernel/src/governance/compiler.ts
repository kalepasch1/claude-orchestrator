/**
 * NL Constitution Compiler (improvement #1) — author policy ONCE, in plain
 * English, for the whole portfolio. Generalized from Tomorrow's
 * constitutionCompiler so every product compiles against the SAME deterministic
 * pattern set + the SAME locked-dimension guardrails.
 *
 * Deterministic by design: 10 regex patterns cover the common policy shapes.
 * Lines that don't match are returned as `unmapped` so a caller can route them to
 * an LLM fallback (the hook is documented, not hard-wired — keeps the kernel
 * dependency-free and the core behavior reproducible/testable).
 *
 * LOCKED DIMENSIONS: a compiled rule can never loosen a product non-negotiable.
 * If a line tries to allow/permit a locked action, it is rejected (kept as a
 * `rejected` line) — fail-closed.
 */
import type { Constitution, ConstitutionRule } from './constitution.ts';
import type { ProductId } from '../types.ts';

export interface CompileResult {
  constitution: Constitution;
  rules: ConstitutionRule[];
  unmapped: string[]; // route these to an LLM fallback if desired
  rejected: { line: string; reason: string }[];
}

interface Pattern {
  re: RegExp;
  build: (m: RegExpMatchArray, idx: number) => ConstitutionRule | null;
}

function num(s: string): number {
  // handles "1,000,000", "$2.5m", "250k", "10 million"
  const cleaned = s.replace(/[$,\s]/g, '').toLowerCase();
  const mult = /m(illion)?$/.test(cleaned) ? 1_000_000 : /k$/.test(cleaned) ? 1_000 : /b(illion)?$/.test(cleaned) ? 1_000_000_000 : 1;
  const base = parseFloat(cleaned.replace(/(million|billion|m|k|b)$/g, ''));
  return Math.round(base * mult);
}

function slug(s: string): string {
  return s.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

const PATTERNS: Pattern[] = [
  // "escalate any action above $1,000,000" / "notify above 250k"
  {
    re: /\b(?:escalate|notify|flag)\b.*\babove\s+\$?([\d.,]+\s*(?:million|billion|[mkb])?)/i,
    build: (m, i) => ({
      id: `c_cap_${i}`,
      text: m[0]!.trim(),
      appliesTo: ['*'],
      when: (a) => (a.amountUsd ?? 0) > num(m[1]!),
      effect: 'escalate',
      priority: 100,
    }),
  },
  // "deny|never|prohibit <action>"  e.g. "never reveal the winner before lock"
  {
    re: /\b(?:deny|never|prohibit|forbid|block)\b\s+(.+)/i,
    build: (m, i) => {
      const verb = slug(m[1]!.replace(/\b(the|a|an|any|all)\b/gi, '')).slice(0, 40);
      if (!verb) return null;
      return {
        id: `c_deny_${i}`,
        text: m[0]!.trim(),
        appliesTo: [verb],
        when: () => true,
        effect: 'deny',
        priority: 200,
      };
    },
  },
  // "allow <action> under $X"
  {
    re: /\ballow\s+(.+?)\s+under\s+\$?([\d.,]+\s*(?:million|billion|[mkb])?)/i,
    build: (m, i) => ({
      id: `c_allow_${i}`,
      text: m[0]!.trim(),
      appliesTo: [slug(m[1]!).slice(0, 40)],
      when: (a) => (a.amountUsd ?? 0) <= num(m[2]!),
      effect: 'allow',
      priority: 50,
    }),
  },
  // "require approval for <action>" => escalate that action type
  {
    re: /\brequire(?:s)?\s+approval\s+(?:for|on|before)\s+(.+)/i,
    build: (m, i) => ({
      id: `c_appr_${i}`,
      text: m[0]!.trim(),
      appliesTo: [slug(m[1]!).slice(0, 40)],
      when: () => true,
      effect: 'escalate',
      priority: 90,
    }),
  },
  // "only counterparties rated A or better" => rating floor on metadata.rating
  {
    re: /\brated\s+([a-d][+-]?)\s+or\s+(?:better|higher|above)/i,
    build: (m, i) => {
      const floor = ratingScore(m[1]!);
      return {
        id: `c_rating_${i}`,
        text: m[0]!.trim(),
        appliesTo: ['*'],
        when: (a) => ratingScore(String(a.metadata?.rating ?? 'D')) < floor,
        effect: 'escalate',
        priority: 80,
      };
    },
  },
];

function ratingScore(r: string): number {
  const order = ['AAA', 'AA', 'A', 'BBB', 'BB', 'B', 'CCC', 'CC', 'C', 'D'];
  const idx = order.indexOf(r.toUpperCase().replace(/[+-]/g, ''));
  return idx === -1 ? 0 : order.length - idx; // higher = better
}

/**
 * Compile plain-English policy text into a Constitution.
 * @param lockedDimensions action types/keywords that may NEVER be allowed by a rule
 */
export function compileConstitution(params: {
  product: ProductId;
  version?: number;
  text: string;
  alwaysEscalate?: string[];
  lockedDimensions?: string[];
}): CompileResult {
  const lines = params.text
    .split(/\n+/)
    .map((l) => l.replace(/^[\s\-*•\d.)]+/, '').trim())
    .filter(Boolean);

  const rules: ConstitutionRule[] = [];
  const unmapped: string[] = [];
  const rejected: { line: string; reason: string }[] = [];
  const locked = (params.lockedDimensions ?? []).map((d) => d.toLowerCase());

  lines.forEach((line, i) => {
    let matched = false;
    for (const p of PATTERNS) {
      const m = line.match(p.re);
      if (!m) continue;
      const r = p.build(m, i);
      if (!r) continue;
      // Guardrail: a rule may never ALLOW a locked dimension.
      if (r.effect === 'allow' && r.appliesTo.some((t) => locked.some((d) => t.includes(d) || d.includes(t)))) {
        rejected.push({ line, reason: 'attempts_to_allow_locked_dimension' });
        matched = true;
        break;
      }
      rules.push(r);
      matched = true;
      break;
    }
    if (!matched) unmapped.push(line);
  });

  const constitution: Constitution = {
    product: params.product,
    version: params.version ?? 1,
    alwaysEscalate: params.alwaysEscalate ?? [],
    rules,
  };
  return { constitution, rules, unmapped, rejected };
}
