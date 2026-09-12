import { describe, it, expect } from 'vitest'
import {
  DB_PROVIDERS,
  PROVIDER_DEFAULT_DIALECT,
  mapConnectorToProvider,
  dialectFor,
  hostFromDsn,
  isCredentialReference,
  CREDENTIAL_REF_PATTERN,
  maskCredentialRef,
  maskSource,
  nonSecretConfig,
  refFromCredentials,
  severityRank,
} from '../dbSteering'

/**
 * These mirror runner/db_steering_contract.py. If a provider id, dialect or the
 * credential-reference rule drifts between the two, the runner stops recognising
 * rows the web app writes — keep both sides in step.
 */
describe('provider mapping (connector id → runner provider id)', () => {
  it('maps the hyphenated connector ids to underscore provider ids', () => {
    expect(mapConnectorToProvider('aws-rds')).toBe('aws_rds')
    expect(mapConnectorToProvider('aws-rds', { aurora: true })).toBe('aws_aurora')
    expect(mapConnectorToProvider('gcp-cloudsql')).toBe('gcp_cloudsql')
    expect(mapConnectorToProvider('gcp-bigquery')).toBe('gcp_bigquery')
    expect(mapConnectorToProvider('azure-postgres')).toBe('azure_postgres')
  })
  it('passes identical ids through and refuses unknown ones', () => {
    for (const id of ['supabase', 'postgres', 'mysql', 'neon', 'planetscale', 'cockroachdb', 'snowflake', 'mongodb']) expect(mapConnectorToProvider(id)).toBe(id)
    expect(mapConnectorToProvider('stripe')).toBeNull()
    expect(mapConnectorToProvider('')).toBeNull()
  })
  it('keeps the runner provider list verbatim', () => {
    expect([...DB_PROVIDERS]).toEqual(['supabase', 'postgres', 'mysql', 'aws_rds', 'aws_aurora', 'aws_redshift', 'gcp_cloudsql', 'gcp_alloydb', 'gcp_bigquery', 'azure_postgres', 'azure_mysql', 'neon', 'planetscale', 'cockroachdb', 'snowflake', 'mongodb', 'other'])
    for (const p of DB_PROVIDERS) expect(PROVIDER_DEFAULT_DIALECT[p]).toBeTruthy()
  })
})

describe('dialect derivation', () => {
  it('uses the provider default', () => {
    expect(dialectFor('supabase')).toBe('postgres')
    expect(dialectFor('neon')).toBe('postgres')
    expect(dialectFor('planetscale')).toBe('mysql')
    expect(dialectFor('gcp_bigquery')).toBe('bigquery')
    expect(dialectFor('snowflake')).toBe('snowflake')
    expect(dialectFor('mongodb')).toBe('mongodb')
  })
  it('honours config.engine=mysql only for the managed AWS/GCP engines', () => {
    expect(dialectFor('aws_rds', { engine: 'mysql' })).toBe('mysql')
    expect(dialectFor('aws_aurora', { engine: 'MySQL' })).toBe('mysql')
    expect(dialectFor('gcp_cloudsql', { engine: 'mysql' })).toBe('mysql')
    expect(dialectFor('aws_rds', { engine: 'postgres' })).toBe('postgres')
    expect(dialectFor('supabase', { engine: 'mysql' })).toBe('postgres')
    expect(dialectFor('neon', { engine: 'mysql' })).toBe('postgres')
  })
})

describe('hostFromDsn', () => {
  it('returns only the host for valid DSNs of any scheme', () => {
    expect(hostFromDsn('postgresql://user:pass@db.example.com:5432/app?sslmode=require')).toBe('db.example.com')
    expect(hostFromDsn('mysql://root:s3cret@10.0.0.9:3306/shop')).toBe('10.0.0.9')
    expect(hostFromDsn('mongodb+srv://u:p@cluster0.abc.mongodb.net/db')).toBe('cluster0.abc.mongodb.net')
    expect(hostFromDsn('postgres://host-only.internal/db')).toBe('host-only.internal')
  })
  it('returns empty for invalid or non-URL input', () => {
    expect(hostFromDsn('')).toBe('')
    expect(hostFromDsn(undefined)).toBe('')
    expect(hostFromDsn('not a dsn')).toBe('')
    expect(hostFromDsn('postgresql://')).toBe('')
    expect(hostFromDsn('host=db.example.com user=x password=y')).toBe('')
  })
  it('never leaks the user:pass segment', () => {
    const out = hostFromDsn('postgresql://alice:hunter2@db.example.com/app')
    expect(out).not.toContain('alice')
    expect(out).not.toContain('hunter2')
    expect(out).not.toContain('@')
    expect(out).not.toContain(':')
  })
})

