/**
 * Generate a tool group from an app's real Nitro routes.
 *
 * package.json has declared `"generate": "tsx generator/auto-mcp.ts"` since the
 * mcp/ package was created; the file never existed. Without it the three groups
 * that did exist were hand-written and the other three apps had none — which is
 * why APP_SOURCES listed six apps and groups/ held three.
 *
 * Groups are generated from the filesystem on purpose. A hand-written tool list
 * describes the API someone remembered; a generated one describes the API that
 * is actually deployed, and regenerating is how it stays true.
 *
 *   npx tsx generator/auto-mcp.ts                 # every app in APP_SOURCES
 *   npx tsx generator/auto-mcp.ts vigil tomorrow  # just these
 *
 * Nitro route conventions honoured:
 *   server/api/a/b.post.ts        -> POST   /api/a/b
 *   server/api/a/index.get.ts     -> GET    /api/a
 *   server/api/a/[id].get.ts      -> GET    /api/a/:id
 *   server/api/a/[...x].ts        -> skipped (catch-all)
 *   server/api/a/_helper.ts       -> skipped (Nitro ignores leading underscore)
 */
import { readdirSync, statSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { join, relative, basename, dirname } from 'node:path';
import { APP_SOURCES } from '../config.js';
import type { AppSource, ToolDefinition } from '../types.js';

/**
 * Routes that exist for machines, not for an agent to call.
 * Calling a webhook or an OAuth callback out of band does nothing useful and
 * can corrupt state, so they never become tools.
 */
const EXCLUDE_SEGMENTS = [
  'webhooks', 'webhook', 'oauth', 'cron', '_fleet-relay', 'callback',
  'health', 'ping', 'sitemap', 'robots', 'og', 'rss', 'feed',
];

const HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete'] as const;
type Method = Uppercase<(typeof HTTP_METHODS)[number]>;

function walk(dir: string, out: string[] = []): string[] {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (entry.endsWith('.ts')) out.push(full);
  }
  return out;
}

interface Route { method: Method; path: string; file: string }

function toRoute(apiRoot: string, file: string): Route | null {
  const rel = relative(apiRoot, file).replace(/\\/g, '/');
  if (rel.split('/').some((s) => s.startsWith('_'))) return null;   // Nitro ignores these
  if (rel.includes('[...')) return null;                            // catch-all
  if (rel.includes('.test.') || rel.includes('.spec.')) return null;

  let stem = rel.replace(/\.ts$/, '');
  let method: Method = 'GET';
  const m = stem.match(/\.(get|post|put|patch|delete)$/);
  if (m) {
    method = m[1].toUpperCase() as Method;
    stem = stem.slice(0, -(m[1].length + 1));
  } else {
    // No method suffix: Nitro accepts any verb. POST is the useful default for
    // an agent, except for an obvious read.
    method = /(^|\/)(index|list|status|summary)$/.test(stem) ? 'GET' : 'POST';
  }
  stem = stem.replace(/(^|\/)index$/, '');
  const path = ('/api/' + stem).replace(/\/+$/, '').replace(/\[(\.\.\.)?([^\]]+)\]/g, ':$2');
  if (EXCLUDE_SEGMENTS.some((seg) => path.split('/').includes(seg))) return null;
  return { method, path, file };
}

