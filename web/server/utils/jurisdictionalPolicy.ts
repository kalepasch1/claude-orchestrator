import { createHash } from 'node:crypto'

export type PolicySource = { id:string; jurisdiction:string; domain:string; title:string; authority_url?:string; effective_from:string; effective_to?:string|null; status:string; rules?:any }
export type PolicyInput = { jurisdiction:string; domains:string[]; as_of?:string; contract?:Record<string,any>; sources?:PolicySource[] }

const stable=(value:any):string=>Array.isArray(value)?`[${value.map(stable).join(',')}]`:value&&typeof value==='object'?`{${Object.keys(value).sort().map(key=>`${JSON.stringify(key)}:${stable(value[key])}`).join(',')}}`:JSON.stringify(value)
const digest = (value:any) => createHash('sha256').update(stable(value)).digest('hex')
const dateOnly = (value:string) => /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : new Date(value).toISOString().slice(0,10)

export function compileJurisdictionalPolicy(input:PolicyInput) {
  const jurisdiction = String(input.jurisdiction || '').trim().slice(0,120)
  if (!jurisdiction) throw new Error('jurisdiction_required')
  const asOf = dateOnly(input.as_of || new Date().toISOString())
  const domains = [...new Set((input.domains || []).map(String).filter(Boolean))].sort()
  const active = (input.sources || []).filter(source => source.status === 'verified' && source.jurisdiction.toLowerCase() === jurisdiction.toLowerCase() && domains.includes(source.domain) && source.effective_from <= asOf && (!source.effective_to || source.effective_to >= asOf))
  const contract = input.contract || {}; const flags:string[] = []
  if (!active.length) flags.push('No verified effective-date authority pack covers this jurisdiction and domain.')
  if (domains.includes('employment')) flags.push('Local employment counsel must review before issuance.')
  if (contract.cross_border) flags.push('Cross-border parties or performance require conflicts, tax, privacy, and enforceability review.')
  if (contract.personal_data) flags.push('Personal-data processing requires privacy-role, security, transfer, retention, and incident review.')
  if (contract.non_compete) flags.push('Post-termination restriction requires jurisdiction-specific enforceability review.')
  if (contract.equity || contract.securities) flags.push('Equity or securities terms require corporate, tax, and securities review.')
  if (contract.uncapped_liability || contract.exclusivity || contract.ip_transfer) flags.push('Material risk allocation requires independent legal approval.')
  const compiledRules = active.flatMap(source => Array.isArray(source.rules?.requirements) ? source.rules.requirements.map((requirement:any) => ({ ...requirement, source_id:source.id, effective_from:source.effective_from })) : [])
  const evidence = active.map(source => ({ id:source.id,title:source.title,url:source.authority_url,effective_from:source.effective_from,effective_to:source.effective_to }))
  const output = { jurisdiction,as_of:asOf,domains,compiled_rules:compiledRules,evidence,professional_review_required:flags.length>0,review_reasons:flags,coverage:{ verified_sources:active.length, complete:active.length>0 },disclaimer:'Workflow policy compilation is not a legal opinion. Verify primary authorities and obtain qualified jurisdiction-specific review before reliance or issuance.' }
  return { ...output,digest:digest(output) }
}
