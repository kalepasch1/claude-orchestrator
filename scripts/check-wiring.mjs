#!/usr/bin/env node
/**
 * check-wiring.mjs — Nuxt-aware dead code detector.
 * 
 * Reads optional .wiring.json from the app root for per-app config:
 * {
 *   "framework": "nuxt"|"expo"|"node",
 *   "autoImportDirs": ["server/utils", "composables"],
 *   "logicDirs": ["server/utils", "server/engines", "lib"],
 *   "surfaceDirs": ["server/api", "pages", "components", "app"],
 *   "exceptions": ["moduleToIgnore"]
 * }
 * 
 * Usage: node scripts/check-wiring.mjs --root /path/to/app [--strict] [--json]
 */
import fs from 'fs';
import path from 'path';

const args = process.argv.slice(2);
const root = args.includes('--root') ? args[args.indexOf('--root') + 1] : '.';
const strict = args.includes('--strict');
const jsonOut = args.includes('--json');

const SKIP = new Set(['node_modules', '.nuxt', '.output', 'dist', '_dormant', '.git', '__tests__', '__pycache__']);
const EXTS = new Set(['.ts', '.js', '.mjs', '.vue', '.tsx', '.jsx', '.py']);

// Load .wiring.json config or use defaults
let config = {
  framework: 'nuxt',
  autoImportDirs: ['server/utils', 'server/engines', 'composables'],
  logicDirs: ['server/utils', 'server/engines', 'lib'],
  surfaceDirs: ['server/api', 'pages', 'components', 'app'],
  exceptions: []
};

const configPath = path.join(root, '.wiring.json');
if (fs.existsSync(configPath)) {
  try {
    const custom = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    config = { ...config, ...custom };
  } catch (e) {
    console.error(`Warning: invalid .wiring.json: ${e.message}`);
  }
}

const exceptSet = new Set(config.exceptions);

function walk(dir, collect = []) {
  if (!fs.existsSync(dir)) return collect;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, collect);
    } else {
      const ext = path.extname(entry.name);
      if (EXTS.has(ext) && !entry.name.includes('.test.') && !entry.name.includes('.spec.')) {
        collect.push(full);
      }
    }
  }
  return collect;
}

function basename(fp) {
  const name = path.basename(fp);
  for (const ext of ['.test.ts', '.test.js', '.spec.ts', '.ts', '.js', '.mjs', '.vue', '.tsx', '.jsx', '.py']) {
    if (name.endsWith(ext)) return name.slice(0, -ext.length);
  }
  return name;
}

// Collect logic files
const logicFiles = [];
for (const d of config.logicDirs) {
  logicFiles.push(...walk(path.join(root, d)));
}

// Collect ALL source files for reference checking
const allFiles = [];
const allDirs = [...new Set([...config.logicDirs, ...config.surfaceDirs, 'shared', 'plugins', 'middleware', 'layouts', 'composables', 'store', 'stores', 'hooks'])];
for (const d of allDirs) {
  allFiles.push(...walk(path.join(root, d)));
}

// Read content of all source files
const contentCache = new Map();
for (const f of allFiles) {
  try {
    contentCache.set(f, fs.readFileSync(f, 'utf8').slice(0, 8000));
  } catch {}
}

// Check each logic file
const orphans = [];
const wired = [];

for (const lf of logicFiles) {
  const bn = basename(lf);
  if (bn === 'index' || bn.length <= 2 || exceptSet.has(bn)) continue;
  
  let found = false;
  for (const [sf, content] of contentCache) {
    if (sf === lf) continue;
    if (path.basename(sf).includes('.test.') || path.basename(sf).includes('.spec.')) continue;
    if (content.includes(bn)) {
      found = true;
      break;
    }
  }
  
  if (found) {
    wired.push(path.relative(root, lf));
  } else {
    orphans.push(path.relative(root, lf));
  }
}

// Output
const total = wired.length + orphans.length;

if (jsonOut) {
  console.log(JSON.stringify({ total, wired: wired.length, orphans: orphans.length, orphanList: orphans }, null, 2));
} else {
  console.log(`Total=${total} Wired=${wired.length} Orphans=${orphans.length}`);
  if (orphans.length > 0) {
    console.log('\nOrphans:');
    for (const o of orphans.sort()) {
      console.log(`  ${o}`);
    }
  }
}

if (strict && orphans.length > 0) {
  process.exit(1);
}
