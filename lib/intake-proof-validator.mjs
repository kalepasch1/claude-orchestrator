/**
 * intake-proof-validator.mjs — Validates intake file proof commands
 *
 * Rejects intake files that use scoped `npx vitest run <file>` proofs
 * instead of the full test suite. Prevents DOA tasks from entering the queue.
 *
 * Usage:
 *   import { validateIntakeProofs } from './intake-proof-validator.mjs';
 *   const result = validateIntakeProofs(fileContent);
 *   if (!result.pass) reject(result);
 */

// Patterns that indicate a scoped (insufficient) proof command
const SCOPED_PROOF_PATTERNS = [
  // npx vitest run <specific-file>
  /npx\s+vitest\s+run\s+\S+\.(ts|js|mjs|tsx|jsx)\b/gi,
  // npx vitest <specific-file> (without 'run')
  /npx\s+vitest\s+(?!run\b)\S+\.(ts|js|mjs|tsx|jsx)\b/gi,
  // vitest run <file> (without npx)
  /(?<!\w)vitest\s+run\s+\S+\.(ts|js|mjs|tsx|jsx)\b/gi,
  // jest <file>
  /(?<!\w)jest\s+\S+\.(ts|js|mjs|tsx|jsx)\b/gi,
  // --testPathPattern or -t with specific files
  /--testPathPattern[=\s]+\S+/gi,
  // vitest with --dir pointing to single test
  /vitest\s+.*--dir\s+\S+/gi,
];

// Patterns that indicate a full-suite proof (acceptable)
const FULL_SUITE_PATTERNS = [
  /npx\s+vitest\s+run\s*$/gm,         // bare `npx vitest run`
  /npm\s+(?:run\s+)?test\b/gi,         // npm test / npm run test
  /npx\s+vitest\s*$/gm,               // bare `npx vitest`
  /nuxi\s+build\b/gi,                  // full build
  /npm\s+run\s+build\b/gi,            // npm run build
  /tsc\s+--noEmit\b/gi,               // type check
  /eslint\s+\.\b/gi,                   // full lint
];

/**
 * @param {string} content - Raw content of an intake file
 * @returns {{ pass: boolean, errors: string[], warnings: string[], proofCommands: string[] }}
 */
export function validateIntakeProofs(content) {
  if (!content || typeof content !== 'string') {
    return { pass: false, errors: ['Empty or invalid intake content'], warnings: [], proofCommands: [] };
  }

  const errors = [];
  const warnings = [];
  const proofCommands = [];

  // Extract proof command blocks
  // Format 1: `proof: <command>` (canonical intake format)
  const proofLineMatches = content.match(/^proof:\s*(.+)$/gm) ?? [];
  for (const match of proofLineMatches) {
    proofCommands.push(match.replace(/^proof:\s*/, '').trim());
  }

  // Format 2: fenced code blocks after "proof" or "verification" headers
  const codeBlockRegex = /(?:proof|verification|test)[:\s]*\n```(?:bash|sh)?\n([\s\S]*?)```/gi;
  let codeMatch;
  while ((codeMatch = codeBlockRegex.exec(content)) !== null) {
    const commands = codeMatch[1].trim().split('\n').filter(l => l.trim());
    proofCommands.push(...commands);
  }

  if (proofCommands.length === 0) {
    warnings.push('No proof commands found in intake file — manual review recommended');
    return { pass: true, errors, warnings, proofCommands };
  }

  // Check each proof command
  for (const cmd of proofCommands) {
    let isScoped = false;
    let isFull = false;

    for (const pattern of FULL_SUITE_PATTERNS) {
      pattern.lastIndex = 0;
      if (pattern.test(cmd)) {
        isFull = true;
        break;
      }
    }

    if (!isFull) {
      for (const pattern of SCOPED_PROOF_PATTERNS) {
        pattern.lastIndex = 0;
        if (pattern.test(cmd)) {
          isScoped = true;
          break;
        }
      }
    }

    if (isScoped) {
      errors.push(
        `Scoped proof detected: "${cmd}" — ` +
        'Proof must run the full test suite (e.g., `npx vitest run` or `npm test`), ' +
        'not a single file. Scoped proofs mask regressions elsewhere.'
      );
    }
  }

  return {
    pass: errors.length === 0,
    errors,
    warnings,
    proofCommands,
  };
}

export default { validateIntakeProofs };
