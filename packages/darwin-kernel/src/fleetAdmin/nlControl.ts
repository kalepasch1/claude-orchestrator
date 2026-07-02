/**
 * Natural-language control plane — govern the whole fleet in English. Bear types
 * "stop auto-refunding anyone who signed up this week"; it is normalized into a policy
 * line, compiled by the kernel's deterministic constitution compiler into an enforceable
 * rule, merged onto the fleet admin constitution, and (optionally) dry-run against history
 * via the digital twin so he sees the diff before it applies. This is what makes the plane
 * usable across 9+ apps without touching code. Pure + zero-dep.
 */
import { compileConstitution } from '../governance/compiler.ts';
import type { Constitution } from '../governance/constitution.ts';
import { fleetAdminConstitution, FLEET_ADMIN_LOCKED_DIMENSIONS } from './constitution.ts';
import { dryRunChange, type TwinResult } from './twin.ts';
import type { AdminAction } from './types.ts';
import type { ResolvedCase } from './precedent.ts';

/** Rewrite common admin phrasings into lines the constitution compiler understands. */
export function preprocessAdminNl(text: string): string[] {
  return text
    .split(/\n+/)
    .map((raw) => {
      let l = raw.trim();
      if (!l) return '';
      // "stop auto-refunding" / "stop auto refunding" / "stop auto-approving X" → require approval
      l = l.replace(/\bstop\s+auto[-\s]?(\w+?)(?:ing|s)?\b/i, (_m, verb) => `require approval for ${verb}`);
      // "always ask before X" / "always review X" → require approval for X
      l = l.replace(/\balways\s+(?:ask\s+before|review|check)\s+/i, 'require approval for ');
      // "auto <verb> under $X" → allow <verb> under $X
      l = l.replace(/\bauto[-\s]?(\w+)\s+under\s+\$?/i, 'allow $1 under $');
      // "hold|pause <verb>" → require approval for <verb>
      l = l.replace(/\b(?:hold|pause)\s+(\w+)/i, 'require approval for $1');
      return l;
    })
    .filter(Boolean);
}

export interface NlCompileResult {
  /** the merged constitution (base fleet law + the new compiled rules) */
  constitution: Constitution;
  addedRuleCount: number;
  unmapped: string[];
  rejected: { line: string; reason: string }[];
  normalizedLines: string[];
  dryRun?: TwinResult;
}

/**
 * Compile English control text into a merged constitution, and (if history is supplied)
 * dry-run it against past actions so the operator sees exactly what would change.
 */
export function compileNlControl(params: {
  text: string;
  history?: AdminAction[];
  outcomes?: Record<string, ResolvedCase['outcome']>;
}): NlCompileResult {
  const base = fleetAdminConstitution();
  const normalizedLines = preprocessAdminNl(params.text);
  const compiled = compileConstitution({
    product: 'orchestrator',
    version: base.version + 1,
    text: normalizedLines.join('\n'),
    alwaysEscalate: base.alwaysEscalate,
    lockedDimensions: [...FLEET_ADMIN_LOCKED_DIMENSIONS],
  });

  const merged: Constitution = {
    product: 'orchestrator',
    version: base.version + 1,
    alwaysEscalate: base.alwaysEscalate,
    rules: [...base.rules, ...compiled.rules],
  };

  let dryRun: TwinResult | undefined;
  if (params.history?.length) {
    dryRun = dryRunChange({ actions: params.history, before: { constitution: base }, after: { constitution: merged }, outcomes: params.outcomes });
  }

  return {
    constitution: merged,
    addedRuleCount: compiled.rules.length,
    unmapped: compiled.unmapped,
    rejected: compiled.rejected,
    normalizedLines,
    dryRun,
  };
}
