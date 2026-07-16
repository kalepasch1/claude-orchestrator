#!/usr/bin/env node
/**
 * Auto-MCP Generator
 * Scans a Nuxt/Node app's API routes and engine files to auto-generate
 * MCP tool definitions with suggested pricing.
 *
 * Usage: tsx generator/auto-mcp.ts --app-name=myapp --repo=/path/to/repo [--pricing-tier=standard]
 */

import { readdir, readFile, writeFile, mkdir } from 'fs/promises';
import { join, basename, extname, relative } from 'path';

interface ScannedEndpoint {
  filePath: string;
  route: string;
  method: string;
  costProfile: 'pure-logic' | 'ai-light' | 'ai-heavy' | 'external-api';
  suggestedPriceCents: number;
  description: string;
}

interface ScannedEngine {
  filePath: string;
  name: string;
  exports: string[];
}

const AI_INDICATORS = [
  'anthropic', 'claude', 'openai', 'gpt', 'callClaude', 'callClaudeStructured',
  'ai-call-logger', 'embeddings', 'voyage', 'generateText', 'streamText',
];

const EXTERNAL_API_INDICATORS = [
  'plaid', 'stripe', 'twilio', 'sendgrid', 'resend', 'fetch(',
  'axios', 'got(', 'request(',
];

const PRICING_TIERS: Record<string, Record<string, number>> = {
  budget: { 'pure-logic': 10, 'ai-light': 50, 'ai-heavy': 200, 'external-api': 100 },
  standard: { 'pure-logic': 50, 'ai-light': 200, 'ai-heavy': 1000, 'external-api': 300 },
  premium: { 'pure-logic': 100, 'ai-light': 500, 'ai-heavy': 3000, 'external-api': 500 },
};

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

function classifyCostProfile(content: string): ScannedEndpoint['costProfile'] {
  const lower = content.toLowerCase();
  const aiScore = AI_INDICATORS.reduce((s, i) => s + (lower.includes(i.toLowerCase()) ? 1 : 0), 0);
  const extScore = EXTERNAL_API_INDICATORS.reduce((s, i) => s + (lower.includes(i.toLowerCase()) ? 1 : 0), 0);
  if (aiScore >= 3) return 'ai-heavy';
  if (aiScore >= 1) return 'ai-light';
  if (extScore >= 2) return 'external-api';
  return 'pure-logic';
}

function extractDescription(content: string, filePath: string): string {
  const jsdoc = content.match(/\/\*\*\s*\n\s*\*\s*(.+)/);
  if (jsdoc) return jsdoc[1].trim();
  const line = content.match(/\/\/\s*(.+)/);
  if (line) return line[1].trim();
  return `API endpoint: ${filePath.replace(/\.(ts|js)$/, '')}`;
}

async function scanApiRoutes(repoPath: string): Promise<ScannedEndpoint[]> {
  const apiDir = join(repoPath, 'server', 'api');
  const endpoints: ScannedEndpoint[] = [];
  try {
    await walkDir(apiDir, async (filePath) => {
      if (!filePath.endsWith('.ts') && !filePath.endsWith('.js')) return;
      if (filePath.includes('.test.')) return;
      const content = await readFile(filePath, 'utf-8');
      const rel = relative(apiDir, filePath);
      let method = 'POST';
      if (filePath.endsWith('.get.ts') || filePath.endsWith('.get.js')) method = 'GET';
      else if (filePath.endsWith('.put.ts') || filePath.endsWith('.put.js')) method = 'PUT';
      else if (filePath.endsWith('.delete.ts') || filePath.endsWith('.delete.js')) method = 'DELETE';
      const route = '/' + rel.replace(/\.(get|post|put|delete|patch)\.(ts|js)$/, '').replace(/\.(ts|js)$/, '').replace(/\[([^\]]+)\]/g, ':$1').replace(/index$/, '').replace(/\/$/, '');
      endpoints.push({ filePath: rel, route: `/api${route}`, method, costProfile: classifyCostProfile(content), suggestedPriceCents: 0, description: extractDescription(content, rel) });
    });
  } catch { /* api dir may not exist */ }
  return endpoints;
}

