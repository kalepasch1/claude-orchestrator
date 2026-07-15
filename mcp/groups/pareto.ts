/**
 * Tool definitions for Pareto 2080 -- Personal Finance.
 * 12 tools covering retirement, tax, portfolio, finance, treasury, and sweeps.
 */

import type { ToolDefinition } from '../types.js';

export const PARETO_TOOLS: ToolDefinition[] = [
  {
    name: 'pareto.retirement.monte_carlo',
    description: 'Run a Monte Carlo retirement simulation. Returns P10/P50/P90 outcomes, success probability, and retirement-day exchange rate.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, currentAge: { type: 'number', description: 'Current age', minimum: 18, maximum: 100 }, retirementAge: { type: 'number', description: 'Target retirement age', minimum: 30, maximum: 100 }, annualIncome: { type: 'number', description: 'Annual income USD', minimum: 0 }, annualExpenses: { type: 'number', description: 'Annual expenses USD', minimum: 0 }, portfolioValue: { type: 'number', description: 'Total portfolio value USD', minimum: 0 }, simulations: { type: 'number', description: 'Number of simulations', minimum: 100, maximum: 50000, default: 10000 } }, required: ['userId'] },
    proxyTo: { method: 'GET', path: '/api/personal/retirement/montecarlo' },
    costProfile: 'pure-logic',
    pricingCents: 100,
  },
  {
    name: 'pareto.retirement.social_security',
    description: 'Calculate Social Security benefits by claim age (62-70), breakeven analysis, spousal benefits, taxation impact, and optimal claiming strategy.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, birthYear: { type: 'number', description: 'Year of birth' }, earningsHistory: { type: 'array', description: 'Annual earnings (highest 35 years)', items: { type: 'number' } }, spouseEarnings: { type: 'array', description: 'Spouse annual earnings', items: { type: 'number' } }, lifeExpectancy: { type: 'number', description: 'Estimated life expectancy', minimum: 62, maximum: 110 } }, required: ['userId', 'birthYear'] },
    proxyTo: { method: 'GET', path: '/api/personal/retirement/social-security' },
    costProfile: 'pure-logic',
    pricingCents: 50,
  },
  {
    name: 'pareto.retirement.decumulation',
    description: 'Generate a tax-aware withdrawal sequencing plan. Optimizes draw-down order across taxable, tax-deferred, and Roth accounts. Includes Roth-ladder strategy.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, accounts: { type: 'array', description: 'Retirement accounts', items: { type: 'object', properties: { type: { type: 'string', enum: ['taxable', 'traditional-ira', 'roth-ira', '401k', 'roth-401k', 'hsa'] }, balance: { type: 'number' }, label: { type: 'string' } } } }, annualNeed: { type: 'number', description: 'Annual withdrawal need USD', minimum: 0 }, taxBracket: { type: 'number', description: 'Marginal tax bracket', minimum: 0, maximum: 0.37 } }, required: ['userId'] },
    proxyTo: { method: 'GET', path: '/api/personal/retirement/decumulation' },
    costProfile: 'pure-logic',
    pricingCents: 100,
  },
  {
    name: 'pareto.tax.deduction_optimizer',
    description: 'Optimize between standard and itemized deductions. Includes above-the-line steering, cap rerouting, and do-not-overspend guard.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, filingStatus: { type: 'string', description: 'Filing status', enum: ['single', 'married-filing-jointly', 'married-filing-separately', 'head-of-household'] }, income: { type: 'number', description: 'AGI in USD', minimum: 0 }, deductions: { type: 'object', description: 'Itemizable amounts', properties: { mortgage: { type: 'number' }, salt: { type: 'number' }, charitable: { type: 'number' }, medical: { type: 'number' }, other: { type: 'number' } } } }, required: ['userId', 'filingStatus'] },
    proxyTo: { method: 'POST', path: '/api/finance/deductions' },
    costProfile: 'pure-logic',
    pricingCents: 50,
  },
  {
    name: 'pareto.tax.entity_routing',
    description: 'Route an expense to the optimal tax entity (personal vs business). Evaluates QBI deduction, entity-level deductions, and combined tax plan.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, expense: { type: 'object', description: 'Expense to route', properties: { amount: { type: 'number' }, category: { type: 'string' }, description: { type: 'string' }, recurring: { type: 'boolean' } } }, entities: { type: 'array', description: 'Available entities', items: { type: 'object', properties: { type: { type: 'string', enum: ['personal', 'sole-prop', 'llc', 's-corp', 'c-corp'] }, name: { type: 'string' } } } } }, required: ['userId', 'expense'] },
    proxyTo: { method: 'POST', path: '/api/finance/entity-routing' },
    costProfile: 'pure-logic',
    pricingCents: 100,
  },
  {
    name: 'pareto.portfolio.optimize',
    description: 'Run portfolio optimization. Includes liability-driven allocation, asset location, glidepath, tax-loss harvesting, and rebalancing recommendations.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, riskTolerance: { type: 'string', description: 'Risk tolerance', enum: ['conservative', 'moderate', 'aggressive'] }, timeHorizon: { type: 'number', description: 'Time horizon years', minimum: 1, maximum: 50 }, taxRate: { type: 'number', description: 'Marginal tax rate', minimum: 0, maximum: 0.50 }, constraints: { type: 'object', description: 'Investment constraints', properties: { maxSinglePosition: { type: 'number' }, excludeSectors: { type: 'array', items: { type: 'string' } }, esgOnly: { type: 'boolean' } } } }, required: ['userId'] },
    proxyTo: { method: 'POST', path: '/api/investments/optimize' },
    costProfile: 'pure-logic',
    pricingCents: 200,
  },
  {
    name: 'pareto.portfolio.recommendations',
    description: 'Get AI-ranked investment deposit recommendations. Scores candidates across CAGR impact, Sortino, diversification, expense ratio, momentum, and drawdown.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, amount: { type: 'number', description: 'Deposit amount USD', minimum: 0 }, maxResults: { type: 'number', description: 'Max recommendations', minimum: 1, maximum: 20, default: 8 } }, required: ['userId'] },
    proxyTo: { method: 'GET', path: '/api/investments/recommendations' },
    costProfile: 'ai-light',
    pricingCents: 300,
  },
  {
    name: 'pareto.finance.opportunities',
    description: 'Scan for unclaimed financial opportunities. Returns prioritized money-on-table items: unclaimed points, credits, rebates, FSA/HSA deadlines, settlement eligibility.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, categories: { type: 'array', description: 'Categories to scan', items: { type: 'string', enum: ['points', 'credits', 'rebates', 'fsa-hsa', 'settlements', 'employer-benefits', 'tax'] } } }, required: ['userId'] },
    proxyTo: { method: 'GET', path: '/api/personal/opportunities' },
    costProfile: 'pure-logic',
    pricingCents: 100,
  },
  {
    name: 'pareto.finance.allocator',
    description: 'Run the unified-loop allocator: invest vs spend-now vs defer for each goal. Includes luxury frontier analysis.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, retireVsEnjoyWeight: { type: 'number', description: 'Weight: retirement (0) vs enjoyment (1)', minimum: 0, maximum: 1, default: 0.5 } }, required: ['userId'] },
    proxyTo: { method: 'POST', path: '/api/finance/allocator/proposal' },
    costProfile: 'pure-logic',
    pricingCents: 100,
  },
  {
    name: 'pareto.treasury.briefing',
    description: 'Get the personal treasury briefing. Shows liquidity position, deposit bonus rotation status, JIT funding readiness, and counterfactual analysis.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' } }, required: ['userId'] },
    proxyTo: { method: 'GET', path: '/api/personal/treasury' },
    costProfile: 'pure-logic',
    pricingCents: 100,
  },
  {
    name: 'pareto.sweeps.equity_comp',
    description: 'Analyze equity compensation: ESPP discount value, RSU vest withholding gap, ISO AMT flag, and 83(b) election decision.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, grants: { type: 'array', description: 'Equity grants', items: { type: 'object', properties: { type: { type: 'string', enum: ['espp', 'rsu', 'iso', 'nso', 'restricted-stock'] }, shares: { type: 'number' }, grantPrice: { type: 'number' }, currentPrice: { type: 'number' }, vestDate: { type: 'string' } } } } }, required: ['userId'] },
    proxyTo: { method: 'GET', path: '/api/personal/sweeps/equity-comp' },
    costProfile: 'pure-logic',
    pricingCents: 100,
  },
  {
    name: 'pareto.sweeps.subscription_savings',
    description: 'AI-ranked subscription savings sweep. Identifies cancellable subscriptions, negotiable rates, and cheaper alternatives.',
    inputSchema: { type: 'object', properties: { userId: { type: 'number', description: 'User profile ID' }, aggressiveness: { type: 'string', description: 'Cut aggressiveness', enum: ['conservative', 'moderate', 'aggressive'], default: 'moderate' } }, required: ['userId'] },
    proxyTo: { method: 'POST', path: '/api/finance/sweep-proposal' },
    costProfile: 'ai-light',
    pricingCents: 200,
  },
];
