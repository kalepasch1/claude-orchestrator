#!/usr/bin/env node
/**
 * HereTomorrow MCP — stdio entrypoint (Claude Code, Claude Desktop).
 *
 * All routing, tool registration and proxying lives in core.ts, which http.ts
 * serves too. This file is only the transport.
 *
 *   npm run dev            # tsx server.ts
 *   npm run build && npm start
 */
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { createServer, readyLine } from './core.js';

async function main() {
  const server = createServer();
  await server.connect(new StdioServerTransport());
  // stdout is the MCP channel. Anything a human reads goes to stderr, or the
  // first log line corrupts the protocol handshake.
  console.error(`[mcp] heretomorrow ready (stdio) — ${readyLine()}`);
}

main().catch((e) => {
  console.error('[mcp] fatal:', e);
  process.exit(1);
});
