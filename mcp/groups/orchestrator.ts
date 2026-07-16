/**
 * Tool definitions for Madeus Orchestrator — cross-vertical coordination.
 */
import type { ToolDefinition } from '../types.js';

export const ORCHESTRATOR_TOOLS: ToolDefinition[] = [
  { name: 'orchestrator.execute_parallel', description: 'Execute multiple tools from any app group in parallel with dependency resolution. Returns aggregated results with per-tool timing and cost.', inputSchema: { type: 'object', properties: { calls: { type: 'array', description: 'Tool calls to execute', items: { type: 'object', properties: { tool: { type: 'string', description: 'Fully qualified tool name' }, args: { type: 'object' }, dependsOn: { type: 'array', items: { type: 'string' } } }, required: ['tool', 'args'] } }, failFast: { type: 'boolean', description: 'Stop on first error', default: false } }, required: ['calls'] }, proxyTo: { method: 'POST', path: '/api/orchestrator/parallel' }, costProfile: 'pure-logic', pricingCents: 1000 },
  { name: 'orchestrator.cross_vertical', description: 'Cross-vertical intelligence: combines insights from gaming, finance, legal, and derivatives into a unified analysis.', inputSchema: { type: 'object', properties: { query: { type: 'string', description: 'Query spanning multiple verticals' }, verticals: { type: 'array', items: { type: 'string', enum: ['gaming', 'finance', 'legal', 'derivatives', 'all'] } }, depth: { type: 'string', enum: ['quick', 'standard', 'deep'] } }, required: ['query'] }, proxyTo: { method: 'POST', path: '/api/orchestrator/cross-vertical' }, costProfile: 'ai-heavy', pricingCents: 2000 },
  { name: 'orchestrator.status', description: 'Health and status of all connected services, tool availability, and usage metrics.', inputSchema: { type: 'object', properties: { includeMetrics: { type: 'boolean', default: true } } }, proxyTo: { method: 'GET', path: '/api/orchestrator/status' }, costProfile: 'pure-logic', pricingCents: 0 },
];