/** First sentence of the file's leading block comment, if it has one. */
function describeFrom(file: string): string | null {
  let src: string;
  try { src = readFileSync(file, 'utf8'); } catch { return null; }
  const block = src.match(/^\s*\/\*\*([\s\S]*?)\*\//);
  if (block) {
    const text = block[1].split('\n').map((l) => l.replace(/^\s*\*ded?\s?/, '').replace(/^\s*\*\s?/, '').trim())
      .filter(Boolean).join(' ').trim();
    if (text) return text.split(/(?<=\.)\s/)[0].slice(0, 300);
  }
  const line = src.match(/^\s*\/\/\s*(.+)$/m);
  return line ? line[1].trim().slice(0, 300) : null;
}

function toolName(appId: string, route: Route): string {
  const parts = route.path.replace(/^\/api\//, '').split('/')
    .filter(Boolean).map((s: string) => s.replace(/^:/, 'by_').replace(/-/g, '_'));
  const verb = route.method === 'GET' ? 'get' : route.method.toLowerCase();
  const tail = parts.join('.');
  return `${appId}.${tail}`.replace(/\.$/, '') + (route.method === 'GET' ? '' : `.${verb}`);
}

/** Path params become required string inputs; everything else is free-form. */
function inputSchemaFor(route: Route): ToolDefinition['inputSchema'] {
  const params = [...route.path.matchAll(/:([A-Za-z0-9_]+)/g)].map((m) => m[1]);
  const properties: Record<string, any> = {};
  for (const p of params) properties[p] = { type: 'string', description: `Path parameter '${p}'` };
  if (route.method !== 'GET' && route.method !== 'DELETE') {
    properties.body = { type: 'object', description: 'Request body forwarded to the endpoint.' };
  }
  return { type: 'object', properties, required: params.length ? params : undefined };
}

function costFor(route: Route): ToolDefinition['costProfile'] {
  if (/\b(ai|copilot|draft|analy[sz]e|generate|research|dossier|synthesi)/i.test(route.path)) return 'ai-heavy';
  return route.method === 'GET' ? 'pure-logic' : 'hybrid';
}

function generate(app: AppSource): { defs: ToolDefinition[]; scanned: number } {
  const apiRoot = join(app.repoPath, app.apiScanGlob.split('/**')[0]);
  const files = walk(apiRoot);
  const seen = new Set<string>();
  const defs: ToolDefinition[] = [];

  for (const file of files.sort()) {
    const route = toRoute(apiRoot, file);
    if (!route) continue;
    const name = toolName(app.id, route);
    if (seen.has(name)) continue;
    seen.add(name);
    const described = describeFrom(route.file);
    defs.push({
      name,
      description: described || `${route.method} ${route.path} on ${app.label}.`,
      inputSchema: inputSchemaFor(route),
      proxyTo: { method: route.method, path: route.path },
      costProfile: costFor(route),
      pricingCents: costFor(route) === 'ai-heavy' ? 2000 : route.method === 'GET' ? 0 : 500,
    });
  }
  return { defs, scanned: files.length };
}

function emit(app: AppSource, defs: ToolDefinition[]): string {
  const constName = `${app.id.toUpperCase()}_TOOLS`;
  const body = defs.map((d) => '  ' + JSON.stringify(d) + ',').join('\n');
  // The scan glob ends in `**/*.ts`, and an unescaped `*/` inside a block
  // comment closes it — which produced six unparseable files on the first run.
  const globSafe = app.apiScanGlob.replace(/\*\//g, '*\u200b/');
  return `/**
 * Tool definitions for ${app.label} — ${app.category}.
 *
 * GENERATED by generator/auto-mcp.ts from the routes under
 * ${app.repoPath}/${globSafe}
 * Regenerate with \`npm run generate\` after adding or moving a route.
 * Hand edits here are lost on the next run — change the route, or the
 * generator, instead.
 *
 * ${defs.length} tools.
 */
import type { ToolDefinition } from '../types.js';

export const ${constName}: ToolDefinition[] = [
${body}
];
`;
}

const wanted = process.argv.slice(2);
const ids = wanted.length ? wanted : Object.keys(APP_SOURCES);
let total = 0;

for (const id of ids) {
  const app = APP_SOURCES[id];
  if (!app) { console.error(`unknown app '${id}'`); process.exitCode = 1; continue; }
  if (!existsSync(app.repoPath)) {
    console.error(`SKIP ${id}: repoPath does not exist — ${app.repoPath}`);
    process.exitCode = 1;
    continue;
  }
  const { defs, scanned } = generate(app);
  if (!defs.length) { console.error(`SKIP ${id}: scanned ${scanned} files, produced no routes`); continue; }
  const out = join(dirname(new URL(import.meta.url).pathname), '..', 'groups', `${id}.ts`);
  writeFileSync(out, emit(app, defs));
  total += defs.length;
  console.log(`${id.padEnd(14)} ${String(defs.length).padStart(4)} tools  (from ${scanned} route files)  -> groups/${id}.ts`);
}
console.log(`\n${total} tools generated.`);
