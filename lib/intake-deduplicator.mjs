/**
 * intake-deduplicator.mjs — Catches duplicate intake files before they enter the queue
 *
 * Compares a new intake file against already-processed intakes and open tasks
 * using content similarity (Jaccard token overlap + structural fingerprinting).
 *
 * Usage:
 *   import { dedupeCheck } from './intake-deduplicator.mjs';
 *   const result = dedupeCheck(newFilePath, './intake/processed', './tasks/open');
 *   if (result.action === 'block') reject(result);
 */

import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { join, basename } from 'node:path';

const BLOCK_THRESHOLD = 0.85;   // ≥85% similarity → block (near-duplicate)
const WARN_THRESHOLD  = 0.60;   // ≥60% similarity → warn (possible duplicate)

// ── tokenization ─────────────────────────────────────────────────────────────

function tokenize(text) {
  return new Set(
    text
      .toLowerCase()
      .replace(/[^a-z0-9\s_-]/g, ' ')
      .split(/\s+/)
      .filter(t => t.length > 2)
  );
}

function jaccardSimilarity(a, b) {
  if (a.size === 0 && b.size === 0) return 1;
  if (a.size === 0 || b.size === 0) return 0;
  let intersection = 0;
  for (const token of a) {
    if (b.has(token)) intersection++;
  }
  return intersection / (a.size + b.size - intersection);
}

// ── structural fingerprint ───────────────────────────────────────────────────

function extractFingerprint(content) {
  const lines = content.split('\n');
  const slug = (content.match(/^slug:\s*(.+)$/m) ?? [])[1]?.trim() ?? '';
  const title = (content.match(/^title:\s*(.+)$/m) ?? [])[1]?.trim() ?? '';
  const project = (content.match(/^project:\s*(.+)$/m) ?? [])[1]?.trim() ?? '';
  const proof = (content.match(/^proof:\s*(.+)$/m) ?? [])[1]?.trim() ?? '';
  return { slug, title, project, proof, lineCount: lines.length };
}

function fingerprintMatch(a, b) {
  // Exact slug match is always a duplicate
  if (a.slug && b.slug && a.slug === b.slug) return 1.0;
  // Same title is very likely a duplicate
  if (a.title && b.title && a.title.toLowerCase() === b.title.toLowerCase()) return 0.95;
  return 0;
}

// ── file scanning ────────────────────────────────────────────────────────────

function scanDir(dir) {
  if (!existsSync(dir)) return [];
  const entries = [];
  try {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      try {
        const stat = statSync(p);
        if (stat.isFile() && (name.endsWith('.md') || name.endsWith('.txt') || name.endsWith('.yaml'))) {
          const content = readFileSync(p, 'utf-8');
          entries.push({ path: p, name, content, tokens: tokenize(content), fingerprint: extractFingerprint(content) });
        }
      } catch { /* skip unreadable files */ }
    }
  } catch { /* skip unreadable dirs */ }
  return entries;
}

// ── main API ─────────────────────────────────────────────────────────────────

/**
 * @param {string} newFilePath - Path to the new intake file
 * @param {...string} searchDirs - Directories to scan for existing files
 * @returns {{ action: 'block'|'warn'|'pass', similarity: number, matchedFile: string|null, reason: string }}
 */
export function dedupeCheck(newFilePath, ...searchDirs) {
  if (!existsSync(newFilePath)) {
    return { action: 'pass', similarity: 0, matchedFile: null, reason: 'File does not exist' };
  }

  const newContent = readFileSync(newFilePath, 'utf-8');
  const newTokens = tokenize(newContent);
  const newFp = extractFingerprint(newContent);

  let highestSim = 0;
  let bestMatch = null;
  let matchReason = '';

  for (const dir of searchDirs) {
    const existing = scanDir(dir);
    for (const entry of existing) {
      // Skip self
      if (entry.path === newFilePath) continue;

      // Check structural fingerprint first (fast path)
      const fpScore = fingerprintMatch(newFp, entry.fingerprint);
      if (fpScore >= BLOCK_THRESHOLD) {
        return {
          action: 'block',
          similarity: fpScore,
          matchedFile: entry.path,
          reason: `Structural duplicate: slug/title match with ${entry.name}`,
        };
      }

      // Token-level similarity
      const sim = jaccardSimilarity(newTokens, entry.tokens);
      if (sim > highestSim) {
        highestSim = sim;
        bestMatch = entry.path;
        matchReason = `${(sim * 100).toFixed(1)}% token overlap with ${entry.name}`;
      }
    }
  }

  if (highestSim >= BLOCK_THRESHOLD) {
    return { action: 'block', similarity: highestSim, matchedFile: bestMatch, reason: matchReason };
  }
  if (highestSim >= WARN_THRESHOLD) {
    return { action: 'warn', similarity: highestSim, matchedFile: bestMatch, reason: matchReason };
  }
  return { action: 'pass', similarity: highestSim, matchedFile: bestMatch, reason: 'No significant duplicates found' };
}

export default { dedupeCheck };
