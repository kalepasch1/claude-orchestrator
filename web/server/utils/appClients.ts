/**
 * Per-app Supabase client registry for the unified admin proxy.
 * Each app's credentials come from env vars: SUPABASE_URL_<APP>, SUPABASE_SERVICE_KEY_<APP>.
 * The proxy never uses RLS — it operates with service-role keys, gated by the orchestrator's
 * own auth middleware (OPS_EMAILS allowlist).
 */
import { createClient, type SupabaseClient } from '@supabase/supabase-js'

export type AppId = 'apparently' | 'tomorrow' | 'smarter' | 'galop' | 'hisanta' | 'pareto' | 'sustainable_barks' | 'orchestrator'

interface AppConfig {
  supabaseUrl: string
  supabaseServiceKey: string
  displayName: string
  baseUrl: string // Vercel deployment URL
  hasFleetExecute: boolean
}

const APP_ENV_MAP: Record<AppId, { urlEnv: string; keyEnv: string; name: string; baseUrlEnv: string }> = {
  apparently:   { urlEnv: 'SUPABASE_URL_APPARENTLY',   keyEnv: 'SUPABASE_SERVICE_KEY_APPARENTLY',   name: 'Apparently',   baseUrlEnv: 'FLEET_URL_APPARENTLY' },
  tomorrow:     { urlEnv: 'SUPABASE_URL_TOMORROW',     keyEnv: 'SUPABASE_SERVICE_KEY_TOMORROW',     name: 'Tomorrow',     baseUrlEnv: 'FLEET_URL_TOMORROW' },
  smarter:      { urlEnv: 'SUPABASE_URL_SMARTER',      keyEnv: 'SUPABASE_SERVICE_KEY_SMARTER',      name: 'Smarter',      baseUrlEnv: 'FLEET_URL_SMARTER' },
  galop:        { urlEnv: 'SUPABASE_URL_GALOP',        keyEnv: 'SUPABASE_SERVICE_KEY_GALOP',        name: 'Galop',        baseUrlEnv: 'FLEET_URL_GALOP' },
  hisanta:      { urlEnv: 'SUPABASE_URL_HISANTA',      keyEnv: 'SUPABASE_SERVICE_KEY_HISANTA',      name: 'HiSanta',      baseUrlEnv: 'FLEET_URL_HISANTA' },
  pareto:           { urlEnv: 'SUPABASE_URL_PARETO',           keyEnv: 'SUPABASE_SERVICE_KEY_PARETO',           name: 'Pareto',           baseUrlEnv: 'FLEET_URL_PARETO' },
  sustainable_barks:{ urlEnv: 'SUPABASE_URL_SUSTAINABLE_BARKS',keyEnv: 'SUPABASE_SERVICE_KEY_SUSTAINABLE_BARKS',name: 'Sustainable Barks',baseUrlEnv: 'FLEET_URL_SUSTAINABLE_BARKS' },
  orchestrator:     { urlEnv: 'SUPABASE_URL',                  keyEnv: 'SUPABASE_SERVICE_KEY',                  name: 'Orchestrator',     baseUrlEnv: 'FLEET_URL_ORCHESTRATOR' },
}

const clients = new Map<AppId, SupabaseClient>()

export function getAppClient(appId: AppId): SupabaseClient | null {
  if (clients.has(appId)) return clients.get(appId)!
  const env = APP_ENV_MAP[appId]
  const url = process.env[env.urlEnv]
  const key = process.env[env.keyEnv] || process.env[`${env.keyEnv.replace('SERVICE_KEY', 'SERVICE_ROLE_KEY')}`]
  if (!url || !key) return null
  const client = createClient(url, key)
  clients.set(appId, client)
  return client
}

export function getAppConfig(appId: AppId): { name: string; baseUrl: string | null; configured: boolean } {
  const env = APP_ENV_MAP[appId]
  return {
    name: env.name,
    baseUrl: process.env[env.baseUrlEnv] ?? null,
    configured: !!(process.env[env.urlEnv] && (process.env[env.keyEnv] || process.env[env.keyEnv.replace('SERVICE_KEY', 'SERVICE_ROLE_KEY')])),
  }
}

export function listApps(): { id: AppId; name: string; configured: boolean; baseUrl: string | null }[] {
  return (Object.keys(APP_ENV_MAP) as AppId[]).map((id) => ({ id, ...getAppConfig(id) }))
}

export const ALL_APP_IDS: AppId[] = Object.keys(APP_ENV_MAP) as AppId[]
