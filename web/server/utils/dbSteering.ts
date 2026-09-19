/**
 * Database Steering — the web half of runner/db_steering_contract.py.
 *
 * Provider ids, dialect derivation and the credential-reference rule are spelled here
 * exactly as the runner spells them, because `db_sources` rows written by this app are
 * read by the Mac runner. A `credential_ref` is a REFERENCE (env:, keychain:, doppler:,
 * onepassword:, vault:<connector_account_id>, file:) — never a DSN, never a password.
 */

export const DB_PROVIDERS = [
  'supabase', 'postgres', 'mysql',
  'aws_rds', 'aws_aurora', 'aws_redshift',
  'gcp_cloudsql', 'gcp_alloydb', 'gcp_bigquery',
  'azure_postgres', 'azure_mysql',
  'neon', 'planetscale', 'cockroachdb', 'snowflake', 'mongodb', 'other',
] as const
export type DbProvider = typeof DB_PROVIDERS[number]
export type DbDialect = 'postgres' | 'mysql' | 'bigquery' | 'snowflake' | 'mongodb' | 'other'

export const PROVIDER_DEFAULT_DIALECT: Record<DbProvider, DbDialect> = {
  supabase: 'postgres', postgres: 'postgres', neon: 'postgres', cockroachdb: 'postgres',
  aws_rds: 'postgres', aws_aurora: 'postgres', aws_redshift: 'postgres',
  gcp_cloudsql: 'postgres', gcp_alloydb: 'postgres', azure_postgres: 'postgres',
  mysql: 'mysql', planetscale: 'mysql', azure_mysql: 'mysql',
  gcp_bigquery: 'bigquery', snowflake: 'snowflake', mongodb: 'mongodb', other: 'other',
}

/** Connector ids (web/config/connectors.ts, category 'Databases') → runner provider ids. */
const CONNECTOR_PROVIDER: Record<string, DbProvider> = {
  'aws-rds': 'aws_rds', 'gcp-cloudsql': 'gcp_cloudsql', 'gcp-bigquery': 'gcp_bigquery', 'azure-postgres': 'azure_postgres',
}
export function mapConnectorToProvider(connectorId: string, opts: { aurora?: boolean } = {}): DbProvider | null {
  const id = String(connectorId || '').trim()
  if (id === 'aws-rds' && opts.aurora) return 'aws_aurora'
  if (CONNECTOR_PROVIDER[id]) return CONNECTOR_PROVIDER[id]
  return (DB_PROVIDERS as readonly string[]).includes(id) ? id as DbProvider : null
}
export function isDbProvider(value: unknown): value is DbProvider { return (DB_PROVIDERS as readonly string[]).includes(String(value)) }

/** Dialect for a provider; AWS/GCP managed engines can run MySQL, which config.engine says. */
export function dialectFor(provider: DbProvider, config: Record<string, any> | null | undefined = {}): DbDialect {
  const engine = String(config?.engine || '').toLowerCase()
  if (engine === 'mysql' && ['aws_rds', 'aws_aurora', 'gcp_cloudsql'].includes(provider)) return 'mysql'
  return PROVIDER_DEFAULT_DIALECT[provider] || 'other'
}

/** Host of a DSN, never its credentials. Returns '' for anything that does not parse. */
export function hostFromDsn(dsn: unknown): string {
  const raw = String(dsn || '').trim()
  if (!raw || !raw.includes('://')) return ''
  try {
    // WHATWG URL only knows special schemes; normalise so postgresql://, mysql://, mongodb+srv:// parse alike.
    const url = new URL(raw.replace(/^[a-z][a-z0-9+.-]*:\/\//i, 'http://'))
    const host = url.hostname || ''
    return /[:@\s]/.test(host) ? '' : host
  } catch { return '' }
}

export const CREDENTIAL_REF_PATTERN = /^(env|keychain|doppler|onepassword|vault|file):/
const INLINE_USERINFO = /:\/\/[^/\s]*:[^/\s]*@/
/** Mirrors runner credential_ref_is_reference(): empty is fine (fleet token); a form-prefixed reference without user:pass@ inside is fine; anything else is a value. */
export function isCredentialReference(ref: unknown): boolean {
  const s = String(ref || '').trim()
  if (!s) return true
  if (!CREDENTIAL_REF_PATTERN.test(s)) return false
  return !INLINE_USERINFO.test(s)
}

/** What the UI may see: the reference's kind, never its value. */
export function maskCredentialRef(ref: unknown): string {
  const s = String(ref || '').trim()
  if (!s) return 'fleet-token'
  const idx = s.indexOf(':')
  return idx > 0 ? s.slice(0, idx) : 'unknown'
}

export const SECRET_CREDENTIAL_KEYS = new Set(['password', 'dsn', 'service_account_json', 'access_token', 'secret', 'api_key', 'token', 'private_key'])
/** Credential fields safe to keep in db_sources.config (port, database, engine, ...). Secret-bearing keys are dropped by name. */
export function nonSecretConfig(credentials: Record<string, any> | null | undefined): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(credentials || {})) {
    if (SECRET_CREDENTIAL_KEYS.has(key) || /password|secret|token|private/i.test(key)) continue
    const text = String(value ?? '').trim()
    if (text) out[key] = text
  }
  return out
}

/** The `ref` column for a source registered from the connectors form. */
export function refFromCredentials(credentials: Record<string, any> | null | undefined, fallback: string): string {
  const c = credentials || {}
  return String(c.project_ref || c.host || c.instance_connection_name || c.project_id || c.account || hostFromDsn(c.dsn) || fallback).trim()
}

export const SEVERITY_RANK: Record<string, number> = { info: 0, low: 1, medium: 2, high: 3, critical: 4 }
export function severityRank(value: unknown): number { return SEVERITY_RANK[String(value)] ?? -1 }

export function maskSource<T extends { credential_ref?: string | null }>(row: T): Omit<T, 'credential_ref'> & { credential_kind: string } {
  const { credential_ref, ...rest } = row
  return { ...rest, credential_kind: maskCredentialRef(credential_ref) }
}
