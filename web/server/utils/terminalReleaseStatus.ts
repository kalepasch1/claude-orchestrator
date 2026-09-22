export interface ReleaseStatusRow {
  id?: string | null
  project?: string | null
  version?: string | null
  to_sha?: string | null
  deploy_status?: string | null
  vercel_url?: string | null
  created_at?: string | null
  deployed_at?: string | null
}

/** Format shared release-ledger facts without promoting runtime metadata to proof. */
export function formatReleaseLedger(rows: ReleaseStatusRow[] | null | undefined, error?: string): string {
  if (error) {
    return `Release status UNKNOWN\n  Shared release ledger could not be read: ${error}\n  No deployment conclusion was inferred from this Vercel runtime.`
  }
  if (!rows?.length) {
    return 'Shared release ledger\n  No release rows found.\n  No deployment is proven by this result.'
  }

  const lines = rows.map((row) => {
    const project = row.project || 'unknown-project'
    const version = row.version || row.id || 'unknown-release'
    const status = row.deploy_status || 'unknown'
    const sha = row.to_sha ? String(row.to_sha).slice(0, 12) : 'no-sha'
    const url = row.vercel_url ? ` · ${row.vercel_url}` : ''
    const at = row.deployed_at || row.created_at || 'unknown-time'
    return `  ${project} · ${version} · ${status} · ${sha} · ${at}${url}`
  })
  return ['Shared release ledger (newest first)', ...lines, '', 'Statuses are shown as recorded; only a verified release plus its production journey proves delivery.'].join('\n')
}