describe('credential references', () => {
  it('accepts the reference forms', () => {
    for (const ref of ['env:PROD_DB_URL', 'keychain:apparently-db', 'doppler:prj/prd/DB_URL', 'onepassword:op://vault/item/field', 'vault:4f1c6b6e-6b7f-4c2e-9d5b-1a2b3c4d5e6f', 'file:/etc/fleet/db.dsn']) {
      expect(CREDENTIAL_REF_PATTERN.test(ref)).toBe(true)
      expect(isCredentialReference(ref)).toBe(true)
    }
  })
  it('treats empty as fine (Supabase through the fleet token)', () => {
    expect(isCredentialReference('')).toBe(true)
    expect(isCredentialReference(undefined)).toBe(true)
  })
  it('refuses raw DSNs, passwords and references that smuggle user:pass@', () => {
    expect(isCredentialReference('postgresql://u:p@host/db')).toBe(false)
    expect(isCredentialReference('hunter2')).toBe(false)
    expect(isCredentialReference('sbp_0123456789abcdef')).toBe(false)
    expect(isCredentialReference('env:postgresql://u:p@host/db')).toBe(false)
    expect(isCredentialReference('file:mysql://root:pw@10.0.0.1/db')).toBe(false)
  })
})

describe('maskCredentialRef', () => {
  it('returns the kind, never the value', () => {
    expect(maskCredentialRef('vault:4f1c6b6e-6b7f-4c2e-9d5b-1a2b3c4d5e6f')).toBe('vault')
    expect(maskCredentialRef('env:PROD_DB_URL')).toBe('env')
    expect(maskCredentialRef('onepassword:op://vault/item/field')).toBe('onepassword')
    expect(maskCredentialRef('')).toBe('fleet-token')
    expect(maskCredentialRef(null)).toBe('fleet-token')
    expect(maskCredentialRef('garbage')).toBe('unknown')
  })
  it('maskSource drops credential_ref and adds credential_kind', () => {
    const masked = maskSource({ id: 'x', label: 'L', credential_ref: 'vault:abc' })
    expect(masked).toEqual({ id: 'x', label: 'L', credential_kind: 'vault' })
    expect('credential_ref' in masked).toBe(false)
  })
})

describe('nonSecretConfig', () => {
  it('strips every secret-bearing key and keeps the rest as trimmed strings', () => {
    const out = nonSecretConfig({
      region: ' us-east-1 ', engine: 'postgres', host: 'db.internal', port: '5432', database: 'app', username: 'reader',
      password: 'hunter2', dsn: 'postgresql://u:p@h/db', service_account_json: '{"private_key":"x"}', access_token: 'sbp_x',
      secret_arn: 'arn:aws:secretsmanager:…', resource_arn: 'arn:aws:rds:…', client_secret: 'zzz', empty: '',
    })
    expect(out).toEqual({ region: 'us-east-1', engine: 'postgres', host: 'db.internal', port: '5432', database: 'app', username: 'reader', resource_arn: 'arn:aws:rds:…' })
    expect(JSON.stringify(out)).not.toMatch(/hunter2|sbp_x|private_key|zzz/)
  })
  it('handles missing input', () => { expect(nonSecretConfig(null)).toEqual({}); expect(nonSecretConfig(undefined)).toEqual({}) })
})

describe('refFromCredentials', () => {
  it('prefers the most specific identifier and falls back to the DSN host, then the given fallback', () => {
    expect(refFromCredentials({ project_ref: 'abcdefghijkl', host: 'x' }, 'supabase')).toBe('abcdefghijkl')
    expect(refFromCredentials({ host: 'db.rds.amazonaws.com' }, 'aws-rds')).toBe('db.rds.amazonaws.com')
    expect(refFromCredentials({ instance_connection_name: 'p:r:i' }, 'gcp-cloudsql')).toBe('p:r:i')
    expect(refFromCredentials({ project_id: 'my-proj' }, 'gcp-bigquery')).toBe('my-proj')
    expect(refFromCredentials({ account: 'xy12345.us-east-1' }, 'snowflake')).toBe('xy12345.us-east-1')
    expect(refFromCredentials({ dsn: 'postgresql://u:p@neon.tech:5432/db' }, 'neon')).toBe('neon.tech')
    expect(refFromCredentials({ dsn: 'garbage' }, 'postgres')).toBe('postgres')
    expect(refFromCredentials({}, 'supabase')).toBe('supabase')
  })
})

describe('severityRank', () => {
  it('orders critical > high > medium > low > info and unknown below all', () => {
    expect(severityRank('critical')).toBeGreaterThan(severityRank('high'))
    expect(severityRank('high')).toBeGreaterThan(severityRank('medium'))
    expect(severityRank('medium')).toBeGreaterThan(severityRank('low'))
    expect(severityRank('low')).toBeGreaterThan(severityRank('info'))
    expect(severityRank('bogus')).toBeLessThan(severityRank('info'))
  })
})