async function scanEngines(repoPath: string): Promise<ScannedEngine[]> {
  const engines: ScannedEngine[] = [];
  for (const dir of [join(repoPath, 'server', 'utils'), join(repoPath, 'server', 'engines')]) {
    try {
      await walkDir(dir, async (filePath) => {
        if (!filePath.endsWith('.ts') && !filePath.endsWith('.js')) return;
        if (filePath.includes('.test.')) return;
        const content = await readFile(filePath, 'utf-8');
        const exports = [...content.matchAll(/export\s+(?:function|const|class|async function)\s+(\w+)/g)].map((m) => m[1]);
        if (exports.length > 0) engines.push({ filePath: relative(repoPath, filePath), name: basename(filePath, extname(filePath)), exports });
      });
    } catch { /* dir may not exist */ }
  }
  return engines;
}

async function generateToolDefinitions(appName: string, endpoints: ScannedEndpoint[], pricingTier: string): Promise<string> {
  const prices = PRICING_TIERS[pricingTier] || PRICING_TIERS.standard;
  const tools = endpoints.map((ep) => {
    const price = prices[ep.costProfile];
    const toolName = `${appName}.${ep.route.replace(/^\/api\//, '').replace(/\//g, '.').replace(/[^a-zA-Z0-9_.]/g, '')}`;
    return `  { name: '${toolName}', description: '${ep.description.replace(/'/g, "\\'")}', inputSchema: { type: 'object', properties: {}, required: [] }, proxyTo: { method: '${ep.method}', path: '${ep.route}' }, costProfile: '${ep.costProfile}', pricingCents: ${price} }`;
  });
  return `import type { ToolDefinition } from '../types.js';\n\nexport const ${appName.toUpperCase().replace(/-/g, '_')}_TOOLS: ToolDefinition[] = [\n${tools.join(',\n')}\n];\n`;
}

async function main() {
  const params: Record<string, string> = {};
  for (const arg of process.argv.slice(2)) {
    const m = arg.match(/^--(\w[\w-]*)=(.+)$/);
    if (m) params[m[1]] = m[2];
  }
  const appName = params['app-name'];
  const repoPath = params.repo;
  const pricingTier = params['pricing-tier'] || 'standard';
  if (!appName || !repoPath) { console.error('Usage: tsx generator/auto-mcp.ts --app-name=myapp --repo=/path/to/repo [--pricing-tier=standard|budget|premium]'); process.exit(1); }

  console.error(`Scanning ${appName} at ${repoPath}...`);
  const endpoints = await scanApiRoutes(repoPath);
  const engines = await scanEngines(repoPath);
  const prices = PRICING_TIERS[pricingTier] || PRICING_TIERS.standard;
  endpoints.forEach((ep) => { ep.suggestedPriceCents = prices[ep.costProfile]; });

  const outDir = join(process.cwd(), 'generated');
  await mkdir(outDir, { recursive: true });
  await writeFile(join(outDir, `${appName}.ts`), await generateToolDefinitions(appName, endpoints, pricingTier));

  const report = [
    `# MCP Readiness Report: ${appName}`, '',
    `- Endpoints: ${endpoints.length}`, `- Engines: ${engines.length}`,
    `- AI-heavy: ${endpoints.filter((e) => e.costProfile === 'ai-heavy').length}`,
    `- Est. monthly revenue (1k calls/tool): $${(endpoints.reduce((s, e) => s + e.suggestedPriceCents * 1000, 0) / 100).toFixed(2)}`,
  ].join('\n');
  await writeFile(join(outDir, `${appName}-readiness.md`), report);
  await writeFile(join(outDir, `${appName}.mcp-config.json`), JSON.stringify({ appName, generatedAt: new Date().toISOString(), pricingTier, toolCount: endpoints.length, engineCount: engines.length, endpoints: endpoints.map((e) => ({ route: e.route, method: e.method, costProfile: e.costProfile, priceCents: e.suggestedPriceCents })) }, null, 2));

  console.error(`Generated ${endpoints.length} tools -> ${outDir}/`);
}

main().catch((e) => { console.error('Generator error:', e); process.exit(1); });
