/**
 * Core type definitions for the HereTomorrow unified MCP server.
 */

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: {
    type: 'object';
    properties: Record<string, JsonSchemaProperty>;
    required?: string[];
  };
  proxyTo: {
    method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    path: string;
  };
  costProfile: 'pure-logic' | 'ai-light' | 'ai-heavy' | 'external-api' | 'hybrid';
  pricingCents: number;
}

export interface JsonSchemaProperty {
  type: string;
  description?: string;
  enum?: string[];
  items?: JsonSchemaProperty;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
}

export interface AppSource {
  id: string;
  label: string;
  baseUrl: string;
  devUrl: string;
  icon: string;
  category: string;
  pricingTier: 'free' | 'professional' | 'enterprise';
  costProfile: CostProfile;
  repoPath: string;
  apiScanGlob: string;
  engineScanGlob: string;
}

export interface CostProfile {
  aiCallsPerRequest: number;
  avgLatencyMs: number;
  estimatedCostPerCall: number;
}

export interface MarketplaceListing {
  appId: string;
  displayName: string;
  tagline: string;
  category: string;
  pricingTier: string;
  icon: string;
}

export interface ToolGroup {
  appId: string;
  label: string;
  icon: string;
  tools: ToolDefinition[];
}

export interface ScanManifest {
  appId: string;
  hash: string;
  scannedAt: string;
  endpoints: ScannedEndpoint[];
  engines: ScannedEngine[];
}

export interface ScannedEndpoint {
  filePath: string;
  method: string;
  route: string;
  hasAiCall: boolean;
  hasExternalApi: boolean;
}

export interface ScannedEngine {
  filePath: string;
  exports: string[];
  isPureLogic: boolean;
}

export interface BillingEvent {
  toolName: string;
  appId: string;
  pricingCents: number;
  timestamp: string;
  userId?: string;
  durationMs: number;
  success: boolean;
}
