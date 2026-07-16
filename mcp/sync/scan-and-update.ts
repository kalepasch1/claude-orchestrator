#!/usr/bin/env node
/**
 * Live Sync — Scan source apps for changes, update MCP tool definitions.
 * Core apps get change detection + logging. Non-core apps get full auto-regeneration.
 *
 * Usage: tsx sync/scan-and-update.ts [--force] [--app=appId]
 */

import { readdir, readFile, writeFile, mkdir } from 'fs/promises';
import { join, relative } from 'path';
import { createHash } from 'crypto';
import { APP_SOURCES } from '../config.js';

interface SyncManifest {
  appId: string;
  lastSync: string;
  directoryHashes: Record<string, string>;
  detectedChanges: ChangeRecord[];
}

interface ChangeRecord {
  timestamp: string;
  filesChanged: string[];
  type: 'api-route-added' | 'api-route-modified' | 'api-route-removed' | 'engine-added' | 'engine-modified';
  description: string;
  acknowledged: boolean;
}

const CORE_APPS = new Set(['apparently', 'pareto', 'smarter', 'tomorrow', 'orchestrator']);
const MANIFEST_DIR = join(process.cwd(), '.sync-manifests');

async function walkDir(dir: string, callback: (filePath: string) => Promise<void>) {
  const entries = await readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === '.git') continue;
      await walkDir(fullPath, callback);
    } else {
      await callback(fullPath);
    }
  }
}

async function hashDirectory(dirPath: string): Promise<string> {
  const hash = createHash('sha256');
  try {
    await walkDir(dirPath, async (fp) => {
      if (fp.endsWith('.ts') || fp.endsWith('.js') || fp.endsWith('.mjs')) {
        hash.update(`${relative(dirPath, fp)}:${await readFile(fp, 'utf-8')}`);
      }
    });
  } catch { return 'not-found'; }
  return hash.digest('hex');
}

async function loadManifest(appId: string): Promise<SyncManifest | null> {
  try { return JSON.parse(await readFile(join(MANIFEST_DIR, `${appId}.json`), 'utf-8')); }
  catch { return null; }
}

async function saveManifest(m: SyncManifest) {
  await mkdir(MANIFEST_DIR, { recursive: true });
  await writeFile(join(MANIFEST_DIR, `${m.appId}.json`), JSON.stringify(m, null, 2));
}

async function buildHashes(repoPath: string): Promise<Record<string, string>> {
  const h: Record<string, string> = {};
  for (const key of ['server/api', 'server/utils', 'server/engines']) {
    h[key] = await hashDirectory(join(repoPath, ...key.split('/')));
    try {
      await walkDir(join(repoPath, ...key.split('/')), async (fp) => {
        if (fp.endsWith('.ts') || fp.endsWith('.js')) {
          h[`file:${relative(repoPath, fp)}`] = createHash('sha256').update(await readFile(fp, 'utf-8')).digest('hex');
        }
      });
    } catch { /* ok */ }
  }
  return h;
}

async function syncApp(appId: string, force: boolean) {
  const cfg = APP_SOURCES[appId];
  if (!cfg?.repoPath) { console.error(`No repoPath for ${appId}`); return; }

  console.error(`\nSyncing ${appId} from ${cfg.repoPath}...`);
  const prev = force ? null : await loadManifest(appId);
  const curHashes = await buildHashes(cfg.repoPath);
  const prevHashes = prev?.directoryHashes || {};

  const apiChanged = prevHashes['server/api'] !== curHashes['server/api'];
  const engChanged = prevHashes['server/utils'] !== curHashes['server/utils'] || prevHashes['server/engines'] !== curHashes['server/engines'];

  if (!apiChanged && !engChanged && !force) { console.error(`  No changes for ${appId}`); return; }

  const changes: ChangeRecord[] = [];
  const ts = new Date().toISOString();

  if (CORE_APPS.has(appId)) {
    console.error(`  [core] Logging changes for manual review`);
    // Detect new/modified files
    for (const [key, hash] of Object.entries(curHashes)) {
      if (!key.startsWith('file:')) continue;
      if (!prevHashes[key]) {
        const type = key.includes('server/api') ? 'api-route-added' as const : 'engine-added' as const;
        changes.push({ timestamp: ts, filesChanged: [key.replace('file:', '')], type, description: `New: ${key.replace('file:', '')}`, acknowledged: false });
      } else if (prevHashes[key] !== hash) {
        changes.push({ timestamp: ts, filesChanged: [key.replace('file:', '')], type: 'api-route-modified', description: `Modified: ${key.replace('file:', '')}`, acknowledged: false });
      }
    }
    if (changes.length > 0) {
      console.error(`  ${changes.length} change(s) detected`);
      changes.forEach((c) => console.error(`    ${c.type}: ${c.filesChanged[0]}`));
    }
  } else {
    console.error(`  [non-core] Auto-regenerating...`);
    const { execSync } = await import('child_process');
    try {
      execSync(`tsx generator/auto-mcp.ts --app-name=${appId} --repo=${cfg.repoPath}`, { cwd: process.cwd(), stdio: 'inherit' });
    } catch (e) { console.error(`  Regen failed: ${e}`); }
  }

  await saveManifest({
    appId, lastSync: ts, directoryHashes: curHashes,
    detectedChanges: [...(prev?.detectedChanges || []), ...changes],
  });
}

async function main() {
  const args = process.argv.slice(2);
  const force = args.includes('--force');
  const appFlag = args.find((a) => a.startsWith('--app='));
  const target = appFlag?.split('=')[1];

  console.error(`HereTomorrow MCP Live Sync — force=${force}, target=${target || 'all'}`);
  const apps = target ? [target] : Object.keys(APP_SOURCES).filter((id) => APP_SOURCES[id].repoPath);
  for (const id of apps) await syncApp(id, force);
  console.error('\nSync complete.');
}

main().catch((e) => { console.error('Sync error:', e); process.exit(1); });
