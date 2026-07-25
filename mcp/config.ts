/**
 * App source configuration for the HereTomorrow portfolio.
 */
import type { AppSource, MarketplaceListing } from './types.js';

export const OWNER_EMAIL = 'kalepasch@gmail.com';

export const APP_SOURCES: Record<string, AppSource> = {
  apparently: { id: 'apparently', label: 'Apparently', baseUrl: 'https://apparently.app', devUrl: 'http://localhost:3000', icon: '◈', category: 'Gaming RegTech', pricingTier: 'enterprise', costProfile: { aiCallsPerRequest: 1.2, avgLatencyMs: 3200, estimatedCostPerCall: 0.08 }, repoPath: '/Users/kpasch/Documents/apparently', apiScanGlob: 'server/api/**/*.ts', engineScanGlob: 'server/engines/**/*.ts' },
  vigil: { id: 'vigil', label: 'Vigil', baseUrl: 'https://vigil.heretomorrow.us', devUrl: 'http://localhost:3001', icon: '⊘', category: 'SupTech Platform', pricingTier: 'enterprise', costProfile: { aiCallsPerRequest: 1.5, avgLatencyMs: 4000, estimatedCostPerCall: 0.12 }, repoPath: '/Users/kpasch/Documents/apparently', apiScanGlob: 'server/api/**/*.ts', engineScanGlob: 'server/engines/**/*.ts' },
  pareto: { id: 'pareto', label: 'Pareto 2080', baseUrl: 'https://pareto2080.com', devUrl: 'http://localhost:3007', icon: '△', category: 'Personal Finance', pricingTier: 'professional', costProfile: { aiCallsPerRequest: 0.6, avgLatencyMs: 1800, estimatedCostPerCall: 0.03 }, repoPath: '/Users/kpasch/Documents/pareto/2080', apiScanGlob: 'server/api/**/*.js', engineScanGlob: 'server/utils/**/*.js' },
  smarter: { id: 'smarter', label: 'Smarter', baseUrl: 'https://smarter.legal', devUrl: 'http://localhost:3002', icon: '§', category: 'Legal Ops', pricingTier: 'professional', costProfile: { aiCallsPerRequest: 1.8, avgLatencyMs: 5000, estimatedCostPerCall: 0.15 }, repoPath: '/Users/kpasch/Documents/smarter', apiScanGlob: 'server/api/**/*.ts', engineScanGlob: 'server/engines/**/*.ts' },
  tomorrow: { id: 'tomorrow', label: 'Tomorrow', baseUrl: 'https://tomorrow.trade', devUrl: 'http://localhost:3003', icon: '∞', category: 'OTC Derivatives', pricingTier: 'enterprise', costProfile: { aiCallsPerRequest: 0.8, avgLatencyMs: 2500, estimatedCostPerCall: 0.06 }, repoPath: '/Users/kpasch/Documents/tomorrow', apiScanGlob: 'server/api/**/*.ts', engineScanGlob: 'server/utils/**/*.ts' },
  orchestrator: { id: 'orchestrator', label: 'Orchestrator', baseUrl: 'https://madeus.heretomorrow.us', devUrl: 'http://localhost:3004', icon: '◉', category: 'Fleet Orchestration', pricingTier: 'enterprise', costProfile: { aiCallsPerRequest: 0.3, avgLatencyMs: 800, estimatedCostPerCall: 0.01 }, repoPath: '/Users/kpasch/Documents/beethoven/claude-orchestrator', apiScanGlob: 'web/server/api/**/*.ts', engineScanGlob: 'server/utils/**/*.ts' },
};

export const MARKETPLACE_LISTINGS: MarketplaceListing[] = [
  { appId: 'apparently', displayName: 'Apparently — Gaming RegTech', tagline: 'Multi-jurisdiction licensing, compliance, and legal intelligence for gaming operators', category: 'Gaming RegTech', pricingTier: 'enterprise', icon: '◈' },
  { appId: 'vigil', displayName: 'Vigil — SupTech Platform', tagline: 'Supervisory technology for gaming regulators and compliance teams', category: 'SupTech Platform', pricingTier: 'enterprise', icon: '⊘' },
  { appId: 'pareto', displayName: 'Pareto 2080 — Personal Finance', tagline: 'AI-powered early-retirement planning, portfolio optimization, and life-ops', category: 'Personal Finance', pricingTier: 'professional', icon: '△' },
  { appId: 'smarter', displayName: 'Smarter — Legal Ops', tagline: 'AI war room for litigation, contract analysis, and legal research', category: 'Legal Ops', pricingTier: 'professional', icon: '§' },
  { appId: 'tomorrow', displayName: 'Tomorrow — OTC Derivatives', tagline: 'Structured trade building, credit risk transfer, and portfolio risk management', category: 'OTC Derivatives', pricingTier: 'enterprise', icon: '∞' },
  { appId: 'orchestrator', displayName: 'Madeus — Fleet Orchestration', tagline: 'Cross-vertical agent orchestration and fleet management', category: 'Fleet Orchestration', pricingTier: 'enterprise', icon: '◉' },
];
